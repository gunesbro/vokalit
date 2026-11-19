// Dub screen: an audio or video file's sentences spoken again in another language, each in its own original voice.
import { api, editableTitle, el, icon, ICONS, lastOpened, rememberOpened, revealButton, setMessage, waitForJob }
  from "./app.js";
import { decode, encodeWav } from "./audio.js";
import { clampSize, clipAt, clipFilter, clipsToPlay, MAX_SPEEDUP, createHistory, formatTime, onlyModel, parseTranslations,
  pasteTranslations, pickSelected, transcriptForTranslation, visibleRows, volumeRamps } from "./script.js";
import { popover, searchSelect, sliders } from "./settings.js";
import { timeline } from "./timeline.js";
import { player } from "./waveform.js";

const AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac"];
const VIDEO_TYPES = ["mp4", "webm"];
const LONG_MINUTES = 20; // longer files are decoded in memory and take Whisper long: a warning before import
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const megabytes = (bytes) => `${(bytes / 1e6).toFixed(bytes < 1e7 ? 1 : 0)} MB`;
const close = () => document.querySelector(".popover")?.dispatchEvent(new Event("close"));
const histories = new Map(); // dub id -> undo history, kept while the app runs (across screen changes)
const openLanguage = new Map(); // dub id -> the language shown, kept across screen changes
const WAVE_PER_SECOND = 50; // waveform values per second of the original
// Pane sizes, dragged by the user and kept between runs: the right column's width and the timeline's lane height.
const SIZES = { right: 400, lane: 22 }; // the defaults; the lane default is also the smallest
const MIN_TABLE = 360;
const speedText = (speed) => `${speed.toFixed(2)}\u00d7`;
const FILTERS = { all: "All", untranslated: "Untranslated", missing: "No take", long: "Too long", "long-fit": "Can fit",
  "long-fitted": "Fitted", "long-shorter": "Need shorter", kept: "Original" };
// Why a too-long take cannot be fitted, or null when it can.
const cannotFit = (clipFit) => (clipFit.need == null ? "No time before the next sentence: move it or shorten the translation"
  : clipFit.need > MAX_SPEEDUP ? `Needs ${speedText(clipFit.need)}: shorten the translation` : null);
const ROW = 38; // px, one sentence row; only the rows in view (and OVERSCAN more each side) are drawn
const OVERSCAN = 10;
const MIN_RIGHT = 320;
const MIN_ABOVE_TIMELINE = 200;
const SPLIT = 7; // px, a separator's width
const sizes = (() => {
  try { return { ...SIZES, ...JSON.parse(localStorage.getItem("vokalit.dubSizes") || "{}") }; } catch { return { ...SIZES }; }
})();
const saveSizes = () => {
  try { localStorage.setItem("vokalit.dubSizes", JSON.stringify(sizes)); } catch { /* storage may be unavailable */ }
};
const LISTENING = "Whisper is finding the sentences on the CPU; a long file takes a while.";
const typing = (target) => Boolean(target?.closest?.("input, textarea, select, [contenteditable]"));

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
    el("div", { class: "name", title: d.name }, d.name),
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

// One dub, laid out like a subtitle editor: a sentence table (left), the video and the selected sentence (right), and
// the timeline (bottom). Every change the user makes goes through act(), so it can be undone. Returns {stop, transcribe}.
function openDub(main, initial, { models, whisper, formats, refreshList }) {
  let dub = initial;
  let selected = null;
  let filter = "all";
  let job = null; // {id, kind, clips: Set, progress}
  if (!histories.has(dub.id)) histories.set(dub.id, createHistory(100));
  // Read on every use: Transcribe again starts a new history. Steps return the dub as saved, and whichever screen is
  // open applies it, so undo works after leaving the screen and coming back.
  const history = () => histories.get(dub.id);
  let stopped = false;
  const message = el("div", { class: "message" });
  const fail = (error) => setMessage(message, error.message, "error");
  const installed = models.filter((m) => m.installed);
  // The language shown: its own translations, takes, timing, model and settings.
  let lang = openLanguage.get(dub.id);
  const tracks = () => dub.tracks.slice(1);
  const track = () => tracks().find((t) => t.language === lang) || tracks()[0];
  const fit = () => dub.fit[track().language] || {};
  const q = (code = track().language) => `?language=${encodeURIComponent(code)}`;
  const model = () => models.find((m) => m.name === track().model);
  const clips = () => track().clips;
  const sources = () => dub.tracks[0].clips;
  // Lookups built once per dub and language, not per row: a dub can have tens of thousands of sentences.
  let index = null;
  const lookup = () => {
    if (index?.dub !== dub || index.language !== track().language) {
      const number = new Map(clips().map((c, i) => [c.id, i + 1]));
      const source = new Map(sources().map((c) => [c.id, c]));
      index = { dub, language: track().language, number, source }; // set first: lengthOf below reads sources
      const sorted = clips().map((c) => ({ id: c.id, start: c.start, length: lengthOf(c) })).sort((a, b) => a.start - b.start);
      Object.assign(index, { sorted, longest: sorted.reduce((most, c) => Math.max(most, c.length), 0) });
    }
    return index;
  };
  const sourceOf = (clip) => lookup().source.get(clip.source_clip);
  const takeOf = (clip) => clip.takes.find((t) => t.file === clip.selected);
  const numberOf = (clipId) => lookup().number.get(clipId) || 0;
  const isKept = (clip) => Boolean(sourceOf(clip)?.keep_original);
  const keptRanges = () => sources().filter((s) => s.keep_original).map((s) => ({ start: s.start, end: s.end }));
  const sourceLength = (clip) => ((sourceOf(clip)?.end ?? 0) - (sourceOf(clip)?.start ?? 0)) || 1;
  // On the timeline a clip is as long as its take, or as its sentence when it has none or keeps the original.
  const lengthOf = (clip) => (isKept(clip) ? sourceLength(clip) : takeOf(clip)?.duration ?? sourceLength(clip));
  const fileUrl = (file) => `/files/dubs/${dub.id}/${file}`;
  const path = (suffix = "") => `/api/dubs/${dub.id}${suffix}`;
  const languageName = (code) => models.flatMap((m) => m.languages).find((l) => l.code === code)?.name || code;
  // Undo labels name the language when the dub has several.
  const inLanguage = (label) => (tracks().length > 1 ? `${label} (${languageName(track().language)})` : label);

  const header = el("header", { class: "main-head dub-head" });
  const tableHead = el("div", { class: "dub-table-head" });
  const table = el("div", { class: "dub-table", role: "listbox", "aria-label": "Sentences" });
  const rowsBox = el("div", { class: "dub-rows" });
  const rendered = new Map(); // clip id -> its row, for the rows drawn now
  let tableIds = []; // the table's clip ids, filtered, in order
  let playingId = null; // the sentence under the playhead while playing
  let scrollFrame = 0;
  table.addEventListener("scroll", () => {
    cancelAnimationFrame(scrollFrame);
    scrollFrame = requestAnimationFrame(() => renderRows());
  });
  const stage = el("div", { class: "dub-stage" });
  const inspector = el("div", { class: "dub-inspector" });
  const play = previewPlayer();
  const lanes = timeline({ duration: dub.source.duration || 1, onSeek: (t) => play.seek(t),
    onSelect: (laneId, clipId) => choose(laneId === "dub" ? clipId : clips().find((c) => c.source_clip === clipId)?.id),
    onMove: (clipId, start) => {
      const before = clips().find((c) => c.id === clipId)?.start;
      const at = q();
      act(inLanguage(`move sentence ${numberOf(clipId)}`), () => api("PATCH", path(`/clips/${clipId}${at}`), { start }),
        () => api("PATCH", path(`/clips/${clipId}${at}`), { start: before }), track().language);
    } });
  const bottom = el("div", { class: "dub-bottom" }, lanes.element);
  const layout = el("div", { class: "dub-layout" });
  const showSizes = () => {
    layout.style.setProperty("--dub-right", `${sizes.right}px`);
    layout.style.setProperty("--tl-lane", `${sizes.lane}px`);
  };
  // Dragging the column separator: the right column takes what the table gives.
  let startRight = 0;
  const columns = separator("Resize the sentences and the video", true, {
    begin: () => { startRight = sizes.right; },
    drag: (dx) => { sizes.right = clampSize(startRight - dx, MIN_RIGHT, layout.clientWidth - MIN_TABLE - SPLIT); },
    reset: () => { sizes.right = SIZES.right; } });
  // Dragging the timeline separator up makes the lanes and the waveform taller; their default height is the smallest.
  let startLane = 0;
  let startBottom = 0;
  const laneCount = () => bottom.querySelectorAll(".tl-lane").length || 2;
  const rows = separator("Resize the timeline", false, {
    begin: () => { startLane = sizes.lane; startBottom = bottom.offsetHeight; },
    drag: (dy) => {
      const smallest = startBottom - laneCount() * (startLane - SIZES.lane);
      const height = clampSize(startBottom - dy, smallest, layout.clientHeight - SPLIT - MIN_ABOVE_TIMELINE);
      sizes.lane = SIZES.lane + (height - smallest) / laneCount();
    },
    reset: () => { sizes.lane = SIZES.lane; } });
  showSizes();
  layout.append(el("section", { class: "dub-left" }, tableHead, table), columns,
    el("aside", { class: "dub-right" }, stage, inspector), rows, bottom);
  main.replaceChildren(header, layout, el("footer", { class: "dub-foot" }, message));

  // A separator between two panes: dragged, moved with the arrow keys, or double-clicked back to the default.
  // `drag` gets the distance from where the drag began; sizes are saved when it ends.
  function separator(label, vertical, { begin, drag, reset }) {
    const node = el("div", { class: `dub-split ${vertical ? "vertical" : "horizontal"}`, role: "separator", tabindex: "0",
      "aria-label": label, "aria-orientation": vertical ? "vertical" : "horizontal",
      title: `${label}: drag it, or double-click to reset` });
    const at = (e) => (vertical ? e.clientX : e.clientY);
    node.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      node.setPointerCapture(e.pointerId);
      node.classList.add("dragging");
      begin();
      const from = at(e);
      const move = (m) => { drag(at(m) - from); showSizes(); };
      const end = () => {
        node.classList.remove("dragging");
        node.removeEventListener("pointermove", move);
        node.removeEventListener("pointerup", end);
        node.removeEventListener("pointercancel", end);
        saveSizes();
      };
      node.addEventListener("pointermove", move);
      node.addEventListener("pointerup", end);
      node.addEventListener("pointercancel", end);
    });
    node.addEventListener("dblclick", () => { reset(); showSizes(); saveSizes(); });
    node.addEventListener("keydown", (e) => {
      const keys = vertical ? { ArrowLeft: -16, ArrowRight: 16 } : { ArrowUp: -16, ArrowDown: 16 };
      if (!(e.key in keys)) return;
      e.preventDefault();
      e.stopPropagation(); // not the sentence list's arrow keys
      begin();
      drag(keys[e.key]);
      showSizes();
      saveSizes();
    });
    return node;
  }

  // --- Changes and undo ------------------------------------------------------------------------

  function apply(data) {
    dub = data;
    if (data.notice) setMessage(message, data.notice, "warn");
    draw();
    play.changed();
  }

  async function change(request) {
    try {
      apply(await request);
    } catch (error) { fail(error); }
  }

  // Does a change and records how to undo it. `run` and `revert` return the dub view (one request, or the last of several).
  // `language`: the language the step belongs to (none for shared ones), so removing a language forgets its steps.
  // `takes`: the step picks takes, so deleting the language's takes forgets it.
  async function act(label, run, revert, language = null, takes = false) {
    try {
      apply(await run());
      history().push({ label, undo: revert, redo: run, language, takes });
      drawHeader();
    } catch (error) { fail(error); }
  }

  async function step(kind) {
    if (job) return setMessage(message, "Wait for the current job to finish, then undo.", "warn");
    try {
      const label = await history()[kind]();
      if (label) {
        apply(history().lastResult());
        setMessage(message, `${kind === "undo" ? "Undid" : "Redid"} ${label}.`);
      }
    } catch (error) { fail(error); }
    drawHeader();
  }


  // Ctrl+Enter: the typed translation is saved first, so the take speaks it.
  async function saveThenGenerate(clip, box) {
    if (box.value !== box.dataset.saved) {
      box.dataset.saved = box.value; // its blur must not save it a second time
      await editTranslation(clip, box.value);
    }
    generate([clip.id]);
  }

  function editTranslation(clip, text) {
    const before = clip.translation;
    if (text.trim() === before) return null;
    const at = q();
    return act(inLanguage(`translation of sentence ${numberOf(clip.id)}`),
      () => api("PATCH", path(`/clips/${clip.id}${at}`), { translation: text }),
      () => api("PATCH", path(`/clips/${clip.id}${at}`), { translation: before }), track().language);
  }

  function editOriginal(clip, text) {
    const source = sourceOf(clip);
    const before = source.text;
    if (text.trim() === before) return;
    act(`text of sentence ${numberOf(clip.id)}`, () => api("PATCH", path(`/source/${source.id}`), { text }),
      () => api("PATCH", path(`/source/${source.id}`), { text: before }));
  }

  // Model and settings belong to the language shown; name and the original's volume to the dub.
  function setOption(label, key, value) {
    const perLanguage = key === "model" || key === "settings";
    const at = perLanguage ? q() : "";
    const before = perLanguage ? track()[key] : dub[key];
    if (before === null || before === undefined) return change(api("PATCH", path(at), { [key]: value }));
    act(perLanguage ? inLanguage(label) : label, () => api("PATCH", path(at), { [key]: value }),
      () => api("PATCH", path(at), { [key]: before }), perLanguage ? track().language : null);
  }

  function pasteMany(translations) {
    const before = Object.fromEntries(Object.keys(translations).map((id) => [id, clips().find((c) => c.id === id).translation]));
    const at = q();
    act(inLanguage(`pasted ${plural(Object.keys(translations).length, "translation")}`),
      () => api("PATCH", path(`/translations${at}`), { translations }),
      () => api("PATCH", path(`/translations${at}`), { translations: before }), track().language);
  }

  // Shared by every language: the sentence's original plays at full volume instead of a dub.
  function toggleKeep(clip) {
    const source = sourceOf(clip);
    const keep = !source.keep_original;
    act(`${keep ? "keeping the original in" : "dubbing"} sentence ${numberOf(clip.id)}`,
      () => api("PATCH", path(`/source/${source.id}`), { keep_original: keep }),
      () => api("PATCH", path(`/source/${source.id}`), { keep_original: !keep }));
  }

  function deleteSentence(clip) {
    const index = clips().indexOf(clip);
    const source = sourceOf(clip);
    const number = index + 1;
    // The sentence is shared by every language: undo brings back its clip in each, and points back the sentences that
    // took their voice from it (they fall back to their own).
    const all = Object.fromEntries(tracks().map((t) => [t.language, t.clips.find((c) => c.source_clip === source.id)]));
    const voices = Object.fromEntries(tracks().map((t) => [t.language,
      t.clips.filter((c) => c.source_clip !== source.id && c.voice_from === source.id).map((c) => c.id)]));
    if (selected === clip.id) selected = clips()[index + 1]?.id || clips()[index - 1]?.id || null;
    act(`deleting sentence ${number}`, () => api("DELETE", path(`/source/${source.id}`)),
      () => api("POST", path("/source/restore"), { source, clips: all, index, voices }));
  }

  // --- Jobs ------------------------------------------------------------------------------------

  async function follow(started, kind, ids = [], language = track().language) {
    // The generated sentences' takes before (in the job's language), for undoing the generation.
    const generating = tracks().find((t) => t.language === language)?.clips || [];
    const wanted = new Set(ids);
    const before = Object.fromEntries(generating.filter((c) => wanted.has(c.id)).map((c) => [c.id, c.selected]));
    job = { id: started.id, kind, clips: new Set(ids), progress: started.progress || "" };
    // Also shown when the screen comes back to a transcription that is still running.
    if (kind === "transcribe") setMessage(message, LISTENING);
    draw();
    try {
      const result = await waitForJob(started.id, (update) => {
        if (job && update.progress !== job.progress) {
          job.progress = update.progress;
          header.querySelector(".job-progress")?.replaceChildren(update.progress || "Working\u2026");
        }
      });
      if (stopped) return; // the screen was left; the screen open now follows the job itself
      apply(result);
      if (kind === "transcribe" && !dub.notice) {
        setMessage(message, `Found ${plural(sources().length, "sentence")}. Use \u201cCopy for translation\u201d, then `
          + "\u201cPaste translations\u201d, or type them in the table.");
      }
      if (kind === "generate" || kind === "fit") recordSelection(before, language, kind);
    } catch (error) {
      if (stopped) return;
      if (error.cancelled) setMessage(message, "Cancelled.");
      else fail(error);
      apply(await api("GET", path()).catch(() => dub));
      if (kind === "generate" || kind === "fit") recordSelection(before, language, kind);
    } finally {
      if (!stopped) {
        job = null;
        draw();
        refreshList().catch(() => {});
        chooseOnlyModel(); // skipped while the job ran (an import opens the screen with Whisper already listening)
      }
    }
  }

  // A generation or a fit selects new takes; undo selects the previous ones again (the new takes stay in the list), in
  // one request however many sentences changed.
  function recordSelection(before, language, kind) {
    const changed = (tracks().find((t) => t.language === language)?.clips || [])
      .filter((c) => c.id in before && c.selected !== before[c.id]);
    if (!changed.length) return;
    const at = q(language);
    const select = (files) => api("POST", path(`/select${at}`), { selections: files });
    const previous = Object.fromEntries(changed.map((c) => [c.id, before[c.id]]));
    const next = Object.fromEntries(changed.map((c) => [c.id, c.selected]));
    const label = `${kind === "fit" ? "fitting" : "generating"} ${plural(changed.length, "sentence")}`;
    history().push({ label: tracks().length > 1 ? `${label} (${languageName(language)})` : label, undo: () => select(previous),
      redo: () => select(next), language, takes: true });
  }

  async function transcribe() {
    if (!whisper) return setMessage(message, "Install Whisper on the Models screen to find the sentences.", "warn");
    try {
      await follow(await api("POST", path("/transcribe"), {}), "transcribe");
    } catch (error) { fail(error); }
  }

  // Speeds the takes up (same pitch) to fit before the next sentence; past 1.25x the server says to shorten them.
  async function fitTakes(ids) {
    if (!ids.length) return;
    try {
      await follow(await api("POST", path(`/fit${q()}`), { clips: ids }), "fit", ids);
    } catch (error) { fail(error); }
  }

  async function generate(ids) {
    if (!ids.length) return;
    if (!model()) return needModel();
    try {
      await follow(await api("POST", path(`/generate${q()}`), { clips: ids }), "generate", ids);
    } catch (error) { fail(error); }
  }

  // Generate without a model: point at the Model select and say why.
  function needModel() {
    header.querySelector(".dub-model")?.focus();
    setMessage(message, installed.length ? `Choose the model that speaks ${languageName(track().language)} first.`
      : "Install a voice model on the Models screen first.", "warn");
  }

  // A language without a model gets the one installed model that speaks it (no undo step, like a first choice).
  function chooseOnlyModel() {
    const name = !track().model && !job && onlyModel(installed, track().language);
    if (name) setOption("choosing the model", "model", name);
  }

  // --- Drawing ---------------------------------------------------------------------------------

  // Redraws keep text typed but not saved yet, and the focus and caret in it.
  function draw() {
    const active = typing(document.activeElement) && main.contains(document.activeElement) ? document.activeElement : null;
    const caret = active && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
    const unsaved = [...main.querySelectorAll("[data-saved]")].filter((box) => box.value !== box.dataset.saved)
      .map((box) => [box.dataset.key, box.value]);
    if (selected && !clips().some((c) => c.id === selected)) selected = null;
    selected ||= clips()[0]?.id || null;
    drawHeader();
    drawTable();
    drawInspector();
    drawLanes();
    for (const [key, value] of unsaved) {
      const box = main.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (box) box.value = value;
    }
    const again = active?.dataset.key && main.querySelector(`[data-key="${CSS.escape(active.dataset.key)}"]`);
    if (again) {
      again.focus();
      if (caret) again.setSelectionRange(...caret);
    }
  }

  function drawHeader() {
    const name = el("input", { class: "title-input", value: dub.name, "aria-label": "Dub name", onchange: () => {
      if (!name.value.trim()) { name.value = dub.name; return; }
      setOption("renaming the dub", "name", name.value.trim());
      refreshList();
    } });
    const chosen = model();
    const modelSelect = el("select", { class: `select dub-model ${chosen ? "" : "needs-choice"}`, "aria-label": "Model",
      title: "The model that speaks the translations", onchange: () => setOption("changing the model", "model", modelSelect.value) },
    !chosen && el("option", { value: "" }, installed.length ? "Choose a voice model" : "No model installed"),
    installed.map((m) => el("option", { value: m.name }, m.title)));
    modelSelect.value = chosen?.name || "";
    const target = languageTabs();
    const settingsButton = el("button", { class: "btn", disabled: !chosen, title: "Generation settings",
      onclick: () => popover(settingsButton, el("div", { class: "menu settings-pop" }, settingsPanel(chosen))) }, "\u2699");
    const all = clips();
    const keptCount = all.filter(isKept).length;
    const translated = all.filter((c) => c.translation.trim() && !isKept(c)).length;
    const voiced = all.filter((c) => c.selected).length;
    const long = all.filter((c) => fit()[c.id]?.state === "long").length;
    const missing = all.filter((c) => !c.selected && c.translation.trim() && !isKept(c)).map((c) => c.id);
    const more = el("button", { class: "btn btn-ghost icon-btn", "aria-label": "More", title: "Transcribe again or delete" }, "\u22ef");
    more.onclick = () => popover(more, el("div", { class: "menu" },
      el("button", { class: "menu-item", disabled: Boolean(job) || !whisper, onclick: () => confirmTranscribe(more) }, "Transcribe again\u2026"),
      el("button", { class: "menu-item danger", disabled: Boolean(job) || !takeCount(),
        onclick: () => confirmClearTakes(more) }, `Delete all takes of ${languageName(track().language)}\u2026`),
      el("button", { class: "menu-item danger", onclick: () => confirmDelete(more) }, "Delete dub\u2026")), { align: "right" });
    const exportButton = el("button", { class: "btn", disabled: !dub.source.duration, title: "Mix the dub into one audio file",
      onclick: () => popover(exportButton, exportPanel(), { align: "right" }) }, "Export");
    const undoLabel = history().undoLabel();
    const redoLabel = history().redoLabel();
    header.replaceChildren(
      editableTitle(name),
      el("span", { class: "row small muted dub-langs" }, dub.source.language ? languageName(dub.source.language) : "Not transcribed",
        " \u2192 ", target),
      modelSelect, settingsButton,
      all.length ? el("span", { class: "small muted dub-progress", title: "Translated \u00b7 with a take \u00b7 too long" },
        `${translated}/${all.length - keptCount} translated \u00b7 ${voiced} voiced`
        + (keptCount ? ` \u00b7 ${keptCount} original` : ""), long ? el("span", { class: "warn" }, ` \u00b7 ${long} too long`) : "")
        : "",
      el("div", { class: "spacer" }),
      el("button", { class: "btn btn-ghost icon-btn", disabled: !undoLabel || Boolean(job), "aria-label": "Undo",
        title: undoLabel ? `Undo: ${undoLabel} (Ctrl+Z)` : "Nothing to undo", onclick: () => step("undo") }, "\u21b6"),
      el("button", { class: "btn btn-ghost icon-btn", disabled: !redoLabel || Boolean(job), "aria-label": "Redo",
        title: redoLabel ? `Redo: ${redoLabel} (Ctrl+Shift+Z)` : "Nothing to redo", onclick: () => step("redo") }, "\u21b7"),
      job ? el("span", { class: "row small muted" }, el("span", { class: "job-progress" }, job.progress || "Working\u2026"),
        el("button", { class: "btn btn-small", onclick: () => api("POST", `/api/jobs/${job.id}/cancel`).catch(fail) }, "Cancel"))
        : el("button", { class: "btn btn-primary", disabled: !missing.length,
          title: !chosen ? "Choose a voice model first" : missing.length
            ? `Generate the ${plural(missing.length, "translated sentence")} without a take`
            : "Every translated sentence has a take", onclick: () => generate(missing) },
        missing.length ? `Generate ${missing.length}` : "Generate missing"),
      exportButton, more);
  }

  // One tab per target language; + adds one (all models' languages), x on a tab removes it (confirmed, not undoable).
  function languageTabs() {
    // A search list of every model's languages the dub does not have yet; its button reads "+ Add language".
    const have = new Set(tracks().map((t) => t.language));
    const options = models.flatMap((m) => m.languages).filter((l, i, all) => all.findIndex((x) => x.code === l.code) === i)
      .filter((l) => !have.has(l.code)).sort((a, b) => a.name.localeCompare(b.name));
    const add = job ? el("span") : searchSelect({ label: "Add a language: dub this file into another language too",
      placeholder: "Search languages", small: true, value: "+ Add language",
      options: options.map((l) => ({ value: l.code, label: l.name })), onChange: async (code) => {
        try {
          const data = await api("POST", path("/languages"), { language: code });
          lang = code;
          openLanguage.set(dub.id, code);
          apply(data);
          setMessage(message, `Added ${languageName(code)}. Its sentences are empty: translate them, then generate.`);
          chooseOnlyModel();
        } catch (error) { fail(error); }
      } });
    return el("span", { class: "row dub-tabs", role: "tablist", "aria-label": "Target languages" }, tracks().map((t) => {
      const on = t.language === track().language;
      const remove = tracks().length > 1 && el("button", { class: "tab-x", "aria-label": `Remove ${languageName(t.language)}`,
        title: `Remove ${languageName(t.language)}`, onclick: (e) => { e.stopPropagation(); confirmRemove(e.target, t.language); } },
      "\u00d7");
      return el("span", { class: `dub-tab ${on ? "active" : ""}` },
        el("button", { class: "btn btn-ghost btn-small", role: "tab", "aria-selected": String(on), disabled: Boolean(job) && !on,
          onclick: () => { if (on) return; lang = t.language; openLanguage.set(dub.id, lang); filter = "all"; draw(); play.changed();
            chooseOnlyModel(); } },
        languageName(t.language)), remove);
    }), add);
  }

  function confirmRemove(anchor, code) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Remove ${languageName(code)}?`),
      el("div", { class: "muted small" }, "Its translations and takes are removed permanently. This cannot be undone."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        close();
        try {
          const data = await api("DELETE", path(`/languages/${code}`));
          if (code === track().language) { lang = null; openLanguage.delete(dub.id); }
          history().drop((step) => step.language === code); // its steps could only fail now
          apply(data);
        } catch (error) { fail(error); }
      } }, "Remove")), { align: "left" });
  }

  function settingsPanel(chosen) {
    const overrides = track().settings[chosen.name] || {};
    const defaults = Object.fromEntries(chosen.settings.map((s) => [s.key, s.default]));
    return sliders(chosen.settings, { ...defaults, ...overrides }, defaults,
      (spec, value, base) => (value === base ? "Default" : `Default: ${base}`),
      (key, value) => setOption(`${chosen.title} settings`, "settings",
        { ...track().settings, [chosen.name]: { ...overrides, [key]: value } }),
      `dub:${dub.id}`);
  }

  function drawTable() {
    const all = clips();
    const counts = Object.fromEntries(Object.keys(FILTERS).map((f) => [f, clipFilter(all, fit(), f).length]));
    const names = FILTERS;
    const chip = (key, label, on) => el("button", {
      class: `btn btn-small ${on ? "active" : "btn-ghost"}`, role: "tab", "aria-selected": String(on),
      disabled: !all.length, onclick: () => { filter = key; drawTable(); } }, `${label} ${counts[key]}`);
    const tooLong = filter.startsWith("long");
    tableHead.replaceChildren(
      el("div", { class: "row dub-filters", role: "tablist" }, ["all", "untranslated", "missing", "long", "kept"]
        .map((key) => chip(key, names[key], key === "long" ? tooLong : filter === key))),

      el("div", { class: "spacer" }),
      el("button", { class: "btn btn-small", disabled: !all.length, onclick: copyTranscript,
        title: "Copy every sentence, numbered, with an instruction for a translation tool" }, "Copy for translation"),
      pasteButton(),
      // Too long, split on a row of its own: what can still be sped up, what was, and what needs a shorter translation.
      tooLong && el("div", { class: "row dub-subrow" },
        el("div", { class: "row dub-filters", role: "tablist", "aria-label": "Too long" },
          ["long", "long-fit", "long-fitted", "long-shorter"].map((key) => chip(key, key === "long" ? "All" : names[key], filter === key))),
        el("div", { class: "spacer" }), fitButton(all), originalsButton(all)));
    if (!all.length) {
      table.replaceChildren(el("div", { class: "empty small" }, dub.source.language
        ? el("p", { class: "muted" }, "No sentences. Transcribe again, or import another file.")
        : job?.kind === "transcribe" ? el("p", { class: "muted" }, LISTENING)
        : whisper ? el("button", { class: "btn btn-primary", disabled: Boolean(job), onclick: transcribe }, "Find the sentences")
          : el("p", { class: "muted" }, "Install Whisper on the ", el("a", { href: "#/models" }, "Models screen"),
            " to find the sentences and their times.")));
      return;
    }
    const shown = new Set(clipFilter(all, fit(), filter));
    tableIds = all.filter((c) => shown.has(c.id)).map((c) => c.id); // in table order, within the filter
    if (!tableIds.length) {
      table.replaceChildren(el("p", { class: "muted small pad" }, `No sentences in \u201c${names[filter]}\u201d.`));
      return;
    }
    rowsBox.style.height = `${tableIds.length * ROW}px`;
    if (rowsBox.parentNode !== table) table.replaceChildren(rowsBox);
    const typed = focusedRow(); // read before the rows go: a row typed in, even scrolled away, is drawn again
    rendered.clear();
    rowsBox.replaceChildren();
    renderRows(typed);
  }

  const focusedRow = () => document.activeElement?.closest?.(".dub-line")?.dataset.clip;

  // In "Too long": fit every take that can be sped up enough; the ones needing more stay for a shorter translation.
  function fitButton(all) {
    const over = clipFilter(all, fit(), "long-fit");
    return el("button", { class: "btn btn-small", disabled: !over.length || Boolean(job),
      title: `Speed the takes up to fit, same pitch, up to ${MAX_SPEEDUP}\u00d7; longer ones need a shorter translation`,
      onclick: () => fitTakes(over) }, over.length ? `Fit ${over.length}` : "Fit");
  }

  // In "Too long": the sped-up takes back to the ones they were made from.
  function originalsButton(all) {
    const fitted = clipFilter(all, fit(), "long-fitted");
    return el("button", { class: "btn btn-small", disabled: !fitted.length || Boolean(job),
      title: "Use the takes as they were generated, before speeding them up", onclick: () => useOriginals(fitted) },
    fitted.length ? `Use originals ${fitted.length}` : "Use originals");
  }

  // Selects the takes sped-up ones were made from (undoable; the sped-up takes stay in the list).
  function useOriginals(ids) {
    const changed = ids.map((id) => clips()[numberOf(id) - 1]).filter(Boolean)
      .map((c) => [c.id, c.selected, takeOf(c)?.from]).filter(([, , from]) => from);
    if (!changed.length) return;
    const at = q();
    const select = (index) => api("POST", path(`/select${at}`), { selections: Object.fromEntries(changed.map((c) => [c[0], c[index]])) });
    act(inLanguage(changed.length === 1 ? `original take of sentence ${numberOf(changed[0][0])}`
      : `original takes of ${plural(changed.length, "sentence")}`), () => select(2), () => select(1), track().language, true);
  }

  // The rows in view, plus the one being typed in (scrolled away, it keeps its text and focus). Rows already drawn stay.
  function renderRows(typed = null) {
    const [first, end] = visibleRows(table.scrollTop, table.clientHeight || 600, ROW, tableIds.length, OVERSCAN);
    const wanted = new Set(tableIds.slice(first, end));
    const focused = typed || focusedRow();
    if (focused && (rendered.has(focused) || tableIds.includes(focused))) wanted.add(focused);
    for (const [id, row] of rendered) if (!wanted.has(id)) { row.remove(); rendered.delete(id); }
    const position = new Map(tableIds.slice(first, end).map((id, i) => [id, first + i]));
    for (const id of wanted) {
      if (rendered.has(id)) continue;
      const clip = clips()[numberOf(id) - 1];
      const row = rowFor(clip);
      row.style.top = `${(position.get(id) ?? tableIds.indexOf(id)) * ROW}px`;
      rendered.set(id, row);
      rowsBox.append(row);
    }
  }

  function rowFor(clip) {
    const number = numberOf(clip.id);
    const source = sourceOf(clip);
    const clipFit = fit()[clip.id] || { state: "missing" };
    const input = el("input", { class: "input dub-tr", value: clip.translation, "data-saved": clip.translation,
      disabled: isKept(clip),
      "data-key": `tr-${clip.id}`, placeholder: "Translation", "aria-label": `Translation of sentence ${number}`,
      onblur: () => input.value !== input.dataset.saved && editTranslation(clip, input.value),
      onkeydown: async (e) => {
        if (e.isComposing) return; // an input method is still composing the text
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
          e.preventDefault();
          await saveThenGenerate(clip, input);
        } else if (e.key === "Enter" || e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const next = tableIds[tableIds.indexOf(clip.id) + (e.key === "ArrowUp" ? -1 : 1)]; // within the filter
          input.blur();
          if (next) { choose(next); table.querySelector(`[data-key="tr-${next}"]`)?.focus(); }
        } else if (e.key === "Escape") { input.value = input.dataset.saved; input.blur(); }
      } });
    input.addEventListener("paste", (e) => {
      const text = e.clipboardData.getData("text");
      if (!/\n/.test(text.trim())) return;
      e.preventDefault();
      const ids = clips().map((c) => c.id);
      pasteMany(pasteTranslations(ids, numberOf(clip.id) - 1, text));
    });
    input.addEventListener("focus", () => choose(clip.id, false));
    const status = clipFit.state === "kept" ? el("span", { class: "dub-status faint", title: "The original plays here" }, "\u266a")
      : clipFit.state === "long" ? el("span", { class: "dub-status warn", title: cannotFit(clipFit)
        || `Runs into the next sentence; fits sped up ${speedText(clipFit.need)}` }, `+${clipFit.over.toFixed(1)} s`)
      : clipFit.speed > 1 ? el("span", { class: "dub-status warn", title: `Sped up ${speedText(clipFit.speed)} to fit` },
        speedText(clipFit.speed))
      : clipFit.state === "fits" ? el("span", { class: "dub-status ok", title: "Fits" }, "\u2713")
        : el("span", { class: "dub-status faint", title: "No take yet" }, "\u25cb");
    const generating = job?.kind === "generate" && job.clips.has(clip.id);
    const row = el("div", { class: `dub-line ${clip.id === selected ? "selected" : ""} ${generating ? "busy" : ""} ${isKept(clip) ? "kept" : ""} ${clip.id === playingId ? "playing" : ""}`,
      role: "option", "aria-selected": String(clip.id === selected), "data-clip": clip.id, onclick: (e) => {
        if (!typing(e.target)) choose(clip.id);
      } },
    el("span", { class: "num faint small" }, number),
    el("button", { class: "num small link-btn dub-at", title: "Play from here", onclick: () => { choose(clip.id); play.seek(clip.start, true); } },
      formatTime(source.start)),
    el("span", { class: "dub-orig", title: source.text }, source.text),
    input, generating ? el("span", { class: "dub-status faint" }, "\u2026") : status);
    return row;
  }

  function pasteButton() {
    const button = el("button", { class: "btn btn-small", disabled: !clips().length,
      title: "Paste a translation tool's reply: each numbered line goes to its sentence" }, "Paste translations");
    button.onclick = () => popover(button, pastePanel(), { align: "right" });
    return button;
  }

  function drawInspector() {
    const clip = clips().find((c) => c.id === selected);
    if (!clip) {
      inspector.replaceChildren(el("p", { class: "muted small" }, "Select a sentence to see it here."));
      return;
    }
    const number = numberOf(clip.id);
    const source = sourceOf(clip);
    const clipFit = fit()[clip.id] || { state: "missing" };
    const original = el("textarea", { class: "textarea", rows: 2, value: source.text, "data-saved": source.text,
      "data-key": `orig-${clip.id}`, "aria-label": `Original of sentence ${number}`,
      title: "What is said. It is also the transcript of the voice sample, so correct it if Whisper misheard.",
      onblur: () => original.value !== original.dataset.saved && editOriginal(clip, original.value) });
    const translation = el("textarea", { class: "textarea", rows: 3, value: clip.translation, "data-saved": clip.translation,
      "data-key": `insp-${clip.id}`, placeholder: "Translation", "aria-label": `Translation of sentence ${number} (details)`,
      onblur: () => translation.value !== translation.dataset.saved && editTranslation(clip, translation.value),
      onkeydown: (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); saveThenGenerate(clip, translation); }
      } });
    // A search list, not a <select>: a dub can have tens of thousands of sentences to take a voice from.
    const voice = searchSelect({ label: `Voice from, sentence ${number}: whose voice and mood it copies. A very short sentence `
      + "clones weakly: pick a longer one of the same speaker.", placeholder: "Search by number or words", small: true,
    value: clip.voice_from, options: sources().map((s, n) => ({ value: s.id, label: s.id === clip.source_clip ? "This sentence"
      : `${n + 1} \u00b7 ${s.text.slice(0, 32)}${s.text.length > 32 ? "\u2026" : ""}` })),
    onChange: (value) => {
      const before = clip.voice_from;
      const at = q();
      act(inLanguage(`voice of sentence ${number}`), () => api("PATCH", path(`/clips/${clip.id}${at}`), { voice_from: value }),
        () => api("PATCH", path(`/clips/${clip.id}${at}`), { voice_from: before }), track().language);
    } });
    const generating = job?.kind === "generate" && job.clips.has(clip.id);
    const takes = clip.takes.map((take, n) => el("div", { class: `row dub-take ${take.file === clip.selected ? "selected" : ""}` },
      el("button", { class: "btn btn-ghost btn-small", "aria-pressed": String(take.file === clip.selected),
        title: take.file === clip.selected ? "Used in the dub" : "Use this take", onclick: () => {
          if (take.file === clip.selected) return;
          const before = clip.selected;
          const at = q();
          act(inLanguage(`take of sentence ${number}`), () => api("POST", path(`/clips/${clip.id}/select${at}`), { file: take.file }),
            () => api("POST", path(`/clips/${clip.id}/select${at}`), { file: before }), track().language, true);
        } }, take.file === clip.selected ? "\u25cf" : "\u25cb"),
      player(fileUrl(take.file), { buckets: 30, showTime: false, label: `Play take ${n + 1}` }),
      el("span", { class: "faint small num" }, `${take.duration.toFixed(1)} s \u00b7 seed ${take.seed}`
        + (take.speed ? ` \u00b7 ${speedText(take.speed)}` : ""))));
    const remove = el("button", { class: "btn btn-ghost btn-small danger", title: "Delete this sentence (undo brings it back)",
      onclick: () => deleteSentence(clip) }, "Delete sentence");
    const kept = isKept(clip);
    const keep = el("label", { class: "row small dub-keep", title: "For music or singing: the original plays here at full "
      + "volume in every language, and nothing is translated or generated (K)" },
    el("input", { type: "checkbox", checked: kept, onchange: () => toggleKeep(clip) }), "Keep the original here (music, singing)");
    if (kept) {
      inspector.replaceChildren(
        el("div", { class: "row" }, el("strong", {}, `Sentence ${number}`),
          el("span", { class: "faint small num" }, `${formatTime(source.start)}\u2013${formatTime(source.end)}`),
          el("div", { class: "spacer" }), el("span", { class: "faint small" }, "\u266a Original")),
        el("label", { class: "field-label" }, "Original"), original, keep,
        el("p", { class: "faint small" }, "The original plays here at full volume, in every language."),
        el("div", { class: "row" }, el("div", { class: "spacer" }), remove));
      return;
    }
    inspector.replaceChildren(
      el("div", { class: "row" }, el("strong", {}, `Sentence ${number}`),
        el("span", { class: "faint small num" }, `${formatTime(source.start)}\u2013${formatTime(source.end)}`),
        el("div", { class: "spacer" }),
        clipFit.state === "long" ? el("span", { class: "row" }, el("span", { class: "warn small" }, `${clipFit.over.toFixed(1)} s too long`),
          cannotFit(clipFit) ? el("span", { class: "faint small" }, cannotFit(clipFit))
            : el("button", { class: "btn btn-small", disabled: Boolean(job), onclick: () => fitTakes([clip.id]),
              title: `Speed the take up ${speedText(clipFit.need)} to fit, same pitch` }, "Fit"))
          : clipFit.speed > 1 ? el("span", { class: "row" }, el("span", { class: "warn small" }, `Sped up ${speedText(clipFit.speed)} to fit`),
            el("button", { class: "btn btn-small", disabled: Boolean(job), onclick: () => useOriginals([clip.id]),
              title: "Use the take as it was generated, before speeding it up" }, "Use the original"))
          : clipFit.state === "fits" ? el("span", { class: "ok small" }, "Fits") : el("span", { class: "faint small" }, "No take yet")),
      el("label", { class: "field-label" }, "Original"), original, keep,
      el("label", { class: "field-label" }, "Translation"), translation,
      el("div", { class: "row" }, el("label", { class: "row small muted" }, "Voice", voice)),
      takes.length ? el("div", { class: "dub-takes" }, takes) : el("p", { class: "faint small" }, "No takes yet."),
      el("div", { class: "row" },
        generating ? el("span", { class: "small muted" }, "Generating\u2026")
          : el("button", { class: "btn btn-primary btn-small", disabled: Boolean(job) || !clip.translation.trim(),
            title: !clip.translation.trim() ? "Write the translation first" : !model() ? "Choose a voice model first" : "Ctrl+Enter",
            onclick: () => generate([clip.id]) }, clip.takes.length ? "Generate again" : "Generate"),
        el("div", { class: "spacer" }), remove));
  }

  function drawLanes() {
    lanes.setLanes([
      { id: "original", label: "Original", draggable: false,
        clips: sources().map((c) => ({ id: c.id, start: c.start, end: c.end, state: "source", title: c.text })) },
      { id: "dub", label: "Dub", draggable: true, clips: clips().map((c) => ({ id: c.id, start: c.start,
        end: c.start + lengthOf(c), state: fit()[c.id]?.state || "missing", title: c.translation || "No translation yet" })) },
    ]);
    if (selected) lanes.select(selected);
  }

  // Selects a sentence everywhere: table, inspector and timeline. `reveal` scrolls the table and timeline to it.
  function choose(clipId, reveal = true) {
    if (!clipId) return;
    const changed = clipId !== selected;
    selected = clipId;
    const at = tableIds.indexOf(clipId);
    if (reveal && at >= 0) { // scroll to its row and draw it now, so it can take the focus at once
      const top = at * ROW;
      if (top < table.scrollTop) table.scrollTop = top;
      else if (top + ROW > table.scrollTop + table.clientHeight) table.scrollTop = top + ROW - table.clientHeight;
      renderRows();
    }
    for (const row of rendered.values()) {
      const on = row.dataset.clip === clipId;
      row.classList.toggle("selected", on);
      row.setAttribute("aria-selected", String(on));
    }
    lanes.select(clipId, reveal);
    if (changed) drawInspector();
  }

  // --- Panels ----------------------------------------------------------------------------------

  async function copyTranscript() {
    // Each sentence's time: until the next one starts (as fit sees it), or the end of the file.
    const { sorted } = lookup();
    const until = new Map(sorted.map((c, i) => [c.id, sorted[i + 1]?.start ?? dub.source.duration ?? c.start + c.length]));
    const text = transcriptForTranslation(clips().map((c) => sourceOf(c)?.text || ""), languageName(track().language),
      clips().map((c) => Math.max(0, until.get(c.id) - c.start)));
    try {
      await navigator.clipboard.writeText(text);
    } catch { // no clipboard permission: copy through a hidden text box
      const box = el("textarea", { class: "sr-only" });
      box.value = text;
      document.body.append(box);
      box.select();
      document.execCommand("copy");
      box.remove();
    }
    setMessage(message, `Copied ${plural(clips().length, "sentence")}. Paste them into a translation tool, then use `
      + "\u201cPaste translations\u201d with its reply.");
  }

  function pastePanel() {
    const all = clips();
    const box = el("textarea", { class: "textarea paste-box", rows: 10, "aria-label": "Translated sentences",
      placeholder: "1. Hello, today we're trying something new.\n2. Yes.\n3. \u2026" });
    const summary = el("div", { class: "small muted" }, `Paste the reply for ${plural(all.length, "sentence")}.`);
    const apply_ = el("button", { class: "btn btn-primary", disabled: true }, "Apply");
    let parsed = null;
    box.addEventListener("input", () => {
      parsed = box.value.trim() ? parseTranslations(box.value, all.length) : null;
      const found = parsed ? all.length - parsed.missing.length : 0;
      apply_.disabled = !found;
      summary.className = parsed?.missing.length ? "small warn" : "small muted";
      summary.textContent = !parsed ? `Paste the reply for ${plural(all.length, "sentence")}.`
        : `Translations for ${found} of ${plural(all.length, "sentence")}`
          + (parsed.missing.length ? `; missing: ${parsed.missing.slice(0, 12).join(", ")}`
            + `${parsed.missing.length > 12 ? "\u2026" : ""}. Those keep what they have.` : ".");
    });
    apply_.onclick = () => {
      close();
      pasteMany(Object.fromEntries(all.flatMap((clip, i) => (parsed.texts[i] === null ? [] : [[clip.id, parsed.texts[i]]]))));
    };
    setTimeout(() => box.focus(), 0);
    return el("div", { class: "menu paste-menu" }, el("strong", {}, "Paste translations"), box, summary,
      el("div", { class: "row" }, apply_, el("button", { class: "btn btn-ghost", onclick: close }, "Cancel")));
  }

  function exportPanel() {
    return el("div", { class: "menu" }, formats.map((f) => el("button", { class: "menu-item", onclick: async () => {
      close();
      setMessage(message, "Exporting\u2026");
      try {
        const { path: file } = await api("POST", path(`/export${q()}`), { format: f.id });
        message.replaceChildren(`Exported ${file.split("/").pop()}. `, revealButton(file, { text: true }));
        message.className = "message info";
      } catch (error) { fail(error); }
    } }, el("strong", {}, f.label), el("span", { class: "faint small" }, f.note))));
  }

  function confirmTranscribe(anchor) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, "Transcribe again?"),
      el("div", { class: "muted small" }, "This replaces every sentence, translation and take, and cannot be undone."),
      el("button", { class: "btn btn-danger", onclick: () => { close(); histories.set(dub.id, createHistory(100)); transcribe(); } },
        "Transcribe again")), { align: "right" });
  }

  const takeCount = () => clips().reduce((n, c) => n + c.takes.length, 0);

  // Every take of the language shown, files included; the sentences and translations stay. Not undoable.
  function confirmClearTakes(anchor) {
    const code = track().language;
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete ${plural(takeCount(), "take")} of ${languageName(code)}?`),
      el("div", { class: "muted small" }, "The sentences and translations stay; the take files are removed permanently. "
        + "This cannot be undone."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        close();
        try {
          const result = await api("POST", path(`/takes/clear${q(code)}`), {});
          history().drop((step) => step.language === code && step.takes); // their takes are gone
          apply(result);
          setMessage(message, `Deleted ${plural(result.removed, "take")} of ${languageName(code)}.`);
        } catch (error) { fail(error); }
      } }, `Delete ${plural(takeCount(), "take")}`)), { align: "right" });
  }

  function confirmDelete(anchor) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete \u201c${dub.name}\u201d?`),
      el("div", { class: "muted small" }, "Its copy of the file, the takes and the exports are removed permanently."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        close();
        try {
          await api("DELETE", path());
          histories.delete(dub.id);
          play.stop();
          location.hash = "#/dub";
          await refreshList();
          window.dispatchEvent(new HashChangeEvent("hashchange"));
        } catch (error) { fail(error); }
      } }, "Delete")), { align: "right" });
  }

  // --- Preview ---------------------------------------------------------------------------------

  // The video (muted) or a plain clock, with the original underneath at its volume and the selected takes at their
  // starts through Web Audio (the audio clock leads; the video follows). Changes restart from the current time.
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

    const context = new AudioContext(); // suspended until Play; decodes the original for the waveform now
    const buffers = new Map(); // url -> Promise<AudioBuffer>
    const original = fileUrl("audio.wav");
    let gain = null;
    let sources = [];
    let playing = false;
    let stopped = false;
    let origin = 0;
    let contextStart = 0;
    let time = 0;
    let frame = 0;
    let current = null; // the sentence under the playhead
    const load = (url) => {
      if (!buffers.has(url)) buffers.set(url, fetch(url).then((r) => r.arrayBuffer()).then((b) => context.decodeAudioData(b)));
      return buffers.get(url);
    };
    const now = () => (playing ? origin + context.currentTime - contextStart : time);

    if (dub.source.duration) {
      load(original).then((buffer) => {
        const data = buffer.getChannelData(0);
        const step = Math.max(1, Math.floor(buffer.sampleRate / WAVE_PER_SECOND));
        const values = new Float32Array(Math.ceil(data.length / step));
        let top = 0;
        for (let i = 0; i < values.length; i++) {
          let peak = 0;
          for (let j = i * step, end = Math.min(data.length, j + step); j < end; j++) peak = Math.max(peak, Math.abs(data[j]));
          values[i] = peak;
          top = Math.max(top, peak);
        }
        if (top) for (let i = 0; i < values.length; i++) values[i] /= top;
        if (!stopped) lanes.setWave(values, buffer.sampleRate / step);
      }).catch(() => {});
    }

    async function start(at) {
      const items = clips().filter((c) => takeOf(c) && !isKept(c)).map((c) => ({ id: c.id, start: c.start, duration: takeOf(c).duration,
        url: fileUrl(c.selected) }));
      const [base, ...takes] = await Promise.all([load(original), ...items.map((c) => load(c.url))]);
      if (stopped) return;
      await context.resume();
      stopSources();
      gain = context.createGain();
      // The original at its volume, up to full volume over kept stretches.
      const points = volumeRamps(keptRanges(), Number(volume.value), 0.05);
      const valueAt = (t) => {
        let value = points[0][1];
        for (let i = 0; i < points.length; i++) {
          const [time, level] = points[i];
          if (time <= t) value = level;
          else {
            const [pt, pv] = points[i - 1];
            value = pv + ((level - pv) * (t - pt)) / Math.max(time - pt, 1e-6);
            break;
          }
        }
        return value;
      };
      gain.connect(context.destination);
      contextStart = context.currentTime + 0.05;
      origin = at;
      gain.gain.setValueAtTime(valueAt(at), contextStart);
      for (const [time, level] of points) if (time > at) gain.gain.linearRampToValueAtTime(level, contextStart + time - at);
      const node = context.createBufferSource();
      node.buffer = base;
      node.connect(gain);
      node.start(contextStart, at);
      sources = [node];
      for (const item of clipsToPlay(items, at)) {
        const source = context.createBufferSource();
        source.buffer = takes[items.findIndex((c) => c.id === item.id)];
        source.connect(context.destination);
        source.start(contextStart + item.delay, item.offset);
        sources.push(source);
      }
      playing = true;
      if (video) { video.currentTime = at; video.play().catch(() => {}); }
      button.replaceChildren(icon(ICONS.pause));
      cancelAnimationFrame(frame);
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
      lanes.setTime(t, playing);
      if (video && Math.abs(video.currentTime - t) > 0.25) video.currentTime = t;
      // The sentence being played is shown, unless the user is typing.
      const under = clipAt(lookup().sorted, t, lookup().longest);
      if (playing && under && under !== current) {
        current = under;
        playingId = under;
        for (const row of rendered.values()) row.classList.toggle("playing", row.dataset.clip === under);
        if (!typing(document.activeElement)) choose(under);
      }
      if (playing && t >= (dub.source.duration || 0)) { pause(); time = 0; return; }
      if (playing) frame = requestAnimationFrame(tick);
    }

    button.onclick = () => (playing ? pause() : start(time).catch(fail));
    volume.oninput = () => {
      volumeLabel.textContent = `${Math.round(volume.value * 100)} %`;
      if (gain && !keptRanges().length) gain.gain.value = Number(volume.value); // with kept stretches: applied on release
    };
    volume.onchange = () => setOption("changing the original's volume", "original_volume", Number(volume.value));

    return {
      toggle: () => button.click(),
      seek(t, andPlay = false) {
        time = t;
        if (playing || andPlay) start(t).catch(fail);
        else { clock.textContent = formatTime(t); lanes.setTime(t); if (video) video.currentTime = t; }
      },
      changed() {
        // Take names repeat after transcribing again (takes/d1-1.wav): decode takes afresh, keep the original.
        for (const url of [...buffers.keys()]) if (url !== original) buffers.delete(url);
        volume.value = dub.original_volume;
        volumeLabel.textContent = `${Math.round(dub.original_volume * 100)} %`;
        if (playing) start(now()).catch(fail);
      },
      stop() { stopped = true; pause(); context.close(); },
    };
  }

  // --- Keys ------------------------------------------------------------------------------------

  const onKey = (e) => {
    if (!main.isConnected) return document.removeEventListener("keydown", onKey);
    if (document.querySelector(".popover")) return;
    const inText = typing(e.target);
    const onControl = Boolean(e.target?.closest?.("button, a")); // Enter and Space press it, as everywhere else
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !inText && e.key.toLowerCase() === "z") { e.preventDefault(); step(e.shiftKey ? "redo" : "undo"); return; }
    if (mod && !inText && e.key.toLowerCase() === "y") { e.preventDefault(); step("redo"); return; }
    if (inText || (onControl && (e.code === "Space" || e.key === "Enter"))) return;
    const visible = clipFilter(clips(), fit(), filter);
    if (e.code === "Space") { e.preventDefault(); play.toggle(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const index = visible.indexOf(selected);
      choose(visible[Math.max(0, Math.min(visible.length - 1, index + (e.key === "ArrowUp" ? -1 : 1)))] || visible[0]);
    } else if (e.key === "Enter" && mod) { e.preventDefault(); if (selected) generate([selected]); }
    else if (e.key === "Enter") { e.preventDefault(); choose(selected); table.querySelector(`[data-key="tr-${selected}"]`)?.focus(); }
    else if (e.key.toLowerCase() === "k" && !mod && selected) {
      e.preventDefault();
      const clip = clips().find((c) => c.id === selected);
      if (clip) toggleKeep(clip);
    }
  };
  document.addEventListener("keydown", onKey);

  draw();
  if (dub.notice) setMessage(message, dub.notice, "warn");
  // A job started before the screen was left keeps running on the server: follow it again.
  api("GET", path("/jobs")).then(([running]) => {
    if (!main.isConnected || job) return;
    if (!running) return chooseOnlyModel();
    if (running.language && tracks().some((t) => t.language === running.language)) {
      lang = running.language; // show the language being generated
      openLanguage.set(dub.id, lang);
    }
    follow(running, running.kind, running.clips, running.language || track().language);
  }).catch(() => {});
  return { stop: () => { stopped = true; play.stop(); document.removeEventListener("keydown", onKey); }, transcribe };
}
