// Studio screen: sessions, cast, script lines with takes, generation, export.
import { api, editableTitle, el, icon, ICONS, lastOpened, rememberMicrophone, rememberOpened, revealButton, setMessage,
  waitForJob } from "./app.js";
import { decode, encodeWav, microphones, record } from "./audio.js";
import { avatar, characterColors, samplePanel } from "./characters.js";
import { soundEditor, soundText } from "./editor.js";
import { commonLanguages, findPlayable, formatTime, moveLine, parsePause, pickSelected, settingsChanges, splitSentences,
  takeNumber } from "./script.js";
import { contextMenu, dot, modelColor, modelPicker, modelTabs, popover, searchSelect, sliders } from "./settings.js";
import { pauseAll, player, rangeEditor, stopAudio } from "./waveform.js";

const ICON_MORE = ["M5 12h.01M12 12h.01M19 12h.01"];
const ICON_SCISSORS = ["M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z", "M20 4L8.1 15.9",
  "M14.5 14.5L20 20", "M8.1 8.1L12 12"];
const ICON_EXPORT = ["M12 4v11", "M7.5 10.5L12 15l4.5-4.5", "M5 19h14"];
const ICON_PREV = ["M18 6l-8 6 8 6z", "M6 6v12"];
const ICON_NEXT = ["M6 6l8 6-8 6z", "M18 6v12"];
const ICON_SLIDERS = ["M4 7h10M18 7h2M4 17h4M12 17h8M14 5v4M8 15v4"];

// Names for the sound tags in the "Add sound" menu (the server sends the tags a model performs).
const TAG_LABELS = {
  laughter: "Laughter", sigh: "Sigh", "confirmation-en": "\u201cYes\u201d (agreeing)", "question-en": "Question (English)",
  "question-ah": "Question \u201cah?\u201d", "question-oh": "Question \u201coh?\u201d", "question-ei": "Question \u201cei?\u201d",
  "question-yi": "Question \u201cyi?\u201d", "surprise-ah": "Surprise \u201cah!\u201d", "surprise-oh": "Surprise \u201coh!\u201d",
  "surprise-wa": "Surprise \u201cwa!\u201d", "surprise-yo": "Surprise \u201cyo!\u201d", "dissatisfaction-hnn": "Dissatisfied \u201chnn\u201d",
  cough: "Cough", crying: "Crying", screaming: "Scream", burping: "Burp", humming: "Humming", sniff: "Sniff", sneeze: "Sneeze",
  elation: "Elation", amusement: "Amusement", enthusiasm: "Enthusiasm", determination: "Determination", pride: "Pride",
  contentment: "Contentment", affection: "Affection", relief: "Relief", contemplation: "Contemplation",
  confusion: "Confusion", surprise: "Surprise", awe: "Awe", longing: "Longing", arousal: "Excited (arousal)",
  anger: "Anger", fear: "Fear", disgust: "Disgust", bitterness: "Bitterness", sadness: "Sadness", shame: "Shame",
  helplessness: "Helplessness", singing: "Singing", shouting: "Shouting", whispering: "Whispering",
  "speed-very-slow": "Very slow", "speed-slow": "Slow", "speed-fast": "Fast", "speed-very-fast": "Very fast",
  "pitch-low": "Lower pitch", "pitch-high": "Higher pitch", pause: "Pause", "long-pause": "Long pause",
  "expressive-high": "More expressive", "expressive-low": "Less expressive",
};
// Tags by kind, for the Add tag menu, the "[" suggestions and the hint; every other tag is a sound.
const TAG_GROUP_ORDER = ["Sounds", "Emotions", "Styles", "Delivery"];
const TAG_GROUPS = Object.fromEntries([
  ...["elation", "amusement", "enthusiasm", "determination", "pride", "contentment", "affection", "relief", "contemplation",
    "confusion", "surprise", "awe", "longing", "arousal", "anger", "fear", "disgust", "bitterness", "sadness", "shame",
    "helplessness"].map((t) => [t, "Emotions"]),
  ...["singing", "shouting", "whispering"].map((t) => [t, "Styles"]),
  ...["speed-very-slow", "speed-slow", "speed-fast", "speed-very-fast", "pitch-low", "pitch-high", "pause", "long-pause",
    "expressive-high", "expressive-low"].map((t) => [t, "Delivery"]),
]);
const tagGroup = (tag) => TAG_GROUPS[tag] || "Sounds";

// Lines longer than this get a note and a "Split" action: models work best with sentence-sized lines.
const LONG_LINE = 300;
const TIP_MODELS = "Models to generate with: each one makes its own take, so you can compare them.";
const TIP_SEED = "The same seed, text, sample and settings give the same audio. Leave empty for a new random seed each time.";
const SPLIT_SIZE = 250;
const ICON_OPEN = ["M6 9l6 6 6-6"]; // chevron down: open the line
const ICON_CLOSE = ["M6 15l6-6 6 6"]; // chevron up: close it

const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
const when = (created) => created.slice(0, 16).replace("T", " ");

export async function renderStudio(root) {
  const list = el("div", { class: "list" });
  const search = el("input", { class: "input", placeholder: "Search", "aria-label": "Search sessions", oninput: () => drawList() });
  const main = el("div", { class: "main" });
  const message = el("div", { class: "message", role: "status" });
  const exportInfo = el("div", { class: "row export-info" });
  root.append(
    el("aside", { class: "sidebar" },
      el("div", { class: "sidebar-head" }, el("h2", {}, "Sessions"),
        el("button", { class: "btn icon-btn", title: "New session", "aria-label": "New session", onclick: newSession }, icon(ICONS.plus))),
      el("div", { class: "search" }, search),
      list),
    main);

  let sessions = [];
  let models = [];
  let library = [];
  let session = null;
  let openLine = null;
  let performing = null; // { line, recorder } while "Perform this line" records
  let justOpened = null; // the open animation plays only when a line (or card) is opened, not on every redraw
  let justDone = null; // { line, file } of the newest take, briefly highlighted
  let exportFormats = []; // what this computer can export (from the server)
  let exportFormat = (() => { try { return localStorage.getItem("vokalit.exportFormat") || "wav"; } catch { return "wav"; } })();
  const picked = new Set(); // lines ticked for bulk actions
  let lastPicked = null; // anchor for Shift+click ranges
  let justClosed = null; // the row that replaces closed details fades in
  let editing = null; // session-only character whose card is shown
  let editingOpen = true; // that card expanded (samples visible) or collapsed to its header
  let seed = "";
  let batch = null;
  let pasting = false;
  let dragging = null;
  const generating = new Map(); // line id -> start time, for the spinner and elapsed seconds
  const lineJobs = new Map(); // line id -> id of the generate job working on it, for Cancel
  const pendingText = {}; // line id -> saves typed text not yet sent (the Generate button waits for it)
  // Elapsed time next to every spinner; one ticker for the whole screen.
  const ticker = setInterval(() => {
    if (!main.isConnected) {
      stopAll(); clearInterval(ticker);
      performing?.recorder.stop().catch(() => {}); // leaving the screen ends the recording; the microphone is released
      performing = null; document.removeEventListener("keydown", spaceToggle);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("keydown", selectionKeys);
      document.removeEventListener("vokalit-player-play", onPlayerPlay); return; }
    paintClock();
    for (const node of main.querySelectorAll(".elapsed[data-start]")) {
      node.textContent = `${Math.floor((Date.now() - Number(node.dataset.start)) / 1000)} s`;
    }
  }, 250);
  const busyLabel = (lineId, text) => el("span", { class: "busy" }, el("span", { class: "spinner", "aria-hidden": "true" }), text,
    el("span", { class: "elapsed num", "data-start": generating.get(lineId) }, "0 s"));
  const lineModels = {}; // line id -> models chosen in its details
  const lineSeeds = {};

  const installed = () => models.filter((m) => m.installed);
  // Short names ("Chatterbox") keep the header and take labels compact; menus show the full title.
  const titles = () => Object.fromEntries(models.flatMap((m) => [[m.name, m.title.split(" ")[0]], [`${m.name}-vc`, "Converted"]]));
  const modelInfo = (name) => models.find((m) => m.name === name);
  // Every sound tag some model performs: shown as chips wherever a line's text is shown.
  const soundTags = () => [...new Set(models.flatMap((m) => m.tags || []))];
  // Tags to offer (installed models), grouped, each with the models that perform it: [{ tag, label, group, note }].
  const soundChoices = () => [...new Set(installed().flatMap((m) => m.tags || []))].map((tag) => ({
    tag, label: TAG_LABELS[tag] || tag, group: tagGroup(tag),
    note: installed().filter((m) => m.tags?.includes(tag)).map((m) => m.title.split(" ")[0]).join(", ") }))
    .sort((a, b) => TAG_GROUP_ORDER.indexOf(a.group) - TAG_GROUP_ORDER.indexOf(b.group));
  const defaults = (name) => Object.fromEntries((modelInfo(name)?.settings || []).map((s) => [s.key, s.default]));
  const sessionValues = (name) => ({ ...defaults(name), ...(session.settings[name] || {}) });
  const languageName = (code) =>
    models.flatMap((m) => m.languages).find((l) => l.code === code)?.name || code;
  const lineLanguage = (line) => line.language || session.language;
  const castEntry = (id) => session.cast.find((c) => c.character === id);
  const fail = (error) => setMessage(message, error.message, "error");
  const sid = () => session.id;
  const selectedId = () => pickSelected(sessions.map((s) => s.id), (location.hash.match(/^#\/studio\/([0-9-]+)/) || [])[1],
    lastOpened("studio"));

  function sampleOf(line) {
    const entry = castEntry(line.character);
    if (!entry || !entry.samples.length) return null;
    return entry.samples.find((s) => s.id === line.sample) || entry.samples.find((s) => s.id === entry.default_sample);
  }

  // Language choices are the languages every chosen model supports. `inherit` adds a "Session (...)" option.
  function languageSelect(names, value, onChange, inherit = null, small = false) {
    const languages = commonLanguages(models, names);
    const options = [
      ...(inherit ? [{ value: "", label: `Session (${languageName(inherit)})` }] : []),
      ...languages.map((l) => ({ value: l.code, label: l.name })),
      ...(value && !languages.some((l) => l.code === value) ? [{ value, label: `${languageName(value)} (not supported)` }] : []),
    ];
    return searchSelect({ options, value: value || "", onChange: (code) => onChange(code || null), label: "Language",
      placeholder: "Search languages", small });
  }

  // --- Loading -------------------------------------------------------------------------------

  async function load() {
    [sessions, models, library, exportFormats] = await Promise.all([api("GET", "/api/sessions"), api("GET", "/api/models"),
      api("GET", "/api/characters"), exportFormats.length ? exportFormats : api("GET", "/api/export-formats").catch(() => [])]);
    drawList();
    const id = selectedId();
    if (!id) {
      session = null;
      main.replaceChildren(el("div", { class: "empty" }, el("h1", {}, "No sessions yet"),
        el("p", {}, "A session holds a script, its cast and every take you generate."),
        el("button", { class: "btn btn-primary", onclick: newSession }, "New session")));
      return;
    }
    if (session?.id !== id) { stopAll(); picked.clear(); lastPicked = null; openLine = null; editing = null; pasting = false; setMessage(message, ""); exportInfo.replaceChildren(); }
    const changed = session?.id !== id;
    try {
      session = await api("GET", `/api/sessions/${id}`);
      rememberOpened("studio", id);
      if (changed) {
        performing?.recorder.stop().catch(() => {});
        performing = null;
        generating.clear(); batch = null; exporting = false; followed.clear(); // jobs of the previous session keep running
        loadExports();
        resumeJobs();
      }
    } catch {
      main.replaceChildren(el("div", { class: "empty" }, el("p", {}, "This session no longer exists.")));
      return;
    }
    draw();
  }

  // Reloads the session; redraws only if something changed (focus checks run this often).
  async function refresh() {
    const next = await api("GET", `/api/sessions/${sid()}`);
    if (JSON.stringify(next) === JSON.stringify(session)) return;
    session = next;
    draw();
  }

  // The selected take's file. Takes deleted in File Explorer are dropped by the server when the session loads.
  const playableFile = (line) => line.selected;

  // Coming back to the window (e.g. after deleting files in File Explorer) reloads the session, which drops
  // takes and samples whose files are gone.
  function onFocus() {
    if (!main.isConnected || !session || Object.keys(pendingText).length || generating.size || batch || performing
        || document.querySelector(".popover, .trim-box, .review-box") || document.activeElement?.matches("input, textarea, [contenteditable]")) return;
    refresh().catch(() => {});
    loadExports();
  }
  window.addEventListener("focus", onFocus);

  // Applies a session returned by the API and redraws.
  const apply = (data) => {
    session = data.session || data;
    draw();
    if (data.notice) setMessage(message, data.notice, "warn");
    return data;
  };

  function drawList() {
    const term = search.value.trim().toLowerCase();
    const current = selectedId();
    list.replaceChildren(...sessions.filter((s) => s.name.toLowerCase().includes(term)).map((s) => {
      const item = el("a", { class: "list-item", href: `#/studio/${s.id}`, "aria-current": s.id === current ? "true" : "false",
        title: "Right-click to rename or delete" },
      el("div", { class: "name" }, s.name),
      el("div", { class: "sub" }, `${plural(s.lines, "line")} \u00b7 ${when(s.created)}`));
      const more = el("button", { class: "btn btn-ghost icon-btn list-more", "aria-label": `Actions for ${s.name}`, title: "Rename or delete" },
        icon(ICON_MORE));
      const holder = el("div", { class: "list-row" }, item, more);
      const menu = (e) => contextMenu(e, sessionMenu(s, holder));
      item.addEventListener("contextmenu", menu);
      more.addEventListener("click", (e) => {
        const box = more.getBoundingClientRect();
        menu({ preventDefault() {}, clientX: box.left, clientY: box.bottom + 4 });
        e.stopPropagation();
      });
      return holder;
    }));
  }

  function closeMenus() { document.querySelector(".popover")?.dispatchEvent(new Event("close")); }

  // Rename or delete a session from the list (right-click or the ... button).
  function sessionMenu(entry, holder) {
    const menu = el("div", { class: "menu" });
    const actions = () => menu.replaceChildren(
      el("button", { class: "menu-item", onclick: () => { closeMenus(); renameInList(entry, holder); } }, "Rename"),
      el("div", { class: "menu-sep" }),
      el("button", { class: "menu-item danger", onclick: () => menu.replaceChildren(...deleteSessionConfirm(entry, actions)) },
        "Delete session\u2026"));
    actions();
    return menu;
  }

  function deleteSessionConfirm(entry, back) {
    return [
      el("div", { class: "confirm-menu" },
        el("strong", {}, `Delete \u201c${entry.name}\u201d?`),
        el("div", { class: "muted small" }, `${entry.lines ? `Its ${plural(entry.lines, "line")}, takes` : "Its takes"}, recordings, `
          + "exports and session-only characters are removed permanently. This cannot be undone."),
        el("div", { class: "row" },
          el("button", { class: "btn btn-danger", onclick: () => { closeMenus(); deleteSession(entry.id); } }, "Delete session"),
          back && el("button", { class: "btn btn-ghost", onclick: back }, "Cancel")))];
  }

  async function deleteSession(id) {
    try {
      await api("DELETE", `/api/sessions/${id}`);
      if (session?.id === id) { session = null; location.hash = "#/studio"; }
      await load();
    } catch (error) { fail(error); }
  }

  function renameInList(entry, holder) {
    const input = el("input", { class: "input list-rename", value: entry.name, "aria-label": "Session name" });
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      const value = input.value.trim();
      if (save && value && value !== entry.name) {
        try {
          await api("PATCH", `/api/sessions/${entry.id}`, { name: value });
          entry.name = value;
          if (session?.id === entry.id) { session.name = value; draw(); }
        } catch (error) { fail(error); }
      }
      drawList();
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") { e.stopPropagation(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
    holder.replaceChildren(input);
    input.select();
  }

  async function newSession() {
    const created = await api("POST", "/api/sessions", {});
    location.hash = `#/studio/${created.id}`;
  }

  // --- Drawing -------------------------------------------------------------------------------

  function draw() {
    const listed = sessions.find((s) => s.id === session.id);
    if (listed && listed.lines !== session.lines.length) { listed.lines = session.lines.length; drawList(); }
    const scroll = main.querySelector(".main-body")?.scrollTop || 0;
    const card = editing && castEntry(editing)?.name ? sessionCharacterEditor(castEntry(editing)) : null;
    const divider = card && el("div", { class: "script-divider", role: "separator" }, `Script \u00b7 ${plural(session.lines.length, "line")}`);
    main.replaceChildren(header(), cast(), el("div", { class: "main-body" }, card, divider, script()), footer());
    main.querySelector(".main-body").scrollTop = scroll;
    paintTransport();
    justOpened = null;
    justDone = null;
  }

  function header() {
    const name = el("input", { class: "title-input", value: session.name, "aria-label": "Session name", onchange: async () => {
      const value = name.value.trim();
      if (!value) { name.value = session.name; return; }
      try {
        apply(await api("PATCH", `/api/sessions/${sid()}`, { name: value }));
        sessions = await api("GET", "/api/sessions");
        drawList();
      } catch (error) { fail(error); }
    } });
    const language = el("div", { class: "pop-holder" });
    language.title = "The language lines are read in, unless a line chooses its own. Only languages every selected model supports are listed.";
    const paintLanguage = () => language.replaceChildren(languageSelect(session.models, session.language, (code) =>
      api("PATCH", `/api/sessions/${sid()}`, { language: code }).then(apply, fail)));
    const picker = modelPicker(installed(), session.models, (names) =>
      api("PATCH", `/api/sessions/${sid()}`, { models: names }).then((data) => { session = data; paintLanguage(); }, fail));
    paintLanguage();
    const settingsButton = el("button", { class: "btn", "aria-haspopup": "dialog",
      title: "Generation settings for this session, per model. Lines can override them." }, icon(ICON_SLIDERS), "Settings");
    settingsButton.onclick = () => popover(settingsButton, sessionSettings(), { align: "right" });
    const seedInput = el("input", { class: "input seed", placeholder: "Random", value: seed, inputmode: "numeric",
      "aria-label": "Seed", title: TIP_SEED, oninput: () => { seed = seedInput.value.replace(/\D/g, ""); seedInput.value = seed; } });
    const more = el("button", { class: "btn btn-ghost icon-btn", "aria-label": "More session actions", title: "More" }, icon(ICON_MORE));
    more.onclick = () => popover(more, el("div", { class: "menu" },
      el("button", { class: "menu-item", disabled: !session.lines.some((l) => !l.text.trim()),
        title: "Remove every line that has no text", onclick: () => {
          const empty = session.lines.filter((l) => !l.text.trim()).map((l) => l.id);
          confirmBulkDelete(more, empty, "empty");
        } }, "Delete empty lines\u2026"),
      el("div", { class: "menu-sep" }),
      el("button", { class: "menu-item danger", onclick: () => confirmDeleteSession(more) }, "Delete session")), { align: "right" });
    return el("header", { class: "main-head" },
      editableTitle(name), el("div", { class: "spacer" }),
      el("div", { class: "muted generate-label", title: TIP_MODELS }, "Generate with"), picker.element, language,
      el("div", { class: "pop-holder" }, settingsButton),
      el("label", { class: "row muted", title: TIP_SEED }, "Seed", seedInput),
      el("div", { class: "pop-holder" }, exportButton()),
      batch
        ? el("button", { class: "btn btn-primary", title: "Stop now: the take being generated is cancelled",
          onclick: () => api("POST", `/api/jobs/${batch}/cancel`, {}).catch(fail) }, "Stop")
        : el("button", { class: "btn btn-primary", onclick: generateMissing,
          title: "Generates every line that has no take yet, top to bottom." }, "Generate missing"),
      el("div", { class: "pop-holder" }, more));
  }

  function confirmDeleteSession(anchor) {
    popover(anchor, el("div", { class: "menu" },
      ...deleteSessionConfirm({ id: session.id, name: session.name, lines: session.lines.length }, null)), { align: "right" });
  }

  function sessionSettings() {
    const names = session.models.length ? session.models : installed().map((m) => m.name);
    const box = el("div", { class: "settings-panel" });
    const paint = () => box.replaceChildren(
      el("div", { class: "row" }, el("h2", {}, "Session settings")),
      modelTabs(names, titles(), (name) => {
        const base = defaults(name);
        const values = sessionValues(name);
        return el("div", {},
          sliders(modelInfo(name)?.settings || [], values, base, (spec) => spec.help, (key, value) =>
            api("PUT", `/api/sessions/${sid()}/settings/${name}`, { ...values, [key]: value })
              .then((data) => { session = data; paint(); }, fail), `session:${name}`),
          el("div", { class: "row settings-foot" },
            el("div", { class: "muted small" }, "Default for every line in this session. Lines can override them."),
            el("div", { class: "spacer" }),
            el("button", { class: "btn btn-small", disabled: !session.settings[name], onclick: () =>
              api("DELETE", `/api/sessions/${sid()}/settings/${name}`).then((data) => { session = data; paint(); }, fail) },
            "Reset to model defaults")));
      }, "session"));
    if (!names.length) {
      box.append(el("p", { class: "muted small" }, "Install a model in the Models tab."));
      return box;
    }
    paint();
    return box;
  }

  // --- Cast ----------------------------------------------------------------------------------

  function cast() {
    const add = el("button", { class: "btn btn-ghost" }, icon(ICONS.plus), "Add character");
    add.onclick = () => popover(add, addCharacterMenu());
    const section = el("section", { class: "cast", "aria-label": "Cast" },
      el("div", { class: "muted" }, "Cast"),
      session.cast.map(chip),
      el("div", { class: "pop-holder" }, add));
    return section;
  }

  function chip(entry) {
    const sessionOnly = entry.scope === "session";
    const deleted = entry.name === null;
    const label = deleted ? "Deleted character" : entry.name;
    const meta = deleted ? "" : sessionOnly ? "this session"
      : entry.samples.length ? plural(entry.samples.length, "sample") : "default voice";
    const nameNode = deleted ? el("span", { class: "warn" }, label)
      : sessionOnly ? el("button", { class: "link-btn", title: "Edit samples", onclick: () => { editing = editing === entry.character ? null : entry.character; editingOpen = true; justOpened = "card"; draw(); } }, label)
        : el("a", { class: "link-btn", href: `#/characters/${entry.character}`, title: "Open in Characters" }, label);
    return el("div", { class: "chip" },
      avatar(entry.character, deleted ? "?" : entry.name, 24), nameNode,
      meta && el("span", { class: "muted small" }, meta),
      sessionOnly && el("button", { class: "btn btn-small chip-action", onclick: () =>
        api("POST", `/api/sessions/${sid()}/cast/${entry.character}/save`, {}).then((data) => {
          apply(data); setMessage(message, `${entry.name} is now in your character library.`);
        }, fail), title: "Move this character to your library so other sessions can use it too." }, "Save to library"),
      el("button", { class: "chip-x", "aria-label": `Remove ${label} from cast`, title: "Remove from cast", onclick: () =>
        api("DELETE", `/api/sessions/${sid()}/cast/${entry.character}`).then(apply, fail) }, icon(ICONS.close, 12)));
  }

  function addCharacterMenu() {
    const inCast = new Set(session.cast.map((c) => c.character));
    const available = library.filter((c) => !inCast.has(c.id));
    const nameInput = el("input", { class: "input", placeholder: "Name", "aria-label": "New character name",
      onkeydown: (e) => { if (e.key === "Enter") createInSession(); } });
    async function createInSession() {
      const value = nameInput.value.trim();
      if (!value) return nameInput.focus();
      try {
        const created = await api("POST", "/api/characters", { name: value, session: sid() });
        editing = created.id;
        document.querySelector(".popover")?.dispatchEvent(new Event("close"));
        await refresh();
      } catch (error) { fail(error); }
    }
    return el("div", { class: "menu add-menu" },
      el("div", { class: "menu-title" }, "From your library"),
      available.length ? available.map((c) => el("button", { class: "menu-item", onclick: () => {
        document.querySelector(".popover")?.dispatchEvent(new Event("close"));
        api("POST", `/api/sessions/${sid()}/cast`, { character: c.id, scope: "library" }).then(apply, fail);
      } }, avatar(c.id, c.name, 20), el("span", { class: "grow" }, c.name),
      el("span", { class: "faint small" }, c.samples.length ? plural(c.samples.length, "sample") : "default voice")))
        : el("div", { class: "faint small menu-note" }, library.length ? "Everyone is already in the cast." : "No library characters yet."),
      el("div", { class: "menu-sep" }),
      el("div", { class: "menu-title" }, "Only in this session"),
      el("div", { class: "row menu-note" }, nameInput, el("button", { class: "btn", onclick: createInSession }, "Create")));
  }

  // A session-only character as a card in the same style as an open line: a header row (name, scope,
  // Save to library, collapse, close) and, when expanded, its samples.
  function sessionCharacterEditor(entry) {
    const name = el("input", { class: "input", value: entry.name, "aria-label": "Character name", onchange: () => {
      const value = name.value.trim();
      if (!value) { name.value = entry.name; return; }
      api("PATCH", `/api/characters/${entry.character}?session=${sid()}`, { name: value }).then(refresh, fail);
    } });
    const count = entry.samples.length;
    const summary = count
      ? `${plural(count, "sample")} \u00b7 default \u201c${(entry.samples.find((x) => x.id === entry.default_sample) || entry.samples[0]).label}\u201d`
      : "No samples \u00b7 default voice";
    const toggle = el("button", { class: "btn btn-ghost icon-btn close-details", "aria-expanded": String(editingOpen),
      "aria-label": editingOpen ? "Collapse" : "Expand", title: editingOpen ? "Collapse" : "Show samples",
      onclick: () => setOpen(!editingOpen) }, icon(editingOpen ? ICON_CLOSE : ICON_OPEN, 16));
    const card = el("section", { class: `line-details character-card ${editingOpen ? "" : "collapsed"} ${justOpened === "card" ? "opening" : ""}`, "aria-label": `Character ${entry.name}` });
    const head = el("div", { class: "detail-head", title: editingOpen ? "Click an empty spot to collapse" : "Click to show samples" },
      avatar(entry.character, entry.name, 28),
      el("label", { class: "row field", title: "Only in this session. Save to library to reuse it in other sessions." },
        "Character", name),
      el("span", { class: "scope-badge", title: "Only in this session" }, "this session"),
      el("span", { class: "faint small" }, summary),
      el("div", { class: "spacer" }),
      el("button", { class: "btn btn-small", title: "Move this character to your library so other sessions can use it too.",
        onclick: () => api("POST", `/api/sessions/${sid()}/cast/${entry.character}/save`, {}).then((data) => {
          editing = null; apply(data); setMessage(message, `${entry.name} is now in your character library.`);
        }, fail) }, "Save to library"),
      toggle,
      el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Close", title: "Close",
        onclick: () => close(() => { editing = null; }) }, icon(ICONS.close)));
    head.addEventListener("click", (e) => {
      if (e.target === head || e.target.classList.contains("spacer") || e.target.classList.contains("faint")) setOpen(!editingOpen);
    });
    async function close(after) {
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
        card.classList.add("closing");
        await new Promise((done) => { card.addEventListener("animationend", done, { once: true }); setTimeout(done, 300); });
      }
      after();
      draw();
    }
    function setOpen(value) {
      if (!value) return close(() => { editingOpen = false; });
      editingOpen = true;
      justOpened = "card";
      draw();
    }
    card.append(head);
    if (editingOpen) {
      let first = true;
      card.append(el("div", { class: "character-body" }, samplePanel(null, entry.character, sid(), async () => {
        if (first) { first = false; return; }
        session = await api("GET", `/api/sessions/${sid()}`); // keep the panel; chips update on the next redraw
      })));
    }
    return card;
  }

  // --- Script --------------------------------------------------------------------------------

  function script() {
    const rows = el("div", { class: `script ${picked.size ? "picking" : ""}` });
    if (!session.lines.length) {
      rows.append(el("div", { class: "script-empty muted" }, session.cast.length
        ? "No lines yet. Add a line or paste a script."
        : "Add a character to the cast, then add lines or paste a script."));
    }
    session.lines.forEach((line, i) => {
      rows.append(openLine === line.id ? details(line, i) : row(line, i));
      if (i < session.lines.length - 1) rows.append(gap(line));
    });
    rows.append(el("div", { class: "script-actions" },
      el("button", { class: "btn btn-ghost", onclick: () => addLine(null) }, icon(ICONS.plus), "Add line"),
      el("button", { class: "btn btn-ghost", onclick: () => { pasting = !pasting; draw(); } }, "Paste script")));
    if (pasting) rows.append(pasteBox());
    return el("section", { class: "script-wrap", "aria-label": "Script" }, rows);
  }

  function speaker(line) {
    const deleted = !castEntry(line.character)?.name;
    const [color] = characterColors(line.character);
    return el("div", { class: "speaker" },
      el("div", { class: "row speaker-name" }, dot(deleted ? "var(--faint)" : color, 8),
        deleted ? el("span", { class: "warn" }, "Deleted character") : line.character_name),
      el("div", { class: "faint small speaker-sample" }, sampleOf(line)?.label || "default voice",
        line.language && ` \u00b7 ${line.language.toUpperCase()}`));
  }

  function row(line, i) {
    const takes = line.takes;
    const selected = takes.find((t) => t.file === line.selected);
    const right = el("div", { class: "row line-right" });
    if (generating.has(line.id)) {
      right.append(busyLabel(line.id, "Generating\u2026"));
    } else if (selected) {
      right.append(player(`/files/sessions/${sid()}/${selected.file}`, { buckets: 30, showTime: false, label: "Play selected take" }),
        el("button", { class: "btn btn-ghost btn-takes", onclick: () => open(line.id) },
          `${titles()[selected.model] || selected.model} · ${plural(takes.length, "take")}`));
    } else {
      const empty = !line.text.trim();
      right.append(el("button", { class: "btn", disabled: empty, title: empty ? "Write the line first" : "",
        onclick: () => generate(line, session.models, seed) }, "Generate"));
    }
    const more = el("button", { class: "icon-btn btn btn-ghost hover-only", "aria-label": "More actions", title: "More" }, icon(ICON_MORE));
    more.onclick = () => popover(more, lineMenu(line, i, more), { align: "right" });
    const remove = el("button", { class: "icon-btn btn btn-ghost hover-only", "aria-label": `Delete line ${i + 1}`, title: "Delete line" },
      icon(ICONS.trash));
    remove.onclick = () => confirmDeleteLine(remove, line, i);
    right.append(el("div", { class: "pop-holder" }, remove), el("div", { class: "pop-holder" }, more),
      el("button", { class: "btn btn-ghost icon-btn open-hint", "aria-label": "Open details", title: "Open details",
        onclick: () => open(line.id) }, icon(ICON_OPEN, 16)));

    const long = line.text.length > LONG_LINE;
    const node = el("div", { class: `line ${generating.has(line.id) ? "is-generating" : ""} ${justClosed === line.id ? "reopened" : ""} `
      + `${playback.lineId === line.id ? "now-playing" : ""} ${justDone?.line === line.id ? "just-done" : ""}`,
      "data-line": line.id,
      title: "Click to edit the line and its takes" },
    pickBox(line), handle(line), speaker(line),
    el("div", { class: "line-body" },
      el("div", { class: `line-text ${line.text ? "" : "faint"}` },
        line.text ? soundText(line.text, soundTags(), TAG_LABELS, el) : "Empty line \u2014 click to write it"),
      long && el("div", { class: "faint small" }, `${line.text.length} characters \u00b7 click to see all or split it`)),
    right);
    node.addEventListener("click", (e) => { if (!e.target.closest("button, a, input, select, .player, .popover")) open(line.id); });
    dragTarget(node, line);
    return node;
  }

  function lineMenu(line, i, anchor) {
    const close = () => document.querySelector(".popover")?.dispatchEvent(new Event("close"));
    const order = session.lines.map((l) => l.id);
    const move = (to) => { close(); api("POST", `/api/sessions/${sid()}/lines/order`, { order: moveLine(order, line.id, order[to], to > i) }).then(apply, fail); };
    return el("div", { class: "menu" },
      el("button", { class: "menu-item", disabled: !line.selected, onclick: () => { close(); playFrom(i); } }, "Play from here"),
      el("button", { class: "menu-item", onclick: () => { close(); open(line.id); } }, "Edit and takes"),
      el("button", { class: "menu-item", onclick: () => { close(); open(line.id); } }, "Perform this line"),
      el("button", { class: "menu-item", disabled: !line.selected || exporting, title: line.selected ? "" : "Generate a take first.",
        onclick: () => popover(anchor, exportPanel(line, i), { align: "right" }) }, "Export this line\u2026"),
      el("button", { class: "menu-item", disabled: i === 0, onclick: () => move(i - 1) }, "Move up"),
      el("button", { class: "menu-item", disabled: i === session.lines.length - 1, onclick: () => move(i + 1) }, "Move down"),
      el("div", { class: "menu-sep" }),
      el("button", { class: "menu-item danger", onclick: () => confirmDeleteLine(anchor, line, i) }, "Delete line\u2026"));
  }

  function confirmDeleteLine(anchor, line, i) {
    const close = () => document.querySelector(".popover")?.dispatchEvent(new Event("close"));
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete line ${i + 1}?`),
      el("div", { class: "muted small" }, line.takes.length
        ? `Its ${plural(line.takes.length, "take")} are removed permanently.` : "It has no takes."),
      el("button", { class: "btn btn-danger", onclick: () => {
        close();
        if (openLine === line.id) openLine = null;
        api("DELETE", `/api/sessions/${sid()}/lines/${line.id}`).then(apply, fail);
      } }, "Delete line")), { align: "right" });
  }

  // Six solid dots: easier to see than a stroked icon.
  function grip() {
    const svg = el("svg", { width: 14, height: 18, viewBox: "0 0 14 18", fill: "currentColor", "aria-hidden": "true" });
    for (const x of [4, 10]) for (const y of [3, 9, 15]) svg.append(el("circle", { cx: x, cy: y, r: 1.7 }));
    return svg;
  }

  // Drag to reorder; with the keyboard, focus it and press the up/down arrows.
  function handle(line) {
    return el("button", { class: "handle", "aria-label": "Reorder: drag, or press the up and down arrow keys",
      title: "Drag to reorder",
      onpointerdown: (e) => { e.target.closest("[data-line]").draggable = true; },
      onpointerup: (e) => { e.target.closest("[data-line]").draggable = false; },
      onkeydown: (e) => {
        const step = e.key === "ArrowUp" ? -1 : e.key === "ArrowDown" ? 1 : 0;
        const order = session.lines.map((l) => l.id);
        const i = order.indexOf(line.id);
        if (!step || i + step < 0 || i + step >= order.length) return;
        e.preventDefault();
        api("POST", `/api/sessions/${sid()}/lines/order`, { order: moveLine(order, line.id, order[i + step], step > 0) })
          .then((data) => { apply(data); main.querySelector(`[data-line="${line.id}"] .handle`)?.focus(); }, fail);
      } }, grip());
  }

  function dragTarget(node, line) {
    node.addEventListener("dragstart", (e) => {
      dragging = line.id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", line.id);
      node.classList.add("dragging");
    });
    node.addEventListener("dragend", () => {
      node.draggable = false;
      dragging = null;
      document.querySelectorAll(".dragging, .drop-before, .drop-after").forEach((n) => n.classList.remove("dragging", "drop-before", "drop-after"));
    });
    node.addEventListener("dragover", (e) => {
      if (!dragging || dragging === line.id) return;
      e.preventDefault();
      const box = node.getBoundingClientRect();
      const after = e.clientY > box.top + box.height / 2;
      node.classList.toggle("drop-after", after);
      node.classList.toggle("drop-before", !after);
    });
    node.addEventListener("dragleave", () => node.classList.remove("drop-before", "drop-after"));
    node.addEventListener("drop", (e) => {
      e.preventDefault();
      const after = node.classList.contains("drop-after");
      const moved = dragging;
      node.classList.remove("drop-before", "drop-after");
      if (!moved || moved === line.id) return;
      const order = moveLine(session.lines.map((l) => l.id), moved, line.id, after);
      api("POST", `/api/sessions/${sid()}/lines/order`, { order }).then(apply, fail);
    });
  }

  function gap(line) {
    return el("div", { class: "gap" },
      el("button", { class: "insert", onclick: () => addLine(line) }, "+ Insert line"),
      el("div", { class: "gap-line" }),
      el("div", { class: "faint num gap-pause" }, `${Number(line.pause_after).toFixed(1)} s pause`));
  }

  async function addLine(after) {
    const last = after || session.lines[session.lines.length - 1];
    const character = last?.character || session.cast.find((c) => c.name)?.character;
    if (!character) return setMessage(message, "Add a character to the cast first.", "warn");
    try {
      const result = await api("POST", `/api/sessions/${sid()}/lines`, { character, after: after?.id || null });
      openLine = result.id;
      apply(result);
      main.querySelector(".line-details .sound-editor")?.focus();
    } catch (error) { fail(error); }
  }

  function pasteBox() {
    const text = el("textarea", { class: "textarea", rows: 6, "aria-label": "Script to paste",
      placeholder: "Host: Welcome to the show.\nGuest: Thanks for having me." });
    const split = el("input", { type: "checkbox", checked: true });
    return el("div", { class: "paste" },
      text,
      el("label", { class: "row small muted paste-option",
        title: "Models work best with a sentence or two. Long speeches become several lines of the same speaker." },
      split, `Split speeches longer than ${LONG_LINE} characters into lines by sentence`),
      el("div", { class: "row" },
        el("button", { class: "btn btn-primary", onclick: async () => {
          try {
            const result = await api("POST", `/api/sessions/${sid()}/paste`, { text: text.value, split: split.checked });
            pasting = false;
            apply(result);
            const note = result.split ? ` ${plural(result.split, "long speech", "long speeches")} split by sentence.` : "";
            setMessage(message, `Added ${plural(result.added, "line")}.${note}`);
          } catch (error) { fail(error); }
        } }, "Add lines"),
        el("button", { class: "btn btn-ghost", onclick: () => { pasting = false; draw(); } }, "Cancel"),
        el("span", { class: "muted small" }, "One line per speaker as \u201cName: text\u201d. New names join the cast as session characters.")));
  }

  function open(lineId) {
    openLine = lineId;
    justOpened = lineId;
    draw();
  }

  // --- Line details --------------------------------------------------------------------------

  function details(line, i) {
    const patch = (fields) => api("PATCH", `/api/sessions/${sid()}/lines/${line.id}`, fields).then(apply, fail);
    const entry = castEntry(line.character);
    const characterSelect = el("select", { class: "select select-small", "aria-label": "Character",
      title: "Who speaks this line. Only characters in the cast are listed.",
      onchange: () => patch({ character: characterSelect.value, sample: null }) },
    !entry?.name && el("option", { value: line.character, disabled: true }, "Deleted character"),
    session.cast.filter((c) => c.name).map((c) => el("option", { value: c.character }, c.name)));
    characterSelect.value = line.character;
    const sample = sampleOf(line);
    const sampleSelect = el("select", { class: "select select-small", "aria-label": "Sample", disabled: !entry?.samples.length,
      onchange: () => patch({ sample: sampleSelect.value }) },
    entry?.samples.length ? entry.samples.map((s) => el("option", { value: s.id }, s.label)) : el("option", {}, "default voice"));
    if (sample) sampleSelect.value = sample.id;
    // Text is saved while typing without redrawing: a redraw on blur would replace the Generate button under
    // the pointer and swallow the click.
    let typing = null;
    const saveText = () => {
      clearTimeout(typing);
      delete pendingText[line.id];
      if (text.value === line.text) return Promise.resolve();
      line.text = text.value;
      return api("PATCH", `/api/sessions/${sid()}/lines/${line.id}`, { text: text.value }).then((data) => { session = data; }, fail);
    };
    // Plain text with sound tags shown as chips; behaves like a textarea (.value, "input").
    const text = soundEditor({ value: line.text, tags: soundTags(), labels: TAG_LABELS, ariaLabel: "Line text", el,
      placeholder: "Write what this character says", suggestions: soundChoices() });
    text.classList.add("line-input");
    text.addEventListener("input", () => { clearTimeout(typing); pendingText[line.id] = saveText; typing = setTimeout(saveText, 600); });
    text.addEventListener("blur", () => saveText());
    const pause = el("input", { class: "input pause", value: line.pause_after, inputmode: "decimal", "aria-label": "Pause after the line in seconds",
      onchange: () => {
        const value = Number(pause.value.replace(",", "."));
        if (!Number.isFinite(value) || value < 0 || value > 10) { pause.value = line.pause_after; return setMessage(message, "Pause must be between 0 and 10 seconds.", "warn"); }
        line.pause_after = value;
        api("PATCH", `/api/sessions/${sid()}/lines/${line.id}`, { pause_after: value }).then((data) => { session = data; }, fail);
      } });

    const chosen = lineModels[line.id] || session.models;
    const picker = modelPicker(installed(), chosen, (names) => { lineModels[line.id] = names; draw(); });
    const lineSeed = el("input", { class: "input seed", placeholder: "Random", value: lineSeeds[line.id] ?? seed, inputmode: "numeric",
      "aria-label": "Seed for this line", oninput: () => { lineSeeds[line.id] = lineSeed.value.replace(/\D/g, ""); lineSeed.value = lineSeeds[line.id]; } });
    // Models that cannot speak the line's language are skipped (the note under the line says so).
    const speaks = (name) => modelInfo(name)?.languages.some((l) => l.code === lineLanguage(line));
    const usable = picker.get().filter(speaks);
    const count = usable.length;
    const busy = generating.has(line.id);
    const exportLineButton = el("button", { class: "btn btn-ghost icon-btn", "aria-label": `Export line ${i + 1}`,
      disabled: !line.selected || exporting,
      title: line.selected ? "Export this line\u2019s selected take (WAV, or a FLAC, MP3 or OGG copy)" : "Generate a take first." },
    icon(ICON_EXPORT, 16));
    exportLineButton.onclick = () => popover(exportLineButton, exportPanel(line, i), { align: "right" });
    const deleteButton = el("button", { class: "btn btn-ghost icon-btn", "aria-label": `Delete line ${i + 1}`, title: "Delete line" },
      icon(ICONS.trash));
    deleteButton.onclick = () => confirmDeleteLine(deleteButton, line, i);
    const generateButton = el("button", { class: "btn btn-primary", disabled: busy || !count || !line.text.trim(),
      title: !line.text.trim() ? "Write the line first" : !count && picker.get().length ? "No selected model speaks this language" : "",
      onclick: () => generate(line, usable, lineSeeds[line.id] ?? seed) },
    busy ? busyLabel(line.id, "Generating\u2026") : `Generate ${plural(count || 0, "take")}`);
    // Cancel stops the model at once; it loads again for the next take.
    const cancelButton = busy && lineJobs.has(line.id) && el("button", { class: "btn", title: "Stop generating this line now",
      onclick: () => { cancelButton.disabled = true; api("POST", `/api/jobs/${lineJobs.get(line.id)}/cancel`, {}).catch(fail); } },
    "Cancel");
    text.addEventListener("input", () => {
      generateButton.disabled = busy || !count || !text.value.trim();
      generateButton.title = text.value.trim() ? "" : "Write the line first";
    });

    // Plays the closing animation, then shows the row again (which fades in).
    const close = async () => {
      if (node.classList.contains("closing")) return;
      await pendingText[line.id]?.();
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
        node.classList.add("closing");
        await new Promise((done) => { node.addEventListener("animationend", done, { once: true }); setTimeout(done, 300); });
      }
      openLine = null;
      justClosed = line.id;
      draw();
      justClosed = null;
    };
    // "Add sound": a [tag] at the cursor. Only models that perform tags get them; others get the text without.
    function soundButton(field, save) {
      const tags = [...new Set(installed().flatMap((m) => m.tags || []))];
      if (!tags.length) return null;
      const button = el("button", { class: "btn btn-small sound-btn", title: "Insert a sound, emotion, style or delivery tag at the cursor. Models that cannot perform a tag skip it." },
        icon(["M12 5v14", "M5 12h14"], 12), "Add tag");
      button.onclick = () => popover(button, el("div", { class: "menu tag-menu" }, ...soundChoices().flatMap((s, n, all) => [
        n === 0 || s.group !== all[n - 1].group ? el("div", { class: "faint small suggest-head" }, s.group) : null,
        el("button", { class: "menu-item suggest-item", onclick: () => {
          document.querySelector(".popover")?.dispatchEvent(new Event("close"));
          field.insertSound(s.tag);
          save();
        } }, el("span", {}, s.label), el("span", { class: "faint small" }, s.note))])));
      // "Higgs performs emotions, styles, delivery and sounds; OmniVoice performs sounds; Chatterbox skips them."
      const name = (m) => m.title.split(" ")[0];
      const kinds = (m) => TAG_GROUP_ORDER.slice(1).concat("Sounds")
        .filter((g) => (m.tags || []).some((t) => tagGroup(t) === g)).map((g) => g.toLowerCase());
      const list = (words) => (words.length > 1 ? `${words.slice(0, -1).join(", ")} and ${words.at(-1)}` : words[0]);
      const performers = installed().filter((m) => m.tags?.length);
      const skippers = installed().filter((m) => !m.tags?.length);
      return el("div", { class: "row sound-tools" }, el("div", { class: "pop-holder" }, button),
        el("span", { class: "faint small" }, "or type [ in the text to pick one. ",
          performers.map((m) => `${name(m)} performs ${list(kinds(m))}`).join("; ")
          + (skippers.length ? `; ${skippers.map(name).join(", ")} ${skippers.length === 1 ? "skips" : "skip"} them` : "")
          + (performers.some((m) => m.name === "omnivoice") ? ". OmniVoice: clearer with a higher Quality." : ".")));
    }
    const counter = el("span", { class: "faint small num nowrap" }, `${line.text.length} characters`);
    text.addEventListener("input", () => { counter.textContent = `${text.value.length} characters`; });
    const head = el("div", { class: "detail-head", title: "Click an empty spot to close" },
      handle(line),
      el("label", { class: "row field", title: "Who speaks this line. Only characters in the cast are listed." },
        dot(characterColors(line.character)[0], 8), "Character", characterSelect),
      el("label", { class: "row field", title: "Which recording of the voice to clone. Samples recorded in different moods steer "
        + "the delivery. Without samples the model's default voice is used (random for OmniVoice unless a seed is set)." },
        "Sample", sampleSelect),
      el("label", { class: "row field", title: "The language the text is written in. Models read the text in that "
        + "language; they do not translate it. \u201cSession\u201d follows the session's language." }, "Language",
        languageSelect(picker.get(), line.language, (code) => patch({ language: code }), session.language, true)),
      el("label", { class: "row field", title: "Silence after this line in the export, in seconds." }, "Pause", pause, "s"),
      el("div", { class: "spacer" }),
      el("div", { class: "pop-holder" }, exportLineButton),
      el("div", { class: "pop-holder" }, deleteButton),
      el("button", { class: "btn btn-ghost icon-btn close-details", "aria-label": "Close details", title: "Close (Esc)", onclick: close },
        icon(ICON_CLOSE, 16)));
    head.addEventListener("click", (e) => { if (e.target === head || e.target.classList.contains("spacer")) close(); });
    const node = el("div", { class: `line-details ${justOpened === line.id ? "opening" : ""} ${justDone?.line === line.id ? "just-done" : ""}`,
      "data-line": line.id,
      onkeydown: (e) => { if (e.key === "Escape" && !e.target.closest(".popover")) { e.preventDefault(); close(); } } },
      head,
      el("div", { class: "detail-text" }, text, el("div", { class: "row" }, soundButton(text, saveText), el("div", { class: "spacer" }), counter)),
      el("div", { class: "detail-row row wrap" },
        el("div", { class: "muted", title: TIP_MODELS }, "Generate with"), picker.element,
        el("label", { class: "row muted", title: TIP_SEED }, "Seed", lineSeed),
        generateButton, cancelButton || null,
        el("div", { class: "faint small" }, "One take per selected model, so you can compare them.")),
      longNote(line, text),
      languageNotes(line, picker.get()),
      lineSettings(line, picker.get()),
      el("div", { class: "detail-bottom" }, takesList(line), perform(line)));
    dragTarget(node, line);
    return node;
  }

  // Follows the text box as you type: appears past LONG_LINE characters, disappears below it.
  function longNote(line, textBox) {
    const box = el("div", { class: "detail-row row wrap small long-note" });
    const update = () => {
      const value = textBox.value;
      box.hidden = value.length <= LONG_LINE;
      if (box.hidden) return box.replaceChildren();
      const parts = splitSentences(value, SPLIT_SIZE);
      box.replaceChildren(...[
        el("span", { class: "warn" }, `This line is long (${value.length} characters). Models work best with a sentence or two; `
          + "very long lines can be cut off or drift."),
        parts.length > 1 && el("button", { class: "btn btn-small", onclick: async () => {
          await pendingText[line.id]?.();
          splitLine(line, splitSentences(textBox.value, SPLIT_SIZE));
        } }, `Split into ${parts.length} lines`),
      ].filter(Boolean)); // replaceChildren would show false as the text "false"
    };
    textBox.addEventListener("input", update);
    update();
    return box;
  }

  // Keeps the first part in this line and adds the rest after it, with the same character, sample and language.
  async function splitLine(line, parts) {
    try {
      await api("PATCH", `/api/sessions/${sid()}/lines/${line.id}`, { text: parts[0] });
      let after = line.id;
      for (const part of parts.slice(1)) {
        const result = await api("POST", `/api/sessions/${sid()}/lines`,
          { character: line.character, text: part, pause_after: line.pause_after, after });
        after = result.id;
        if (line.sample || line.language) {
          await api("PATCH", `/api/sessions/${sid()}/lines/${after}`, { sample: line.sample, language: line.language });
        }
      }
      await refresh();
      setMessage(message, `Split into ${parts.length} lines. Existing takes stay on the first line.`);
    } catch (error) { fail(error); }
  }

  // Warns when a chosen model cannot speak the line's language.
  function languageNotes(line, names) {
    const language = lineLanguage(line);
    const notes = [];
    for (const name of names) {
      const info = modelInfo(name);
      if (info && !info.languages.some((l) => l.code === language)) {
        notes.push(el("div", { class: "warn small" }, `${info.title} does not support ${languageName(language)}, so it is skipped.`));
      }
    }
    return notes.length ? el("div", { class: "detail-row language-notes" }, notes) : null;
  }

  // When the sample is in another language than the line, the voice may keep the sample's accent. Shown in the tab of
  // a model that has a setting against it (Chatterbox), with a button that sets it for this line.
  function accentNote(line, name) {
    const info = modelInfo(name);
    const sample = sampleOf(line);
    const language = lineLanguage(line);
    if (!info?.accent_setting || !sample?.language || sample.language === language) return null;
    const { key, value } = info.accent_setting;
    const label = info.settings.find((x) => x.key === key)?.label || key;
    const applied = ({ ...sessionValues(name), ...(line.settings[name] || {}) })[key] === value;
    return el("div", { class: "row small wrap accent-note" },
      el("span", { class: applied ? "muted" : "warn" }, `The sample \u201c${sample.label}\u201d is ${languageName(sample.language)} `
        + `and the line is ${languageName(language)}, so the voice may keep a ${languageName(sample.language)} accent.`
        + (applied ? ` ${label} is ${value} to reduce it.` : "")),
      applied ? null : el("button", { class: "btn btn-small", onclick: () =>
        api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${name}`, { ...(line.settings[name] || {}), [key]: value })
          .then((data) => { apply(data); setMessage(message, `${label} set to ${value} for this line.`); }, fail) },
      "Reduce accent"));
  }

  function lineSettings(line, names) {
    if (!names.length) return null;
    const changes = names.reduce((n, name) => n + settingsChanges(line.settings[name], sessionValues(name)).length, 0);
    return el("section", { class: "detail-row line-settings", "aria-label": "Line settings" },
      el("div", { class: "row" },
        el("h3", {}, "Settings for this line"),
        el("div", { class: `small ${changes ? "accent" : "faint"}` },
          changes ? `${plural(changes, "change")} from session settings` : "Same as session settings")),
      modelTabs(names, titles(), (name) => {
        const base = sessionValues(name);
        const values = { ...base, ...(line.settings[name] || {}) };
        const own = settingsChanges(line.settings[name], base).length;
        return el("div", {},
          accentNote(line, name),
          sliders(modelInfo(name)?.settings || [], values, base,
            (spec, value, baseValue) => (value === baseValue ? "Same as session"
              : spec.type === "text" ? (baseValue ? `Session: ${baseValue}` : "Session: none")
                : `Session: ${Number(baseValue).toFixed(spec.step >= 1 ? 0 : 2)}`),
            (key, value) => {
              const overrides = { ...(line.settings[name] || {}), [key]: value };
              if (value === base[key]) delete overrides[key];
              api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${name}`, overrides).then(apply, fail);
            }, `line:${line.id}:${name}`),
          el("div", { class: "row settings-foot" },
            el("div", { class: "spacer" }),
            el("button", { class: "btn btn-small", disabled: !own,
              title: `Forget this line's own ${titles()[name] || name} settings and use the session's.`,
              onclick: () => api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${name}`, {}).then(apply, fail) },
            "Reset to session settings")));
      }, `line:${line.id}`));
  }

  function takesList(line) {
    const takes = [...line.takes].reverse();
    return el("section", { class: "takes" },
      el("h3", {}, "Takes"),
      takes.length ? takes.map((take) => takeRow(line, take)) : el("p", { class: "muted small" }, "No takes yet."),
      takes.length > 1 && el("div", { class: "faint small" }, "The selected take is used in the export."));
  }

  function takeRow(line, take) {
    const isSelected = take.file === line.selected;
    const converted = take.kind === "convert";
    const model = converted ? "Converted" : titles()[take.model] || take.model;
    const meta = converted
      ? `from your recording · Chatterbox VC · ${take.duration} s`
      : [take.sample_label, take.language && languageName(take.language), `seed ${take.seed}`, `${take.duration} s`]
        .filter(Boolean).join(" \u00b7 ");
    const rowNode = el("div", { class: `take ${justDone?.file === take.file ? "just-done" : ""}` },
      el("input", { type: "radio", name: `take-${line.id}`, checked: isSelected, "aria-label": `Use take ${takeNumber(take.file)}`,
        title: "The selected take is the one used in the export.",
        onchange: () => api("POST", `/api/sessions/${sid()}/lines/${line.id}/takes/select`, { file: take.file }).then(apply, fail) }),
      player(`/files/sessions/${sid()}/${take.file}`, { buckets: 60, showTime: false, selected: isSelected }),
      el("div", { class: "take-info" },
        el("div", { class: "row" }, dot(modelColor(take.model)), el("span", {}, model),
          el("span", { class: "muted" }, `· take ${takeNumber(take.file) ?? "?"}`)),
        el("div", { class: "faint small" }, meta,
          take.trimmed_from && [" · ", el("span", { title: `Trimmed copy (${take.trim?.join("\u2013")} s) of ${take.trimmed_from.split("/").pop()}` }, "trimmed")],
          take.custom_settings && [" · ", el("span", { class: "accent", title: "Generated with settings that differ from the session's current ones." }, "custom settings")],
          take.text_changed && [" · ", el("span", { class: "warn", title: `The line's text changed after this take. The take says: \u201c${take.text}\u201d` }, "text changed")])),
      !converted && take.settings && el("button", { class: "btn btn-small btn-ghost", title: "Copy this take's seed and settings to the line",
        onclick: () => useSettings(line, take) }, "Use these settings") || el("span"),
      el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Trim take", "aria-expanded": "false",
        title: "Trim: cut silence or noise from the start and end (saved as a new take)",
        onclick: (e) => toggleTrim(e.currentTarget, rowNode, line, take) }, icon(ICON_SCISSORS)),
      revealButton(`sessions/${sid()}/${take.file}`),
      el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Delete take", title: "Delete take", onclick: () => {
        rowNode.querySelector(".confirm")?.remove();
        rowNode.append(el("div", { class: "confirm" },
          el("span", {}, `Delete take ${takeNumber(take.file) ?? ""}? The file is removed.`),
          el("div", { class: "row" },
            el("button", { class: "btn btn-danger btn-small", onclick: () => {
              stopAudio(`/files/sessions/${sid()}/${take.file}`);
              api("DELETE", `/api/sessions/${sid()}/lines/${line.id}/takes`, { file: take.file }).then(apply, fail);
            } }, "Delete"),
            el("button", { class: "btn btn-ghost btn-small", onclick: (e) => e.target.closest(".confirm").remove() }, "Cancel"))));
      } }, icon(ICONS.trash)));
    return rowNode;
  }

  // Opens a trim range under a take; saving makes a new trimmed take (the original stays).
  async function toggleTrim(button, rowNode, line, take) {
    const open = rowNode.querySelector(".trim-box");
    if (open) { open.remove(); button.setAttribute("aria-expanded", "false"); return; }
    button.setAttribute("aria-expanded", "true");
    const box = el("div", { class: "trim-box" }, el("div", { class: "muted small" }, "Loading\u2026"));
    rowNode.append(box);
    try {
      const { samples, sampleRate } = await decode(`/files/sessions/${sid()}/${take.file}`);
      // Two ways to save: as a new take (the original stays) or in place of the original.
      const asCopy = el("button", { class: "btn btn-primary btn-small",
        title: "Keep the original and add the trimmed audio as a new, selected take" }, "Save as new take");
      const replace = el("button", { class: "btn btn-small",
        title: "Save the trimmed audio and delete the original take" }, "Replace original");
      const range = rangeEditor(samples, sampleRate, (start, end) => {
        asCopy.disabled = replace.disabled = end - start < 0.3;
      });
      const save = async (replaceOriginal) => {
        const [start, end] = range.getRange();
        asCopy.disabled = replace.disabled = true;
        if (replaceOriginal) stopAudio(`/files/sessions/${sid()}/${take.file}`);
        try {
          apply(await api("POST", `/api/sessions/${sid()}/lines/${line.id}/takes/trim`,
            { file: take.file, start, end, replace: replaceOriginal }));
          setMessage(message, replaceOriginal
            ? `Take ${takeNumber(take.file) ?? ""} was trimmed; the original was deleted.`
            : `Saved a trimmed copy of take ${takeNumber(take.file) ?? ""}; it is now selected.`);
        } catch (error) { asCopy.disabled = replace.disabled = false; fail(error); }
      };
      asCopy.onclick = () => save(false);
      replace.onclick = () => {
        // Deleting the original cannot be undone: confirm in place.
        replace.replaceWith(el("span", { class: "row small" },
          el("span", { class: "warn" }, "Delete the original take?"),
          el("button", { class: "btn btn-danger btn-small", onclick: () => save(true) }, "Replace"),
          el("button", { class: "btn btn-ghost btn-small", onclick: (e) => e.target.parentElement.replaceWith(replace) }, "Cancel")));
      };
      box.replaceChildren(
        el("div", { class: "muted small" }, "Drag the handles to keep only the part you want."),
        range.element,
        el("div", { class: "row" }, asCopy, replace,
          el("button", { class: "btn btn-ghost btn-small", onclick: () => { box.remove(); button.setAttribute("aria-expanded", "false"); } },
            "Cancel")));
    } catch {
      box.replaceChildren(el("div", { class: "warn small" }, "Cannot read this take's audio."));
    }
  }

  async function useSettings(line, take) {
    lineSeeds[line.id] = String(take.seed);
    const chosen = lineModels[line.id] || session.models;
    if (!chosen.includes(take.model)) lineModels[line.id] = [...chosen, take.model];
    const base = sessionValues(take.model);
    const overrides = Object.fromEntries(Object.entries(take.settings).filter(([key, value]) => base[key] !== value));
    try {
      apply(await api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${take.model}`, overrides));
      setMessage(message, `Line ${session.lines.findIndex((l) => l.id === line.id) + 1} now uses seed ${take.seed} and that take's settings.`);
    } catch (error) { fail(error); }
  }

  function perform(line) {
    const status = el("div", { class: "muted small grow" }, "Ready to record");
    const meter = el("div", { class: "meter" }, el("div"));
    const mic = el("select", { class: "select select-small", "aria-label": "Microphone",
      onchange: () => { mic.title = mic.selectedOptions[0]?.textContent || ""; } });
    const button = el("button", { class: "record-round", "aria-label": "Record",
      title: "Record yourself reading the line; it is converted to this character's voice as a new take." }, el("span", { class: "rec-dot" }));
    const fileInput = el("input", { type: "file", accept: "audio/*", class: "sr-only", onchange: async () => {
      const file = fileInput.files[0];
      fileInput.value = "";
      if (!file) return;
      try {
        const { samples, sampleRate } = await decode(file);
        convert(samples, sampleRate);
      } catch { setMessage(message, "Cannot read this file. Use WAV, MP3, M4A, OGG or FLAC.", "error"); }
    } });
    // The recorder lives outside this panel: a redraw (a take finishing, a focus check) rebuilds the panel,
    // and the new one picks up the running recording instead of losing it.
    const ownRecording = () => performing?.line === line.id;
    let ticker = null;
    const paintRecording = () => {
      if (!ownRecording()) return;
      button.classList.add("on");
      button.setAttribute("aria-label", "Stop");
      ticker = setInterval(() => {
        if (!button.isConnected) return clearInterval(ticker);
        status.textContent = `Recording ${formatTime(performing.recorder.seconds())}`;
        meter.firstChild.style.width = `${Math.min(100, performing.recorder.level() * 100)}%`;
      }, 200);
    };
    const fill = () => microphones().then((devices) => {
      const current = mic.value;
      mic.replaceChildren(...devices.map((d, n) => el("option", { value: d.deviceId }, d.label || `Microphone ${n + 1}`)));
      if (!devices.length) mic.append(el("option", { value: "" }, "Default microphone"));
      if (devices.some((d) => d.deviceId === current)) mic.value = current;
      mic.title = mic.selectedOptions[0]?.textContent || "";  // the full name when it is cut off
    }).catch(() => {});
    button.onclick = async () => {
      if (performing && !ownRecording()) return setMessage(message, "Another line is being recorded. Stop it first.", "warn");
      if (!performing) {
        try { performing = { line: line.id, recorder: await record(mic.value, rememberMicrophone) }; } catch (error) {
          return setMessage(message, `Cannot use the microphone: ${error.message}`, "error");
        }
        fill();
        paintRecording();
        return;
      }
      clearInterval(ticker);
      const { samples, sampleRate } = await performing.recorder.stop();
      performing = null;
      button.classList.remove("on");
      button.setAttribute("aria-label", "Record");
      meter.firstChild.style.width = "0";
      convert(samples, sampleRate);
    };
    async function convert(samples, sampleRate) {
      if (samples.length < sampleRate * 0.3) { status.textContent = "Too short. Record the whole line."; return; }
      status.textContent = "Converting\u2026";
      try {
        const { id } = await api("POST", `/api/sessions/${sid()}/lines/${line.id}/convert`, encodeWav(samples, sampleRate));
        follow({ id, kind: "convert", line: line.id, started: Date.now() / 1000 });
      } catch (error) { fail(error); }
    }
    fill();
    paintRecording();
    const name = castEntry(line.character)?.name || "the character";
    return el("section", { class: "perform" },
      el("h3", {}, "Perform this line"),
      el("div", { class: "muted small" }, `Record it with your own delivery; it becomes a take in ${name}’s voice.`),
      el("div", { class: "row perform-controls" }, button, status, meter,
        el("button", { class: "btn btn-small", onclick: () => fileInput.click() }, "Upload"), fileInput),
      el("label", { class: "row faint small mic-field" }, "Microphone", mic));
  }

  // --- Generation and export -----------------------------------------------------------------

  async function generate(line, names, seedValue) {
    if (!names.length) return setMessage(message, installed().length ? "Choose a model in \u201cGenerate with\u201d." : "Install a model in the Models tab.", "warn");
    await pendingText[line.id]?.(); // typed text that was not saved yet
    try {
      const { id } = await api("POST", `/api/sessions/${sid()}/lines/${line.id}/generate`, { models: names, seed: seedValue || null });
      follow({ id, kind: "generate", line: line.id, started: Date.now() / 1000 });
    } catch (error) { fail(error); }
  }

  // --- Running jobs ----------------------------------------------------------------------------
  // Jobs run on the local server. The screen follows them, and when it is opened again (another tab, another
  // session and back, or a reload) it asks the server which jobs of this session are still running and
  // follows those, so "Generating..." and Stop come back.

  const followed = new Set();
  let exporting = false;

  async function resumeJobs() {
    const owner = session?.id;
    if (!owner) return;
    let running = [];
    try { running = await api("GET", `/api/sessions/${owner}/jobs`); } catch { return; }
    if (session?.id !== owner) return;
    for (const job of running) follow(job);
  }

  async function follow(job) {
    if (followed.has(job.id)) return;
    followed.add(job.id);
    const owner = session.id;
    const mine = () => session?.id === owner; // the user may switch session while it runs
    const number = (lineId) => session.lines.findIndex((l) => l.id === lineId) + 1;
    const takesOf = (lineId) => new Set(session.lines.find((l) => l.id === lineId)?.takes.map((t) => t.file) || []);
    const started = (job.started || Date.now() / 1000) * 1000;
    let current = job.line;
    const before = current ? takesOf(current) : null;
    if (job.kind === "generate" || job.kind === "convert") {
      generating.set(current, started);
      if (job.kind === "generate") lineJobs.set(current, job.id);
      setMessage(message, `${job.kind === "convert" ? "Converting" : "Generating"} line ${number(current)}\u2026`);
    } else if (job.kind === "batch") {
      batch = job.id;
      if (current) generating.set(current, started);
      if (job.progress) setMessage(message, `${job.progress}\u2026`);
    } else if (job.kind === "export") {
      exporting = true;
      setMessage(message, "Exporting\u2026");
    }
    if (main.isConnected) draw();
    let result = null;
    let error = null;
    let last = job.progress || "";
    try {
      result = await waitForJob(job.id, (update) => {
        if (!mine() || job.kind !== "batch") return;
        if (update.line && update.line !== current) { // the batch moved on to the next line
          if (current) generating.delete(current);
          current = update.line;
          generating.set(current, Date.now());
          refresh().catch(() => {});
        }
        if (update.progress && update.progress !== last) { last = update.progress; setMessage(message, `${last}\u2026`); }
      });
    } catch (failure) { error = failure; }
    followed.delete(job.id);
    if (!mine()) return;
    if (job.kind === "export") {
      exporting = false;
      if (error) setMessage(message, error.message, "warn");
      else { setMessage(message, `Exported ${result.split("/").pop()}.`); loadExports(); }
      return;
    }
    if (current) { generating.delete(current); lineJobs.delete(current); }
    if (job.kind === "batch") batch = null;
    if (error?.cancelled) setMessage(message, job.kind === "batch" ? (error.progress || "Stopped.") : `Line ${number(current)} cancelled.`);
    else if (error) fail(error);
    else if (job.kind === "batch") {
      const skipped = result.skipped_empty ? ` Skipped ${plural(result.skipped_empty, "empty line")}.` : "";
      setMessage(message, last.startsWith("Stopped") ? last : `Generated ${plural(result.generated, "line")}.${skipped}`);
    } else {
      setMessage(message, `Line ${number(current)} done.`);
    }
    try { session = await api("GET", `/api/sessions/${owner}`); } catch { return; }
    if (!mine()) return;
    const fresh = current && before && session.lines.find((l) => l.id === current)?.takes.find((t) => !before.has(t.file));
    if (fresh && job.kind !== "batch") justDone = { line: current, file: fresh.file };
    if (main.isConnected) draw();
  }

  async function generateMissing() {
    if (!session.models.length) return setMessage(message, installed().length ? "Choose a model in “Generate with”." : "Install a model in the Models tab.", "warn");
    if (!session.lines.some((l) => !l.takes.length && l.text.trim())) {
      return setMessage(message, session.lines.some((l) => !l.takes.length) ? "The lines without takes are empty." : "Every line already has a take.");
    }
    return runBatch("generate-missing", {});
  }

  async function generatePicked() {
    if (!session.models.length) return setMessage(message, installed().length ? "Choose a model in “Generate with”." : "Install a model in the Models tab.", "warn");
    const ids = session.lines.filter((l) => picked.has(l.id)).map((l) => l.id);
    if (!ids.some((id) => session.lines.find((l) => l.id === id).text.trim())) return setMessage(message, "The selected lines are empty.", "warn");
    return runBatch("generate-lines", { lines: ids });
  }

  async function runBatch(endpoint, body) {
    try {
      for (const id of pendingTextIds()) await pendingText[id]();
      const { id } = await api("POST", `/api/sessions/${sid()}/${endpoint}`, { ...body, seed: seed || null });
      follow({ id, kind: "batch", line: null, started: Date.now() / 1000 });
    } catch (error) { fail(error); }
  }

  const pendingTextIds = () => Object.keys(pendingText);

  // Export is possible once every line has a selected take; it opens a small panel to choose the format.
  function exportButton() {
    const missing = session.lines.map((l, n) => (playableFile(l) ? null : n + 1)).filter(Boolean);
    const ready = session.lines.length && !missing.length;
    const button = el("button", { class: "btn", "aria-haspopup": "dialog", disabled: !ready || exporting,
      title: !session.lines.length ? "Add lines first."
        : missing.length ? `Every line needs a take before exporting. Missing: ${plural(missing.length, "line")} (${missing.join(", ")}).`
          : "Join the selected take of every line, with its pause, into one audio file." }, "Export");
    button.onclick = () => popover(button, exportPanel(), { align: "right" });
    return button;
  }

  // The format panel; with `line`, it exports only that line's selected take (WAV, or a converted copy).
  function exportPanel(line = null, i = 0) {
    let choice = exportFormat;
    const options = exportFormats.length ? exportFormats : [{ id: "wav", label: "WAV", note: "Lossless." }];
    if (!options.some((f) => f.id === choice)) choice = options[0].id;
    return el("div", { class: "menu export-panel" },
      el("strong", {}, line ? `Export line ${i + 1}` : "Export"),
      el("div", { class: "muted small" }, line ? "The selected take of this line, without its pause."
        : `The selected take of all ${plural(session.lines.length, "line")}, with their pauses, in one file.`),
      el("div", { class: "export-options", role: "radiogroup", "aria-label": "File format" },
        options.map((f) => el("label", { class: "export-option" },
          el("input", { type: "radio", name: "export-format", value: f.id, checked: f.id === choice,
            onchange: () => { choice = f.id; } }),
          el("span", { class: "export-format" }, f.label, el("span", { class: "faint" }, ` .${f.id}`)),
          el("span", { class: "muted small" }, f.note)))),
      el("button", { class: "btn btn-primary", onclick: () => {
        document.querySelector(".popover")?.dispatchEvent(new Event("close"));
        exportFormat = choice;
        try { localStorage.setItem("vokalit.exportFormat", choice); } catch { /* storage may be unavailable */ }
        exportSession(choice, line?.id);
      } }, "Export"));
  }

  async function exportSession(fmt, lineId = null) {
    try {
      const { id } = await api("POST", `/api/sessions/${sid()}/export`, { format: fmt, ...(lineId ? { line: lineId } : {}) });
      follow({ id, kind: "export", started: Date.now() / 1000 });
    } catch (error) { setMessage(message, error.message, "warn"); }
  }

  // --- Earlier exports: the newest one in the footer, all of them in a list ------------------

  let exportsList = [];

  async function loadExports() {
    const id = session?.id;
    try { exportsList = await api("GET", `/api/sessions/${id}/exports`); } catch { exportsList = []; }
    if (session?.id === id) paintExports();
  }

  const sizeText = (bytes) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);

  function paintExports() {
    if (!exportsList.length) return exportInfo.replaceChildren();
    const latest = exportsList[0];
    const all = el("button", { class: "btn btn-ghost btn-small", "aria-haspopup": "dialog",
      title: "All exports of this session" }, plural(exportsList.length, "export"), icon(ICONS.chevron, 12));
    all.onclick = () => popover(all, exportsPanel(), { align: "right", up: true });
    exportInfo.replaceChildren(
      player(`/files/${latest.path}`, { buckets: 40, label: "Play the latest export" }),
      el("span", { class: "export-name", title: `Latest export: ${latest.name} (${when(latest.created)})` },
        el("span", { class: "export-label" }, "Latest: "), latest.name),
      revealButton(latest.path),
      el("div", { class: "pop-holder" }, all));
  }

  function exportsPanel() {
    const box = el("div", { class: "menu exports-panel" });
    const paint = () => box.replaceChildren(
      el("strong", {}, "Exports"),
      el("div", { class: "muted small" }, "Files are in this session's exports folder."),
      ...(exportsList.length ? exportsList.map((item) => {
        const remove = el("button", { class: "btn btn-ghost icon-btn", "aria-label": `Delete ${item.name}`, title: "Delete this export" },
          icon(ICONS.trash));
        remove.onclick = () => {
          remove.replaceWith(el("button", { class: "btn btn-danger btn-small", onclick: async () => {
            stopAudio(`/files/${item.path}`);
            try { exportsList = await api("DELETE", `/api/sessions/${sid()}/exports`, { name: item.name }); } catch (error) { fail(error); }
            paintExports();
            paint();
          } }, "Delete"));
        };
        return el("div", { class: "export-item" },
          player(`/files/${item.path}`, { buckets: 30, showTime: false, label: `Play ${item.name}` }),
          el("div", { class: "export-item-text" },
            el("div", { class: "export-item-name", title: item.name }, item.name),
            el("div", { class: "faint small" }, `${item.format.toUpperCase()} \u00b7 ${sizeText(item.size)} \u00b7 ${when(item.created)}`)),
          revealButton(item.path), remove);
      }) : [el("div", { class: "muted small" }, "No exports left.")]));
    paint();
    return box;
  }

  function footer() {
    return el("footer", { class: "main-foot" },
      picked.size ? selectionBar() : transport,
      batch && el("span", { class: "spinner", "aria-hidden": "true" }), message, exportInfo);
  }

  // --- Selecting lines for bulk actions -----------------------------------------------------

  // The tick box left of each row. Shift+click ticks every line between this one and the last one ticked.
  function pickBox(line) {
    return el("input", { type: "checkbox", class: "pick", checked: picked.has(line.id), "aria-label": "Select line",
      title: "Select for bulk actions (Shift+click selects a range, Ctrl+A selects all)",
      onclick: (e) => {
        const ids = session.lines.map((l) => l.id);
        const on = e.target.checked;
        if (e.shiftKey && lastPicked && ids.includes(lastPicked)) {
          const [a, b] = [ids.indexOf(lastPicked), ids.indexOf(line.id)].sort((x, y) => x - y);
          for (const id of ids.slice(a, b + 1)) on ? picked.add(id) : picked.delete(id);
        } else {
          on ? picked.add(line.id) : picked.delete(line.id);
        }
        lastPicked = line.id;
        draw();
      } });
  }

  function clearPicked() { picked.clear(); lastPicked = null; draw(); }

  function selectionBar() {
    const ids = session.lines.filter((l) => picked.has(l.id)).map((l) => l.id);
    const lines = session.lines.filter((l) => picked.has(l.id));
    const characters = new Set(lines.map((l) => l.character));
    const shared = characters.size === 1 ? castEntry([...characters][0]) : null;
    const characterButton = el("button", { class: "btn btn-small", "aria-haspopup": "menu",
      title: "Give the selected lines another speaker" }, "Character", icon(ICONS.chevron, 12));
    characterButton.onclick = () => popover(characterButton, el("div", { class: "menu" },
      session.cast.filter((c) => c.name).map((c) => el("button", { class: "menu-item", onclick: () => bulkUpdate(ids,
        { character: c.character, sample: null }, `${plural(ids.length, "line")} now spoken by ${c.name}.`) },
      avatar(c.character, c.name, 20), c.name))), { up: true });
    const sampleButton = el("button", { class: "btn btn-small", "aria-haspopup": "menu", disabled: !shared?.samples.length,
      title: shared ? "Use another sample of this character for the selected lines" : "Select lines of one character to change their sample" },
    "Sample", icon(ICONS.chevron, 12));
    sampleButton.onclick = () => popover(sampleButton, el("div", { class: "menu" },
      shared.samples.map((sample) => el("button", { class: "menu-item", onclick: () => bulkUpdate(ids,
        { sample: sample.id }, `${plural(ids.length, "line")} now use \u201c${sample.label}\u201d.`) },
      sample.label, sample.id === shared.default_sample && el("span", { class: "faint small" }, "default")))), { up: true });
    const pauses = new Set(lines.map((l) => l.pause_after));
    const pauseButton = el("button", { class: "btn btn-small", "aria-haspopup": "dialog",
      title: "Set the silence after the selected lines in the export" }, "Pause", icon(ICONS.chevron, 12));
    pauseButton.onclick = () => {
      const input = el("input", { class: "input pause", inputmode: "decimal", "aria-label": "Pause after each line in seconds",
        value: pauses.size === 1 ? lines[0].pause_after : "", placeholder: pauses.size === 1 ? "" : "mixed" });
      const set = () => {
        const value = parsePause(input.value);
        if (value === null) return setMessage(message, "Pause must be between 0 and 10 seconds.", "warn");
        bulkUpdate(ids, { pause_after: value }, `${plural(ids.length, "line")} now pause ${value} s.`);
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); set(); } });
      popover(pauseButton, el("div", { class: "menu pause-menu" },
        el("label", { class: "row field" }, "Pause", input, "s"),
        el("button", { class: "btn btn-primary btn-small", onclick: set }, "Set")), { up: true });
      input.focus();
      input.select();
    };
    const takeCount = lines.reduce((n, l) => n + l.takes.length, 0);
    const clearButton = el("button", { class: "btn btn-small", disabled: !takeCount || !!batch,
      title: takeCount ? "Delete every take of the selected lines; the lines stay" : "The selected lines have no takes" },
    "Delete takes");
    clearButton.onclick = () => confirmClearTakes(clearButton, lines, takeCount);
    const deleteButton = el("button", { class: "btn btn-small btn-danger", title: "Delete the selected lines and their takes" }, "Delete lines");
    deleteButton.onclick = () => confirmBulkDelete(deleteButton, ids, "selected");
    return el("div", { class: "selection-bar" },
      el("span", { class: "small selection-count" }, `${plural(ids.length, "line")} selected`),
      el("button", { class: "btn btn-small", disabled: !!batch, onclick: generatePicked,
        title: "Generate a take for each selected line with the models in \u201cGenerate with\u201d" }, "Generate"),
      el("div", { class: "pop-holder" }, characterButton),
      el("div", { class: "pop-holder" }, sampleButton),
      el("div", { class: "pop-holder" }, pauseButton),
      el("div", { class: "pop-holder" }, clearButton),
      el("div", { class: "pop-holder" }, deleteButton),
      el("button", { class: "btn btn-ghost btn-small", onclick: clearPicked, title: "Clear the selection (Esc)" }, "Clear"));
  }

  async function bulkUpdate(ids, fields, done) {
    document.querySelector(".popover")?.dispatchEvent(new Event("close"));
    try {
      apply(await api("POST", `/api/sessions/${sid()}/lines/update`, { lines: ids, fields }));
      setMessage(message, done);
    } catch (error) { fail(error); }
  }

  function confirmClearTakes(anchor, lines, takeCount) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete ${plural(takeCount, "take")} of ${plural(lines.length, "line")}?`),
      el("div", { class: "muted small" }, "The lines and their text stay; the take files are removed permanently. "
        + "This cannot be undone."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        document.querySelector(".popover")?.dispatchEvent(new Event("close"));
        for (const line of lines) for (const take of line.takes) stopAudio(`/files/sessions/${sid()}/${take.file}`);
        if (lines.some((l) => l.id === playback.lineId)) stopAll();
        try {
          const result = await api("POST", `/api/sessions/${sid()}/takes/clear`, { lines: lines.map((l) => l.id) });
          apply(result);
          setMessage(message, `Deleted ${plural(result.removed, "take")}.`);
        } catch (error) { fail(error); }
      } }, `Delete ${plural(takeCount, "take")}`)), { align: "left", up: true });
  }

  function confirmBulkDelete(anchor, ids, kind) {
    const lines = session.lines.filter((l) => ids.includes(l.id));
    const takes = lines.reduce((n, l) => n + l.takes.length, 0);
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete ${plural(lines.length, kind === "empty" ? "empty line" : "line")}?`),
      el("div", { class: "muted small" }, takes
        ? `Their ${plural(takes, "take")} are removed permanently. This cannot be undone.` : "They have no takes."),
      el("button", { class: "btn btn-danger", onclick: async () => {
        document.querySelector(".popover")?.dispatchEvent(new Event("close"));
        if (ids.includes(openLine)) openLine = null;
        try {
          const data = await api("POST", `/api/sessions/${sid()}/lines/delete`, { lines: ids });
          for (const id of ids) picked.delete(id);
          apply(data);
          if (!data.notice) setMessage(message, `Deleted ${plural(lines.length, "line")}.`);
        } catch (error) { fail(error); }
      } }, `Delete ${plural(lines.length, "line")}`)), { align: "left", up: anchor.closest("footer") !== null });
  }

  // Ctrl+A selects every line and Esc clears the selection, unless you are typing.
  function selectionKeys(e) {
    if (e.target.closest?.("input:not([type=checkbox]), textarea, select, [contenteditable]") || !session) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      for (const line of session.lines) picked.add(line.id);
      draw();
    } else if (e.key === "Escape" && picked.size && !e.defaultPrevented && !document.querySelector(".popover")) {
      clearPicked();
    }
  }
  document.addEventListener("keydown", selectionKeys);

  // --- Play all: the selected takes in order, with each line's pause between them ------------

  const playback = { lineId: null, audio: null, timer: null, resumeAt: null, paused: false };
  const transport = el("div", { class: "transport" });
  const clock = el("span", { class: "num faint small transport-clock" });
  const lineIndex = (id) => session ? session.lines.findIndex((l) => l.id === id) : -1;

  function stopAll() {
    playback.audio?.pause();
    clearTimeout(playback.timer);
    Object.assign(playback, { lineId: null, audio: null, timer: null, resumeAt: null, paused: false });
    paintTransport();
  }

  // Plays the first line with a take at or after `from` (or before it, with step -1).
  function playAt(from, step = 1) {
    playback.audio?.pause();
    clearTimeout(playback.timer);
    playback.resumeAt = null;
    const { index, skipped } = findPlayable(session.lines.map((l) => ({ selected: playableFile(l) })), from, step);
    if (skipped.length) {
      const numbers = (step > 0 ? skipped : [...skipped].reverse()).map((n) => n + 1);
      setMessage(message, `Skipped ${numbers.length > 1 ? "lines" : "line"} ${numbers.join(", ")}: no take yet.`, "warn");
    }
    if (index < 0) {
      if (!skipped.length || step < 0) setMessage(message, step > 0 ? "Reached the end of the script." : "");
      stopAll();
      return;
    }
    const line = session.lines[index];
    pauseAll();
    const audio = new Audio(`/files/sessions/${sid()}/${playableFile(line)}`);
    Object.assign(playback, { lineId: line.id, audio, paused: false });
    audio.addEventListener("ended", () => {
      // Silence for the line's pause, then the next line (looked up again: the script may have changed).
      playback.timer = setTimeout(() => playAt(lineIndex(line.id) + 1), line.pause_after * 1000);
      playback.resumeAt = line.id;
    });
    audio.play().catch(fail);
    paintTransport();
    main.querySelector(`.line[data-line="${line.id}"], .line-details[data-line="${line.id}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function playFrom(index) { playAt(index); }

  function togglePlay() {
    if (!session) return;
    if (!playback.lineId) return playAt(0);
    if (playback.resumeAt) { // paused or waiting in the gap after a line
      const after = lineIndex(playback.resumeAt);
      if (playback.timer && !playback.paused) { clearTimeout(playback.timer); playback.timer = null; playback.paused = true; return paintTransport(); }
      playback.paused = false;
      return playAt(after + 1);
    }
    if (playback.audio.paused) { pauseAll(); playback.audio.play(); playback.paused = false; } else { playback.audio.pause(); playback.paused = true; }
    paintTransport();
  }

  function step(delta) {
    if (!session) return;
    const at = playback.lineId ? lineIndex(playback.lineId) : -1;
    playAt(Math.max(0, at + delta), delta);
  }

  function paintClock() {
    const a = playback.audio;
    clock.textContent = a && !playback.resumeAt ? `${formatTime(a.currentTime || 0)} / ${formatTime(a.duration || 0)}` : "";
  }

  function paintTransport() {
    const at = playback.lineId ? lineIndex(playback.lineId) : -1;
    const isPlaying = playback.lineId && !playback.paused;
    const line = at >= 0 ? session.lines[at] : null;
    const playable = session?.lines.some((l) => playableFile(l));
    transport.replaceChildren(
      el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Previous line", title: "Previous line",
        disabled: !playable, onclick: () => step(-1) }, icon(ICON_PREV, 14)),
      el("button", { class: "btn icon-btn transport-play", "aria-label": isPlaying ? "Pause" : playback.lineId ? "Resume" : "Play all",
        title: isPlaying ? "Pause (Space)" : "Play all lines in order, with their pauses (Space)", disabled: !playable,
        onclick: togglePlay }, icon(isPlaying ? ICONS.pause : ICONS.play, 14)),
      el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Next line", title: "Next line",
        disabled: !playable, onclick: () => step(1) }, icon(ICON_NEXT, 14)),
      el("span", { class: "small transport-label" }, line
        ? `Line ${at + 1}/${session.lines.length} \u00b7 ${line.character_name || "Deleted character"}`
        : playable ? "Play all" : ""),
      clock);
    for (const node of main.querySelectorAll("[data-line]")) {
      node.classList.toggle("now-playing", node.dataset.line === playback.lineId);
    }
    paintClock();
  }

  // Space plays/pauses, unless you are typing or on a control.
  function spaceToggle(e) {
    if (e.key !== " " || e.target.closest?.("input, textarea, select, button, [contenteditable]")) return;
    e.preventDefault();
    togglePlay();
  }
  document.addEventListener("keydown", spaceToggle);
  // Playing a single take pauses "Play all" (it can be resumed).
  const onPlayerPlay = () => { if (playback.lineId && !playback.paused) togglePlay(); };
  document.addEventListener("vokalit-player-play", onPlayerPlay);

  // --- Routing -------------------------------------------------------------------------------

  const onHash = () => {
    if (!root.isConnected || !(location.hash.startsWith("#/studio") || location.hash === "" || location.hash === "#/")) {
      window.removeEventListener("hashchange", onHash);
      return;
    }
    load().catch(fail);
  };
  window.addEventListener("hashchange", onHash);
  await load().catch(fail);
}
