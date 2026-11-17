// Models screen: install (with confirmation and progress), cancel, remove.
import { api, el, setMessage, waitForJob } from "./app.js";

// Install jobs survive switching screens.
const installs = {}; // name -> { progress, log, step, steps }
let missedNotice = null; // how an install ended while another screen was open: [text, kind]

export async function renderModels(root) {
  const message = el("div", { class: "message" });
  const body = el("div", { class: "models" });
  const gpu = el("div", { class: "muted" });
  api("GET", "/api/system").then(({ gpu: name }) => {
    gpu.textContent = name ? name.replace(/^NVIDIA /, "").replace(/, (\d+) MiB$/, (_, mb) => ` \u00b7 ${Math.round(mb / 1024)} GB`)
      : "No NVIDIA GPU found";
  }).catch(() => {});
  root.append(el("div", { class: "main" },
    el("header", { class: "main-head" },
      el("h1", {}, "Models"),
      el("div", { class: "muted" }, "Run locally on your NVIDIA GPU. Files stay in this project folder; Remove frees all of it."),
      el("div", { class: "spacer" }),
      message,
      gpu),
    el("div", { class: "main-body" }, body)));
  if (missedNotice) {
    setMessage(message, ...missedNotice);
    missedNotice = null;
  }

  function report(text, kind) {
    if (root.isConnected) setMessage(message, text, kind);
    else missedNotice = [text, kind];
  }

  async function refresh() {
    try {
      draw(await api("GET", "/api/components"));
    } catch (error) {
      setMessage(message, error.message, "error");
    }
  }

  let busyName = null; // an install running on the server (also one started elsewhere): other Installs wait

  function draw({ items, total_gb: total, installing }) {
    busyName = installing || Object.keys(installs)[0] || null;
    // Sizes are measured in the background after an install or remove: look again until they are known.
    if (items.some((c) => c.installed && c.frees_gb == null)) setTimeout(() => root.isConnected && refresh(), 3000);
    body.replaceChildren(
      el("div", { class: "table-head" }, el("div", {}, "Component"), el("div", {}, "Status"), el("div", {}, "License"), el("div")),
      ...items.map(row),
      total ? el("div", { class: "row total-line" }, el("span", { class: "muted" }, "All components"),
        el("span", { class: "num" }, `${total} GB`)) : null,
      el("p", { class: "muted small" },
        "Sizes are measured on Windows and can differ slightly. The model name links to its page, which lists supported languages."));
  }

  function row(model) {
    const job = installs[model.name];
    const state = job ? "installing" : model.installed ? "installed" : "";
    const statusText = job ? installingText(job) : model.installed ? (model.frees_gb == null ? "Installed \u00b7 measuring size\u2026" : `Installed \u00b7 frees ${model.frees_gb} GB`)
      : `Not installed \u00b7 ~${model.disk_gb} GB`;
    const actions = el("div", { class: "row", style: { justifyContent: "flex-end" } });
    const container = el("div", { class: "table-row", "data-model": model.name },
      el("div", {},
        el("div", { class: "row" },
          el("a", { href: model.url, target: "_blank", rel: "noopener", style: { fontSize: "14px", fontWeight: "600", textDecoration: "none" } }, model.title),
          model.recommended ? el("span", { class: "tag" }, "Recommended") : null),
        el("div", { class: "muted" }, model.summary)),
      el("div", { class: `status ${state}` }, el("span", { class: "dot" }), statusText),
      el("div", { class: "muted" }, model.license),
      actions);

    if (job) {
      actions.append(el("button", { class: "btn btn-danger", onclick: () => cancel(model) }, "Cancel"));
      container.append(progress(job));
    } else if (model.installed) {
      actions.append(el("button", { class: "btn", onclick: () => confirmRemove(container, model) }, "Remove"));
    } else {
      const waiting = busyName && busyName !== model.name;
      actions.append(el("button", { class: "btn btn-primary", disabled: Boolean(waiting),
        title: waiting ? "Another install is running." : "", onclick: () => confirmInstall(container, model) }, "Install"));
    }
    return container;
  }

  // Download sizes are not known in advance, so instead of a percentage: one segment per step, the running one
  // animated, and the size on disk and time under it.
  function progress(job) {
    return el("div", { class: "progress-wrap" },
      steps(job),
      el("div", { class: "row muted small num" }, el("div", {}, progressText(job))),
      el("details", {}, el("summary", {}, "Show install log"), el("pre", { class: "log" }, job.log || "")));
  }

  function steps(job) {
    const bar = el("div", { class: "steps", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": job.steps },
      ...Array.from({ length: job.steps }, () => el("div")));
    markSteps(bar, job);
    return bar;
  }

  // Changes classes only, so the running segment's animation does not restart on every update.
  function markSteps(bar, job) {
    bar.setAttribute("aria-valuenow", Math.max(0, job.step - 1));
    [...bar.children].forEach((segment, i) => {
      segment.className = i + 1 < job.step ? "done" : i + 1 === job.step ? "running" : "";
    });
  }

  function confirmInstall(container, model) {
    container.querySelector(".confirm")?.remove();
    container.append(el("div", { class: "confirm" },
      el("div", {},
        el("strong", {}, `Install ${model.title}?`),
        el("ul", {},
          el("li", {}, model.kind === "tool"
            ? `Disk space: about ${model.disk_gb} GB (the program and its model; runs on the processor)`
            : `Disk space: about ${model.disk_gb} GB (PyTorch with CUDA, libraries and the model; PyTorch files are shared with other installed models)`),
          el("li", {}, `Location: .local/${model.name}/`),
          el("li", {}, model.license.startsWith("CC-BY-NC")
            ? "License: CC-BY-NC \u2014 the model's weights may not be used commercially."
            : `License: ${model.license}`),
          el("li", {}, "Downloads from PyPI and Hugging Face. Nothing else leaves your computer."))),
      el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => refresh() }, "Cancel"),
      el("button", { class: "btn btn-primary", onclick: () => install(model) }, "Install")));
  }

  function confirmRemove(container, model) {
    container.querySelector(".confirm")?.remove();
    container.append(el("div", { class: "confirm" },
      el("div", {}, el("strong", {}, `Remove ${model.title}?`), " ",
        el("span", { class: "muted" }, `This permanently deletes .local/${model.name}/` + (model.frees_gb == null ? "." : ` and frees ${model.frees_gb} GB.`))),
      el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => refresh() }, "Keep"),
      el("button", { class: "btn btn-danger", onclick: (event) => {
        for (const button of container.querySelectorAll(".confirm button")) button.disabled = true;
        event.currentTarget.textContent = "Removing…";
        remove(model);
      } }, "Remove")));
  }

  async function install(model) {
    setMessage(message, "");
    try {
      const { id } = await api("POST", `/api/models/${model.name}/install`);
      installs[model.name] = { progress: "", log: "", step: 1, steps: 5 };
      refresh();
      await waitForJob(id, (j) => {
        const [, step, steps] = j.progress.match(/^Step (\d+)\/(\d+)/) || [];
        const last = installs[model.name];
        installs[model.name] = { progress: j.progress, log: j.log, started: j.started,
          step: Number(step || last.step), steps: Number(steps || last.steps) };
        if (root.isConnected) updateProgress(model.name);
      });
      report(`${model.title} is installed.`, "info");
    } catch (error) {
      report(/Cancelled|^$/.test(error.message) ? "Install cancelled. Nothing was kept." : `Install failed: ${error.message}`,
        /Cancelled|^$/.test(error.message) ? "info" : "error");
    } finally {
      delete installs[model.name];
      if (root.isConnected) refresh();
    }
  }

  // The elapsed time is counted here, every second, so it moves even while the server is busy.
  function progressText(job) {
    if (!job.progress) return "Starting\u2026";
    if (!job.started) return job.progress;
    const seconds = Math.max(0, Math.floor(Date.now() / 1000 - job.started));
    return `${job.progress} \u00b7 ${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  }

  const ticker = setInterval(() => {
    if (!root.isConnected) return clearInterval(ticker);
    for (const name of Object.keys(installs)) {
      const line = body.querySelector(`[data-model="${name}"] .progress-wrap .row div`);
      if (line) line.textContent = progressText(installs[name]);
    }
  }, 1000);

  function installingText(job) {
    return `Installing \u00b7 step ${job.step} of ${job.steps}`;
  }

  // Updates the progress block in place so an open log stays open.
  function updateProgress(name) {
    const job = installs[name];
    const container = body.querySelector(`[data-model="${name}"]`);
    const wrap = container?.querySelector(".progress-wrap");
    if (!wrap) return refresh();
    const bar = wrap.querySelector(".steps");
    if (bar.children.length === job.steps) markSteps(bar, job);
    else bar.replaceWith(steps(job));
    wrap.querySelector(".row div").textContent = progressText(job);
    const log = wrap.querySelector("pre.log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent = job.log;
    if (atBottom) log.scrollTop = log.scrollHeight;
    container.querySelector(".status").lastChild.textContent = installingText(job);
  }

  async function cancel(model) {
    await api("POST", `/api/models/${model.name}/cancel`);
    setMessage(message, "Cancelling…", "info");
  }

  async function remove(model) {
    try {
      await api("POST", `/api/models/${model.name}/remove`);
      setMessage(message, `${model.title} was removed.`, "info");
    } catch (error) {
      setMessage(message, error.message, "error");
    }
    refresh();
  }

  refresh();
}
