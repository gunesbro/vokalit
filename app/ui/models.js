// Models screen: install (with confirmation and progress), cancel, remove.
import { api, el, setMessage, waitForJob } from "./app.js";

// Install jobs survive switching screens: their state lives here, and `screen` is the Models screen open right now
// (null on other screens), which the job following code updates.
const installs = {}; // name -> { progress, log, step, steps, started }
const following = new Set(); // install job ids being followed
let screen = null;
let missedNotice = null; // how an install ended while another screen was open: [text, kind]

// Follows an install job to its end, updating whichever Models screen is open.
async function follow(id, name, title) {
  if (following.has(id)) return;
  following.add(id);
  installs[name] ||= { progress: "", log: "", step: 1, steps: 5 };
  const report = (text, kind) => (screen?.alive() ? screen.report(text, kind) : (missedNotice = [text, kind]));
  try {
    await waitForJob(id, (j) => {
      const [, step, steps] = j.progress.match(/^Step (\d+)\/(\d+)/) || [];
      const last = installs[name];
      installs[name] = { progress: j.progress, log: j.log, started: j.started,
        step: Number(step || last.step), steps: Number(steps || last.steps) };
      screen?.updateProgress(name);
    });
    report(`${title} is installed.`, "info");
  } catch (error) {
    report(/Cancelled|^$/.test(error.message) ? "Install cancelled. Nothing was kept." : `Install failed: ${error.message}`,
      /Cancelled|^$/.test(error.message) ? "info" : "error");
  } finally {
    delete installs[name];
    following.delete(id);
    screen?.refresh();
  }
}

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
    setMessage(message, text, kind);
  }

  async function refresh() {
    try {
      draw(await api("GET", "/api/components"));
    } catch (error) {
      setMessage(message, error.message, "error");
    }
  }

  let busyName = null; // an install running on the server (also one started elsewhere): other Installs wait

  let freeGb = null; // free space on the drive models go to, from the last listing

  function draw({ items, total_gb: total, free_gb: free, installing, install_job: job }) {
    freeGb = free ?? null;
    // An install started before this screen opened (another tab, or the window was reopened): follow it here.
    if (job && !installs[job.name]) {
      installs[job.name] = { progress: "", log: "", step: 1, steps: 5 };
      follow(job.id, job.name, items.find((c) => c.name === job.name)?.title || job.name);
    }
    busyName = installing || Object.keys(installs)[0] || null;
    // Sizes are measured in the background after an install or remove: look again until they are known.
    if (items.some((c) => c.installed && c.frees_gb == null)) setTimeout(() => root.isConnected && refresh(), 3000);
    body.replaceChildren(...[
      el("div", { class: "table-head" }, el("div", {}, "Component"), el("div", {}, "Status"), el("div", {}, "License"), el("div")),
      ...items.map(row),
      total ? el("div", { class: "row total-line" }, el("span", { class: "muted" }, "All components"),
        el("span", { class: "num" }, `${total} GB`, sharedNote(items, total))) : null,
      el("p", { class: "muted small" },
        "Sizes are measured on Windows and can differ slightly. The model name links to its page, which lists supported languages."),
    ].filter(Boolean)); // replaceChildren would show a null as the text "null"
  }

  // What no single row frees: files several components use (PyTorch and common libraries), stored once.
  function sharedNote(items, total) {
    const installed = items.filter((c) => c.installed);
    if (installed.some((c) => c.frees_gb == null)) return null;
    const shared = Math.round((total - installed.reduce((sum, c) => sum + c.frees_gb, 0)) * 10) / 10;
    return shared >= 0.1 ? el("span", { class: "muted", title: "Files several components use, such as PyTorch, are "
      + "stored once. Removing one of them does not free these; removing the last one does." },
    ` \u00b7 ${shared} GB shared between models`) : null;
  }

  function row(model) {
    const job = installs[model.name];
    const state = job ? "installing" : model.installed ? "installed" : "";
    const statusText = job ? installingText(job) : model.installed ? (model.frees_gb == null ? "Installed \u00b7 measuring size\u2026" : `Installed \u00b7 frees ${model.frees_gb} GB`)
      : `Not installed \u00b7 ~${model.disk_gb} GB disk \u00b7 ${model.vram_gb ? `~${model.vram_gb} GB GPU memory` : "runs on the processor"}`;
    const actions = el("div", { class: "row", style: { justifyContent: "flex-end" } });
    const container = el("div", { class: "table-row", "data-model": model.name },
      el("div", {},
        el("div", { class: "row" },
          el("a", { href: model.url, target: "_blank", rel: "noopener", style: { fontSize: "14px", fontWeight: "600", textDecoration: "none" } }, model.title),
          model.recommended ? el("span", { class: "tag" }, "Recommended") : null),
        el("div", { class: "muted" }, model.summary)),
      el("div", {}, el("div", { class: `status ${state}` }, el("span", { class: "dot" }), statusText),
        model.installed && !job ? runtimeLine(model) : null),
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
    // Checked before anything is downloaded (the server checks again)
    const tooFull = freeGb != null && model.needs_gb > freeGb;
    container.append(el("div", { class: "confirm" },
      el("div", {},
        el("strong", {}, `Install ${model.title}?`),
        el("ul", {},
          el("li", {}, model.kind === "tool" && !model.vram_gb
            ? `Disk space: about ${model.disk_gb} GB (the program and its model; runs on the processor)`
            : `Disk space: about ${model.disk_gb} GB (PyTorch with CUDA, libraries and the model; PyTorch files are shared with other installed models)`),
          model.vram_gb ? el("li", {}, `GPU memory: about ${model.vram_gb} GB while it is loaded. Vokalit unloads it `
            + "after 5 minutes unused, and unloads other models when it needs room.") : null,
          freeGb == null ? null : el("li", { class: tooFull ? "warn" : "" }, tooFull
            ? `Not enough free space: it needs about ${model.needs_gb} GB and ${freeGb} GB is free on this drive. `
              + "Free some space or remove a model you do not use."
            : `Free space on this drive: ${freeGb} GB, enough (it needs about ${model.needs_gb} GB with some room to spare`
              + (model.needs_gb < model.disk_gb ? ", less than its size because PyTorch is already installed)." : ").")),
          el("li", {}, `Location: .local/${model.name}/`),
          el("li", {}, model.license.startsWith("CC-BY-NC")
            ? "License: CC-BY-NC \u2014 the model's weights may not be used commercially."
            : `License: ${model.license}`),
          el("li", {}, `Downloads from ${model.downloads}. Nothing else leaves your computer.`))),
      el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => refresh() }, "Cancel"),
      el("button", { class: "btn btn-primary", disabled: tooFull, title: tooFull ? "Not enough free disk space" : null,
        onclick: () => install(model) }, "Install")));
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
      follow(id, model.name, model.title);
    } catch (error) {
      setMessage(message, `Install failed: ${error.message}`, "error");
    }
  }

  // Whether the model is loaded right now (GPU memory, when it unloads itself) and an Unload button.
  function runtimeLine(model) {
    const box = el("div", { class: "runtime small", "data-runtime": model.name });
    paintRuntime(box, model);
    return box;
  }

  function paintRuntime(box, model) {
    const r = model.runtime || { loaded: false };
    if (!r.loaded) return box.replaceChildren(el("span", { class: "faint" }, "\u25cb Not loaded"));
    const where = model.kind === "tool" ? "In memory" : "On GPU";
    const parts = [where, r.vram_gb ? `${r.vram_gb.toFixed(1)} GB` : null, r.mode?.label,
      r.busy ? "generating" : `unloads in ${Math.max(1, Math.ceil(r.unloads_in / 60))} min`].filter(Boolean);
    // replaceChildren would show a null as the text "null": leave out what is not there
    box.replaceChildren(...[el("span", { class: "loaded" }, `\u25cf ${parts.join(" \u00b7 ")}`),
      r.busy ? null : el("button", { class: "btn btn-ghost btn-small", title: "Free its memory now; the next take loads it again",
        onclick: () => api("POST", `/api/models/${model.name}/unload`).then((view) => paintRuntime(box, view),
          (error) => setMessage(message, error.message, "error")) }, "Unload"),
      // Why it runs this way (Higgs: full precision or 8-bit), on its own line
      r.mode?.reason ? el("div", { class: "faint runtime-reason" }, r.mode.reason) : null].filter(Boolean));
  }

  // Loaded models change on their own (a take loads one, idle ones unload): look every few seconds and repaint only
  // those lines, so an open confirmation or install log stays as it is.
  const watcher = setInterval(async () => {
    if (!root.isConnected) { clearInterval(watcher); return; }
    try {
      const { items } = await api("GET", "/api/components");
      for (const model of items) {
        const box = body.querySelector(`[data-runtime="${model.name}"]`);
        if (box && model.installed) paintRuntime(box, model);
      }
    } catch { /* the next look */ }
  }, 5000);

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

  screen = { report, alive: () => root.isConnected, refresh: () => (root.isConnected ? refresh() : undefined),
    updateProgress: (name) => root.isConnected && updateProgress(name) };
  refresh();
}
