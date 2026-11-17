// Models screen: install (with confirmation and progress), cancel, remove.
import { api, el, setMessage, waitForJob } from "./app.js";

// Install jobs survive switching screens.
const installs = {}; // name -> { progress, log, percent }

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

  async function refresh() {
    try {
      draw(await api("GET", "/api/models"));
    } catch (error) {
      setMessage(message, error.message, "error");
    }
  }

  function draw(list) {
    body.replaceChildren(
      el("div", { class: "table-head" }, el("div", {}, "Model"), el("div", {}, "Status"), el("div", {}, "License"), el("div")),
      ...list.map(row),
      el("p", { class: "muted small" },
        "Sizes are measured on Windows and can differ slightly. The model name links to its page, which lists supported languages."));
  }

  function row(model) {
    const job = installs[model.name];
    const state = job ? "installing" : model.installed ? "installed" : "";
    const statusText = job ? `Installing · ${job.percent}%` : model.installed ? `Installed · ${model.size_gb} GB` : "Not installed";
    const actions = el("div", { class: "row", style: { justifyContent: "flex-end" } });
    const container = el("div", { class: "table-row", "data-model": model.name },
      el("div", {},
        el("a", { href: model.url, target: "_blank", rel: "noopener", style: { fontSize: "14px", fontWeight: "600", textDecoration: "none" } }, model.title),
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
      actions.append(el("button", { class: "btn btn-primary", onclick: () => confirmInstall(container, model) }, "Install"));
    }
    return container;
  }

  function progress(job) {
    return el("div", { class: "progress-wrap" },
      el("div", { class: "progress", role: "progressbar", "aria-valuenow": job.percent, "aria-valuemin": 0, "aria-valuemax": 100 },
        el("div", { style: { width: `${job.percent}%` } })),
      el("div", { class: "row muted small num" }, el("div", {}, job.progress || "Starting…")),
      el("details", {}, el("summary", {}, "Show install log"), el("pre", { class: "log" }, job.log || "")));
  }

  function confirmInstall(container, model) {
    container.querySelector(".confirm")?.remove();
    container.append(el("div", { class: "confirm" },
      el("div", {},
        el("strong", {}, `Install ${model.title}?`),
        el("ul", {},
          el("li", {}, `Disk space: about ${model.disk_gb} GB (PyTorch with CUDA, libraries and the model)`),
          el("li", {}, `Location: .local/${model.name}/`),
          el("li", {}, `License: ${model.license}`),
          el("li", {}, "Downloads from PyPI and Hugging Face. Nothing else leaves your computer."))),
      el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => refresh() }, "Cancel"),
      el("button", { class: "btn btn-primary", onclick: () => install(model) }, "Install")));
  }

  function confirmRemove(container, model) {
    container.querySelector(".confirm")?.remove();
    container.append(el("div", { class: "confirm" },
      el("div", {}, el("strong", {}, `Remove ${model.title}?`), " ",
        el("span", { class: "muted" }, `This permanently deletes .local/${model.name}/ and frees ${model.size_gb} GB.`)),
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
      installs[model.name] = { progress: "", log: "", percent: 0 };
      refresh();
      await waitForJob(id, (j) => {
        const percent = Number((j.progress.match(/(\d+)%/) || [])[1] || installs[model.name].percent);
        installs[model.name] = { progress: j.progress, log: j.log, percent };
        if (root.isConnected) updateProgress(model.name);
      });
      setMessage(message, `${model.title} is installed.`, "info");
    } catch (error) {
      setMessage(message, /Cancelled|^$/.test(error.message) ? "Install cancelled. Nothing was kept." : `Install failed: ${error.message}`,
        /Cancelled|^$/.test(error.message) ? "info" : "error");
    } finally {
      delete installs[model.name];
      if (root.isConnected) refresh();
    }
  }

  // Updates the progress block in place so an open log stays open.
  function updateProgress(name) {
    const job = installs[name];
    const container = body.querySelector(`[data-model="${name}"]`);
    const wrap = container?.querySelector(".progress-wrap");
    if (!wrap) return refresh();
    wrap.querySelector(".progress > div").style.width = `${job.percent}%`;
    wrap.querySelector(".progress").setAttribute("aria-valuenow", job.percent);
    wrap.querySelector(".row div").textContent = job.progress || "Starting…";
    const log = wrap.querySelector("pre.log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent = job.log;
    if (atBottom) log.scrollTop = log.scrollHeight;
    container.querySelector(".status").lastChild.textContent = `Installing · ${job.percent}%`;
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
