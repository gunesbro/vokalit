// Dub screen: an audio or video file's sentences spoken again in another language, each in its own original voice.
import { api, editableTitle, el, icon, ICONS, lastOpened, rememberOpened, revealButton, setMessage, waitForJob }
  from "./app.js";
import { decode, encodeWav } from "./audio.js";
import { clipsToPlay, formatTime, pasteTranslations, pickSelected } from "./script.js";
import { popover, searchSelect, sliders } from "./settings.js";
import { timeline } from "./timeline.js";
import { player } from "./waveform.js";

const AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac"];
const VIDEO_TYPES = ["mp4", "webm"];
const LONG_MINUTES = 20; // longer files are decoded in memory and take Whisper long: a warning before import
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const megabytes = (bytes) => `${(bytes / 1e6).toFixed(bytes < 1e7 ? 1 : 0)} MB`;
const close = () => document.querySelector(".popover")?.dispatchEvent(new Event("close"));

export async function renderDub(root) {
  const list = el("div", { class: "list" });
  const main = el("div", { class: "main" });
  const fileInput = el("input", { type: "file", class: "sr-only", accept: [...AUDIO_TYPES, ...VIDEO_TYPES].map((e) => `.${e}`).join(","),
    onchange: () => { const file = fileInput.files[0]; fileInput.value = ""; if (file) importFile(file); } });
  root.append(
    el("aside", { class: "sidebar" },
      el("div", { class: "sidebar-head" }, el("h2", {}, "Dubs"),
        el("button", { class: "btn icon-btn", title: "New dub from a video or audio file", "aria-label": "New dub",
          onclick: () => fileInput.click() }, icon(ICONS.plus)), fileInput),
      list),
    main);
  root.addEventListener("dragover", (e) => e.preventDefault());
  root.addEventListener("drop", (e) => { e.preventDefault(); const file = e.dataTransfer.files[0]; if (file) importFile(file); });

  let items = [];
  let models = [];
  let whisper = false;
  let formats = [];
  let view = null; // the open dub's screen (see openDub), stopped when another opens
  let transcribeNext = null; // a dub just imported: transcribed once it is open
  const selectedId = () => pickSelected(items.map((d) => d.id), (location.hash.match(/^#\/dub\/([0-9-]+)/) || [])[1],
    lastOpened("dub"));

  async function refreshList() {
    items = await api("GET", "/api/dubs");
    const current = selectedId();
    list.replaceChildren(...items.map((d) => el("a", { class: "list-item", href: `#/dub/${d.id}`,
      "aria-current": d.id === current ? "true" : "false" },
    el("div", { class: "name" }, d.name),
    el("div", { class: "sub" }, `${d.kind === "video" ? "Video" : "Audio"}${d.duration ? ` \u00b7 ${formatTime(d.duration)}` : ""}`
      + ` \u00b7 ${plural(d.clips, "sentence")}`))));
    if (!items.length) list.append(el("p", { class: "muted small pad" }, "No dubs yet."));
  }

  async function show() {
    view?.stop();
    view = null;
    const id = selectedId();
    if (!id) {
      main.replaceChildren(el("div", { class: "empty" }, el("h1", {}, "Dub a video or recording"),
        el("p", {}, "Drop a video (MP4, WebM) or an audio file here. Vokalit finds the sentences and their times; you "
          + "write the translations, and each sentence is spoken in the new language in its own original voice."),
        el("button", { class: "btn btn-primary", onclick: () => fileInput.click() }, "Choose a file")));
      return;
    }
    rememberOpened("dub", id);
    try {
      view = openDub(main, await api("GET", `/api/dubs/${id}`), { models, whisper, formats, refreshList });
      if (transcribeNext === id) {
        transcribeNext = null;
        view.transcribe();
      }
    } catch (error) {
      main.replaceChildren(el("div", { class: "empty" }, el("p", {}, error.message)));
    }
  }

  // Reads the file's sound in the window (no ffmpeg), confirms size and length, then creates the dub and transcribes.
  async function importFile(file) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    const message = el("div", { class: "message" });
    const card = el("div", { class: "empty" }, el("h1", {}, file.name), message);
    view?.stop();
    view = null;
    main.replaceChildren(card);
    if (![...AUDIO_TYPES, ...VIDEO_TYPES].includes(ext)) {
      return setMessage(message, "Vokalit cannot open this file. Use a video (MP4, WebM) or an audio file (WAV, MP3, "
        + "M4A, OGG, FLAC).", "error");
    }
    setMessage(message, "Reading the sound\u2026");
    let audio;
    try {
      audio = await decode(file);
    } catch {
      return setMessage(message, VIDEO_TYPES.includes(ext)
        ? "This window cannot read this video's sound. Add the video's audio as a separate file (WAV, MP3, M4A, OGG "
          + "or FLAC)." : "Cannot read this file. Use WAV, MP3, M4A, OGG or FLAC.", "error");
    }
    const seconds = audio.samples.length / audio.sampleRate;
    const long = seconds > LONG_MINUTES * 60;
    setMessage(message, "");
    card.append(...[
      el("p", {}, `${megabytes(file.size)} \u00b7 ${formatTime(seconds)}. The file is copied into Vokalit's folder.`),
      long && el("p", { class: "warn" }, `This file is ${Math.round(seconds / 60)} minutes long. Dubbing is made for clips `
        + `up to about ${LONG_MINUTES} minutes: a long file uses a lot of memory, and Whisper takes a long time.`),
      el("div", { class: "row" },
        el("button", { class: "btn btn-primary", onclick: async (e) => {
          e.target.disabled = true;
          setMessage(message, "Importing\u2026");
          try {
            const name = file.name.replace(/\.[^.]+$/, "");
            const dub = await api("POST", `/api/dubs?name=${encodeURIComponent(name)}&ext=${ext}`, file);
            await api("POST", `/api/dubs/${dub.id}/audio`, encodeWav(audio.samples, audio.sampleRate));
            audio = null;
            rememberOpened("dub", dub.id);
            transcribeNext = dub.id; // the dub opens through the address change, then transcribes
            if (location.hash === `#/dub/${dub.id}`) await onHash();
            else location.hash = `#/dub/${dub.id}`;
          } catch (error) {
            e.target.disabled = false;
            setMessage(message, error.message, "error");
          }
        } }, "Import"),
        el("button", { class: "btn btn-ghost", onclick: () => show() }, "Cancel"))].filter(Boolean));
  }

  const onHash = async () => {
    if (!location.hash.startsWith("#/dub") || !root.isConnected) {
      view?.stop();
      window.removeEventListener("hashchange", onHash);
      return;
    }
    await refreshList();
    show();
  };
  window.addEventListener("hashchange", onHash);

  [models, formats] = await Promise.all([api("GET", "/api/models"), api("GET", "/api/export-formats").catch(() => [])]);
  whisper = await api("GET", "/api/components")
    .then(({ items: parts }) => Boolean(parts.find((c) => c.name === "whisper")?.installed)).catch(() => false);
  await refreshList();
  show();
}

// One dub: header, preview with the timeline, and the sentence list. Returns {stop, transcribe}.
function openDub(main, initial, { models, whisper, formats, refreshList }) {
  let dub = initial;
  let selected = null;
  let job = null; // {id, kind, clips: Set}
  const message = el("div", { class: "message" });
  const fail = (error) => setMessage(message, error.message, "error");
  const installed = models.filter((m) => m.installed);
  const model = () => models.find((m) => m.name === dub.model);
  const sourceOf = (clip) => dub.tracks[0].clips.find((c) => c.id === clip.source_clip);
  const takeOf = (clip) => clip.takes.find((t) => t.file === clip.selected);
  const fileUrl = (file) => `/files/dubs/${dub.id}/${file}`;
  const path = (suffix = "") => `/api/dubs/${dub.id}${suffix}`;

  const header = el("header", { class: "main-head dub-head" });
  const stage = el("div", { class: "dub-stage" });
  const rows = el("div", { class: "dub-rows" });
  const play = previewPlayer();
  const lanes = timeline({ duration: dub.source.duration || 1, onSeek: (t) => play.seek(t),
    onSelect: (laneId, clipId) => choose(laneId === "dub" ? clipId : dub.tracks[1].clips.find((c) => c.source_clip === clipId)?.id),
    onMove: (clipId, start) => change(api("PATCH", path(`/clips/${clipId}`), { start })) });
  main.replaceChildren(header, el("div", { class: "main-body dub-body" }, stage, lanes.element, rows),
    el("footer", { class: "dub-foot" }, message));

  async function change(request) {
    try {
      apply(await request);
    } catch (error) { fail(error); }
  }

  function apply(data) {
    dub = data;
    if (data.notice) setMessage(message, data.notice, "warn");
    draw();
    play.changed();
  }

  function choose(clipId) {
    selected = clipId;
    lanes.select(clipId);
    for (const row of rows.querySelectorAll(".dub-row")) row.classList.toggle("selected", row.dataset.clip === clipId);
    rows.querySelector(`.dub-row[data-clip="${clipId}"]`)?.scrollIntoView({ block: "nearest" });
  }

  // Redraws (a job finishing, a saved change) keep text typed but not saved yet, and the focus and caret in it.
  function draw() {
    const active = document.activeElement?.closest?.(".dub-rows") ? document.activeElement : null;
    const caret = active && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
    const unsaved = [...rows.querySelectorAll("textarea")].filter((t) => t.value !== t.dataset.saved)
      .map((t) => [t.getAttribute("aria-label"), t.value]);
    drawHeader();
    drawLanes();
    drawRows();
    for (const [label, value] of unsaved) {
      const box = rows.querySelector(`[aria-label="${CSS.escape(label)}"]`);
      if (box) box.value = value;
    }
    const again = active && rows.querySelector(`[aria-label="${CSS.escape(active.getAttribute("aria-label"))}"]`);
    if (again) {
      again.focus();
      if (caret) again.setSelectionRange(...caret);
    }
  }

  // --- Header ----------------------------------------------------------------------------------

  function drawHeader() {
    const name = el("input", { class: "title-input", value: dub.name, "aria-label": "Dub name", onchange: () => {
      if (!name.value.trim()) { name.value = dub.name; return; }
      change(api("PATCH", path(), { name: name.value.trim() })).then(refreshList);
    } });
    const chosen = model();
    const modelSelect = el("select", { class: "select", "aria-label": "Model", title: "The model that speaks the translations",
      onchange: () => change(api("PATCH", path(), { model: modelSelect.value })) },
    !chosen && el("option", { value: "" }, installed.length ? "Choose a model" : "No model installed"),
    installed.map((m) => el("option", { value: m.name }, m.title)));
    modelSelect.value = chosen?.name || "";
    const languages = (chosen ? chosen.languages : models.flatMap((m) => m.languages))
      .filter((l, i, all) => all.findIndex((x) => x.code === l.code) === i);
    const target = searchSelect({ label: "Target language", placeholder: "Search languages", small: false,
      value: dub.target_language, options: languages.map((l) => ({ value: l.code, label: l.name })),
      onChange: (code) => change(api("PATCH", path(), { target_language: code })) });
    const sourceName = models.flatMap((m) => m.languages).find((l) => l.code === dub.source.language)?.name;
    const settingsButton = el("button", { class: "btn", disabled: !chosen, onclick: () => popover(settingsButton,
      el("div", { class: "menu settings-pop" }, settingsPanel(chosen))) }, "Settings");
    const missing = dub.tracks[1].clips.filter((c) => !c.selected && c.translation.trim()).map((c) => c.id);
    const busy = Boolean(job);
    const more = el("button", { class: "btn btn-ghost icon-btn", "aria-label": "More", title: "Transcribe again or delete" },
      "\u22ef");
    more.onclick = () => popover(more, el("div", { class: "menu" },
      el("button", { class: "menu-item", disabled: busy || !whisper, onclick: () => confirmTranscribe(more) }, "Transcribe again\u2026"),
      el("button", { class: "menu-item danger", onclick: () => confirmDelete(more) }, "Delete dub\u2026")), { align: "right" });
    const exportButton = el("button", { class: "btn", disabled: !dub.source.duration, title: "Mix the dub into one audio file",
      onclick: () => popover(exportButton, exportPanel(), { align: "right" }) }, "Export");
    header.replaceChildren(
      editableTitle(name),
      el("span", { class: "muted small" }, sourceName ? `From ${sourceName}` : "Not transcribed yet"),
      el("label", { class: "row muted" }, "To", target),
      modelSelect, settingsButton,
      el("div", { class: "spacer" }),
      job ? el("span", { class: "row small muted" }, el("span", { class: "job-progress" }, job.progress || "Working\u2026"),
        el("button", { class: "btn btn-small", onclick: () => api("POST", `/api/jobs/${job.id}/cancel`).catch(fail) }, "Cancel"))
        : el("button", { class: "btn btn-primary", disabled: !missing.length || !chosen,
          title: !chosen ? "Choose a model first" : missing.length ? "Generate every translated sentence without a take"
            : "Every translated sentence has a take", onclick: () => generate(missing) },
        missing.length ? `Generate ${plural(missing.length, "sentence")}` : "Generate missing"),
      exportButton, more);
  }

  function settingsPanel(chosen) {
    const overrides = dub.settings[chosen.name] || {};
    const defaults = Object.fromEntries(chosen.settings.map((s) => [s.key, s.default]));
    return sliders(chosen.settings, { ...defaults, ...overrides }, defaults,
      (spec, value, base) => (value === base ? "Default" : `Default: ${base}`),
      (key, value) => change(api("PATCH", path(), { settings: { ...dub.settings, [chosen.name]: { ...overrides, [key]: value } } })),
      `dub:${dub.id}`);
  }

  function exportPanel() {
    return el("div", { class: "menu" }, formats.map((f) => el("button", { class: "menu-item", onclick: async () => {
      close();
      setMessage(message, "Exporting\u2026");
      try {
        const { path: file } = await api("POST", path("/export"), { format: f.id });
        message.replaceChildren(`Exported ${file.split("/").pop()}. `, revealButton(file, { text: true }));
        message.className = "message info";
      } catch (error) { fail(error); }
    } }, el("strong", {}, f.label), el("span", { class: "faint small" }, f.note))));
  }

  function confirmTranscribe(anchor) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, "Transcribe again?"),
      el("div", { class: "muted small" }, "This replaces every sentence, translation and take."),
      el("button", { class: "btn btn-danger", onclick: () => { close(); transcribe(); } }, "Transcribe again")), { align: "right" });
  }

  function confirmDelete(anchor) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete \u201c${dub.name}\u201d?`),
      el("div", { class: "muted small" }, "Its copy of the file, the takes and the exports are removed permanently."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        close();
        try {
          await api("DELETE", path());
          play.stop();
          location.hash = "#/dub";
          await refreshList();
          window.dispatchEvent(new HashChangeEvent("hashchange"));
        } catch (error) { fail(error); }
      } }, "Delete")), { align: "right" });
  }

  // --- Jobs ------------------------------------------------------------------------------------

  async function follow(started, kind, clips = []) {
    job = { id: started.id, kind, clips: new Set(clips), progress: "" };
    draw();
    try {
      apply(await waitForJob(started.id, (update) => {
        if (job && update.progress !== job.progress) {
          job.progress = update.progress;
          const node = header.querySelector(".job-progress");
          if (node) node.textContent = update.progress;
        }
      }));
      if (kind === "transcribe" && !dub.notice) setMessage(message, `Found ${plural(dub.tracks[0].clips.length, "sentence")}. Write `
        + "the translations, then generate.");
    } catch (error) {
      if (error.cancelled) setMessage(message, "Cancelled.");
      else fail(error);
      apply(await api("GET", path()).catch(() => dub));
    } finally {
      job = null;
      draw();
      refreshList().catch(() => {});
    }
  }

  async function transcribe() {
    if (!whisper) return setMessage(message, "Install Whisper on the Models screen to find the sentences.", "warn");
    try {
      setMessage(message, "Whisper is listening on the CPU; a long file takes a while.");
      await follow(await api("POST", path("/transcribe"), {}), "transcribe");
    } catch (error) { fail(error); }
  }

  async function generate(ids) {
    try {
      await follow(await api("POST", path("/generate"), { clips: ids }), "generate", ids);
    } catch (error) { fail(error); }
  }

  // --- Timeline and rows -----------------------------------------------------------------------

  function drawLanes() {
    const sources = dub.tracks[0].clips;
    lanes.setLanes([
      { id: "original", label: "Original", draggable: false,
        clips: sources.map((c) => ({ id: c.id, start: c.start, end: c.end, state: "source", title: c.text })) },
      { id: "dub", label: "Dub", draggable: true, clips: dub.tracks[1].clips.map((c) => {
        const source = sourceOf(c);
        const length = takeOf(c)?.duration ?? (source ? source.end - source.start : 1);
        return { id: c.id, start: c.start, end: c.start + length, state: dub.fit[c.id]?.state || "missing",
          title: c.translation || "No translation yet" };
      }) },
    ]);
    if (selected) lanes.select(selected);
  }

  function drawRows() {
    const sources = dub.tracks[0].clips;
    const clips = dub.tracks[1].clips;
    if (!clips.length) {
      rows.replaceChildren(el("div", { class: "empty small" }, dub.source.language
        ? el("p", { class: "muted" }, "No sentences. Transcribe again, or import another file.")
        : whisper ? el("button", { class: "btn btn-primary", disabled: Boolean(job), onclick: transcribe }, "Find the sentences")
          : el("p", { class: "muted" }, "Install Whisper on the ", el("a", { href: "#/models" }, "Models screen"),
            " to find the sentences and their times.")));
      return;
    }
    const ids = clips.map((c) => c.id);
    rows.replaceChildren(...clips.map((clip, i) => {
      const source = sourceOf(clip);
      const fit = dub.fit[clip.id] || { state: "missing" };
      // Saved when the box loses the focus (not on "change": a redraw that keeps typed text would hide the change).
      const original = el("textarea", { class: "textarea", rows: 2, value: source.text, "aria-label": `Sentence ${i + 1}`,
        "data-saved": source.text,
        title: "What is said. It is also the transcript of the voice sample, so correct it if Whisper misheard.",
        onblur: () => original.value !== original.dataset.saved
          && change(api("PATCH", path(`/source/${source.id}`), { text: original.value })) });
      const translation = el("textarea", { class: "textarea", rows: 2, value: clip.translation, "data-saved": clip.translation,
        placeholder: "Translation", "aria-label": `Translation of sentence ${i + 1}`,
        onblur: () => translation.value !== translation.dataset.saved
          && change(api("PATCH", path(`/clips/${clip.id}`), { translation: translation.value })) });
      translation.addEventListener("paste", (e) => {
        const text = e.clipboardData.getData("text");
        if (!/\n/.test(text.trim())) return;
        e.preventDefault();
        pasteAll(pasteTranslations(ids, i, text));
      });
      const voice = el("select", { class: "select select-small", "aria-label": `Voice from, sentence ${i + 1}`,
        title: "Whose voice and mood the sentence copies. A very short sentence clones weakly: pick a longer one of the same speaker.",
        onchange: () => change(api("PATCH", path(`/clips/${clip.id}`), { voice_from: voice.value })) },
      sources.map((s, n) => el("option", { value: s.id }, s.id === clip.source_clip ? "This sentence"
        : `${n + 1} \u00b7 ${s.text.slice(0, 28)}${s.text.length > 28 ? "\u2026" : ""}`)));
      voice.value = clip.voice_from;
      const generating = job?.kind === "generate" && job.clips.has(clip.id);
      const take = takeOf(clip);
      const status = fit.state === "long" ? el("span", { class: "warn small" }, `${fit.over.toFixed(1)} s too long`)
        : fit.state === "fits" ? el("span", { class: "ok small" }, "Fits") : el("span", { class: "faint small" }, "No take yet");
      const takes = clip.takes.length > 1 && el("select", { class: "select select-small", "aria-label": `Take, sentence ${i + 1}`,
        onchange: (e) => change(api("POST", path(`/clips/${clip.id}/select`), { file: e.target.value })) },
      clip.takes.map((t, n) => el("option", { value: t.file, selected: t.file === clip.selected }, `Take ${n + 1} \u00b7 seed ${t.seed}`)));
      const remove = el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Delete sentence", title: "Delete this sentence" },
        icon(ICONS.trash));
      remove.onclick = () => popover(remove, el("div", { class: "menu confirm-menu" },
        el("strong", {}, `Delete sentence ${i + 1}?`),
        el("div", { class: "muted small" }, "Its translation and takes are removed too."),
        el("button", { class: "btn btn-danger", onclick: () => { close(); change(api("DELETE", path(`/source/${source.id}`))); } },
          "Delete")), { align: "right" });
      const row = el("div", { class: `dub-row ${clip.id === selected ? "selected" : ""}`, "data-clip": clip.id },
        el("button", { class: "dub-time num faint small link-btn", title: "Play from here",
          onclick: () => { choose(clip.id); play.seek(clip.start, true); } },
        `${i + 1} \u00b7 ${formatTime(source.start)}\u2013${formatTime(source.end)}`),
        original, translation,
        el("div", { class: "dub-actions" },
          el("div", { class: "row" }, voice, status),
          el("div", { class: "row" },
            generating ? el("span", { class: "small muted" }, "Generating\u2026")
              : el("button", { class: "btn btn-small", disabled: Boolean(job) || !clip.translation.trim() || !model(),
                title: !clip.translation.trim() ? "Write the translation first" : !model() ? "Choose a model first" : "",
                onclick: () => generate([clip.id]) }, clip.takes.length ? "Again" : "Generate"),
            take && player(fileUrl(take.file), { buckets: 24, showTime: false, label: "Play the take" }),
            takes, remove)));
      row.addEventListener("focusin", () => choose(clip.id));
      return row;
    }));
  }

  async function pasteAll(values) {
    try {
      for (const [id, text] of Object.entries(values)) apply(await api("PATCH", path(`/clips/${id}`), { translation: text }));
      setMessage(message, `Pasted ${plural(Object.keys(values).length, "translation")}.`);
    } catch (error) { fail(error); }
  }

  // --- Preview ---------------------------------------------------------------------------------

  // The video (muted) or a plain clock, with the original underneath at its volume and the selected takes at their
  // starts, through Web Audio. Changes (a dragged clip, a new take, the volume) restart from the current time.
  function previewPlayer() {
    const video = dub.source.kind === "video" ? el("video", { class: "dub-video", muted: true, playsinline: true,
      preload: "auto", src: fileUrl(dub.source.file) }) : null;
    if (video) video.muted = true;
    const button = el("button", { class: "btn icon-btn transport-play", "aria-label": "Play", title: "Play (Space)" }, icon(ICONS.play));
    const clock = el("span", { class: "num small muted" }, "0:00");
    const volume = el("input", { type: "range", min: 0, max: 1, step: 0.05, value: dub.original_volume,
      "aria-label": "Original volume", title: "The original under the dub (music, effects). 0 = the dub alone." });
    const volumeLabel = el("span", { class: "num small muted" }, `${Math.round(dub.original_volume * 100)} %`);
    stage.replaceChildren(video || el("div", { class: "dub-audio-only faint small" }, "Audio file \u2014 no picture"),
      el("div", { class: "row dub-transport" }, button, clock, el("div", { class: "spacer" }),
        el("label", { class: "row small muted" }, "Original", volume, volumeLabel)));
    if (video) video.addEventListener("error", () => stage.querySelector(".dub-video")?.replaceWith(
      el("div", { class: "dub-audio-only warn small" }, "This window cannot show this video; the dub plays without the picture.")));

    const buffers = new Map(); // url -> Promise<AudioBuffer>
    let context = null;
    let gain = null;
    let sources = [];
    let playing = false;
    let origin = 0; // media time at contextStart
    let contextStart = 0;
    let time = 0;
    let frame = 0;
    const load = (url) => {
      if (!buffers.has(url)) buffers.set(url, fetch(url).then((r) => r.arrayBuffer()).then((b) => context.decodeAudioData(b)));
      return buffers.get(url);
    };
    const now = () => (playing ? origin + context.currentTime - contextStart : time);

    async function start(at) {
      context ||= new AudioContext();
      const clips = dub.tracks[1].clips.filter((c) => takeOf(c)).map((c) => ({ id: c.id, start: c.start,
        duration: takeOf(c).duration, url: fileUrl(c.selected) }));
      const [original, ...takes] = await Promise.all([load(fileUrl("audio.wav")), ...clips.map((c) => load(c.url))]);
      stopSources();
      gain = context.createGain();
      gain.gain.value = Number(volume.value);
      gain.connect(context.destination);
      contextStart = context.currentTime + 0.05;
      origin = at;
      const base = context.createBufferSource();
      base.buffer = original;
      base.connect(gain);
      base.start(contextStart, at);
      sources = [base];
      for (const item of clipsToPlay(clips, at)) {
        const source = context.createBufferSource();
        source.buffer = takes[clips.findIndex((c) => c.id === item.id)];
        source.connect(context.destination);
        source.start(contextStart + item.delay, item.offset);
        sources.push(source);
      }
      playing = true;
      if (video) { video.currentTime = at; video.play().catch(() => {}); }
      button.replaceChildren(icon(ICONS.pause));
      tick();
    }

    function stopSources() {
      for (const source of sources) { try { source.stop(); } catch { /* already ended */ } }
      sources = [];
    }

    function pause() {
      time = now();
      playing = false;
      stopSources();
      cancelAnimationFrame(frame);
      video?.pause();
      button.replaceChildren(icon(ICONS.play));
    }

    function tick() {
      const t = Math.min(now(), dub.source.duration || 0);
      clock.textContent = formatTime(t);
      lanes.setTime(t);
      if (video && Math.abs(video.currentTime - t) > 0.25) video.currentTime = t;
      if (playing && t >= (dub.source.duration || 0)) { pause(); time = 0; return; }
      if (playing) frame = requestAnimationFrame(tick);
    }

    button.onclick = () => (playing ? pause() : start(time).catch(fail));
    volume.oninput = () => { volumeLabel.textContent = `${Math.round(volume.value * 100)} %`; if (gain) gain.gain.value = Number(volume.value); };
    volume.onchange = () => api("PATCH", path(), { original_volume: Number(volume.value) }).then((d) => { dub = d; }, fail);
    const onKey = (e) => {
      if (e.code !== "Space" || e.target.closest("input, textarea, select, button") || !stage.isConnected) return;
      e.preventDefault();
      button.click();
    };
    document.addEventListener("keydown", onKey);

    return {
      seek(t, andPlay = false) {
        time = t;
        if (playing || andPlay) start(t).catch(fail);
        else { clock.textContent = formatTime(t); lanes.setTime(t); if (video) video.currentTime = t; }
      },
      changed() {
        // Take names repeat after transcribing again (takes/d1-1.wav): decode takes afresh, keep the original.
        for (const url of [...buffers.keys()]) if (url !== fileUrl("audio.wav")) buffers.delete(url);
        if (playing) start(now()).catch(fail);
      },
      stop() { pause(); document.removeEventListener("keydown", onKey); context?.close(); },
    };
  }

  draw();
  if (dub.notice) setMessage(message, dub.notice, "warn");
  // A job started before the screen was left keeps running on the server: follow it again.
  api("GET", path("/jobs")).then(([running]) => {
    if (running && !job && main.isConnected) follow(running, running.kind, running.clips);
  }).catch(() => {});
  return { stop: () => play.stop(), transcribe };
}
