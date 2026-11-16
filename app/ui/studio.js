// Studio screen: sessions, cast, script lines with takes, generation, export.
import { api, editableTitle, el, icon, ICONS, revealButton, setMessage, waitForJob } from "./app.js";
import { decode, encodeWav, microphones, record } from "./audio.js";
import { avatar, characterColors, samplePanel } from "./characters.js";
import { commonLanguages, findPlayable, formatTime, moveLine, settingsChanges, splitSentences, takeNumber } from "./script.js";
import { dot, modelColor, modelPicker, modelTabs, popover, sliders } from "./settings.js";
import { pauseAll, player, stopAudio } from "./waveform.js";

const ICON_MORE = ["M5 12h.01M12 12h.01M19 12h.01"];
const ICON_PREV = ["M18 6l-8 6 8 6z", "M6 6v12"];
const ICON_NEXT = ["M6 6l8 6-8 6z", "M18 6v12"];
const ICON_SLIDERS = ["M4 7h10M18 7h2M4 17h4M12 17h8M14 5v4M8 15v4"];

// Lines longer than this get a note and a "Split" action: models work best with sentence-sized lines.
const LONG_LINE = 300;
const TIP_MODELS = "Models to generate with: each one makes its own take, so you can compare them.";
const TIP_SEED = "The same seed, text, sample and settings give the same audio. Leave empty for a new random seed each time.";
const SPLIT_SIZE = 250;
const ICON_OPEN = ["M6 9l6 6 6-6"]; // chevron down: open the line
const ICON_CLOSE = ["M6 15l6-6 6 6"]; // chevron up: close it

const textRows = (text) => Math.min(10, Math.max(2, Math.ceil(text.length / 140) + (text.match(/\n/g) || []).length));
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
  const picked = new Set(); // lines ticked for bulk actions
  let lastPicked = null; // anchor for Shift+click ranges
  let justClosed = null; // the row that replaces closed details fades in
  let editing = null; // session-only character whose samples are open
  let seed = "";
  let batch = null;
  let pasting = false;
  let dragging = null;
  const generating = new Map(); // line id -> start time, for the spinner and elapsed seconds
  const pendingText = {}; // line id -> saves typed text not yet sent (the Generate button waits for it)
  // Elapsed time next to every spinner; one ticker for the whole screen.
  const ticker = setInterval(() => {
    if (!main.isConnected) { stopAll(); clearInterval(ticker); document.removeEventListener("keydown", spaceToggle);
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
  const defaults = (name) => Object.fromEntries((modelInfo(name)?.settings || []).map((s) => [s.key, s.default]));
  const sessionValues = (name) => ({ ...defaults(name), ...(session.settings[name] || {}) });
  const languageName = (code) =>
    models.flatMap((m) => m.languages).find((l) => l.code === code)?.name || code;
  const lineLanguage = (line) => line.language || session.language;
  const castEntry = (id) => session.cast.find((c) => c.character === id);
  const fail = (error) => setMessage(message, error.message, "error");
  const sid = () => session.id;
  const selectedId = () => (location.hash.match(/^#\/studio\/([0-9-]+)/) || [])[1] || sessions[0]?.id;

  function sampleOf(line) {
    const entry = castEntry(line.character);
    if (!entry || !entry.samples.length) return null;
    return entry.samples.find((s) => s.id === line.sample) || entry.samples.find((s) => s.id === entry.default_sample);
  }

  // Language choices are the languages every chosen model supports. `inherit` adds a "Session (...)" option.
  function languageSelect(names, value, onChange, inherit = null, small = false) {
    const options = commonLanguages(models, names);
    const select = el("select", { class: `select language-select ${small ? "select-small" : ""}`, "aria-label": "Language", onchange: () => onChange(select.value || null) },
      inherit && el("option", { value: "" }, `Session (${languageName(inherit)})`),
      options.map((l) => el("option", { value: l.code }, l.name)));
    if (value && !options.some((l) => l.code === value)) {
      select.append(el("option", { value }, `${languageName(value)} (not supported)`));
    }
    select.value = value || "";
    return select;
  }

  // --- Loading -------------------------------------------------------------------------------

  async function load() {
    [sessions, models, library] = await Promise.all([api("GET", "/api/sessions"), api("GET", "/api/models"),
      api("GET", "/api/characters")]);
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
    try {
      session = await api("GET", `/api/sessions/${id}`);
    } catch {
      main.replaceChildren(el("div", { class: "empty" }, el("p", {}, "This session no longer exists.")));
      return;
    }
    draw();
  }

  async function refresh() {
    session = await api("GET", `/api/sessions/${sid()}`);
    draw();
  }

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
    list.replaceChildren(...sessions.filter((s) => s.name.toLowerCase().includes(term)).map((s) => el("a", {
      class: "list-item", href: `#/studio/${s.id}`, "aria-current": s.id === current ? "true" : "false" },
    el("div", { class: "name" }, s.name),
    el("div", { class: "sub" }, `${plural(s.lines, "line")} · ${when(s.created)}`))));
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
    main.replaceChildren(header(), cast(), el("div", { class: "main-body" }, script()), footer());
    main.querySelector(".main-body").scrollTop = scroll;
    paintTransport();
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
      el("button", { class: "btn", onclick: exportSession,
        title: "Joins the selected take of every line, with its pause, into one WAV file." }, "Export"),
      batch
        ? el("button", { class: "btn btn-primary", onclick: () => api("POST", `/api/sessions/${sid()}/stop`, {}).catch(fail) }, "Stop")
        : el("button", { class: "btn btn-primary", onclick: generateMissing,
          title: "Generates every line that has no take yet, top to bottom." }, "Generate missing"),
      el("div", { class: "pop-holder" }, more));
  }

  function confirmDeleteSession(anchor) {
    popover(anchor, el("div", { class: "menu confirm-menu" },
      el("strong", {}, `Delete “${session.name}”?`),
      el("div", { class: "muted small" }, "Its lines, takes, recordings and session-only characters are removed permanently."),
      el("div", { class: "row" },
        el("button", { class: "btn btn-danger", onclick: async () => {
          await api("DELETE", `/api/sessions/${sid()}`).catch(fail);
          session = null;
          location.hash = "#/studio";
          load();
        } }, "Delete session"))), { align: "right" });
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
              .then((data) => { session = data; paint(); }, fail)),
          el("div", { class: "row settings-foot" },
            el("div", { class: "muted small" }, "Default for every line in this session. Lines can override them."),
            el("div", { class: "spacer" }),
            el("button", { class: "btn btn-small", disabled: !session.settings[name], onclick: () =>
              api("DELETE", `/api/sessions/${sid()}/settings/${name}`).then((data) => { session = data; paint(); }, fail) },
            "Reset to model defaults")));
      }));
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
    if (!editing || !castEntry(editing)) return section;
    return el("div", {}, section, sessionCharacterEditor(castEntry(editing)));
  }

  function chip(entry) {
    const sessionOnly = entry.scope === "session";
    const deleted = entry.name === null;
    const label = deleted ? "Deleted character" : entry.name;
    const meta = deleted ? "" : sessionOnly ? "this session"
      : entry.samples.length ? plural(entry.samples.length, "sample") : "default voice";
    const nameNode = deleted ? el("span", { class: "warn" }, label)
      : sessionOnly ? el("button", { class: "link-btn", title: "Edit samples", onclick: () => { editing = editing === entry.character ? null : entry.character; draw(); } }, label)
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

  function sessionCharacterEditor(entry) {
    const name = el("input", { class: "input", value: entry.name, "aria-label": "Character name", onchange: () => {
      const value = name.value.trim();
      if (!value) { name.value = entry.name; return; }
      api("PATCH", `/api/characters/${entry.character}?session=${sid()}`, { name: value }).then(refresh, fail);
    } });
    let first = true;
    return el("div", { class: "cast-editor" },
      el("div", { class: "row" }, avatar(entry.character, entry.name, 24), name,
        el("span", { class: "muted small" }, "Only in this session. Save to library to reuse it elsewhere."),
        el("div", { class: "spacer" }),
        el("button", { class: "btn btn-ghost icon-btn", "aria-label": "Close", onclick: () => { editing = null; draw(); } }, icon(ICONS.close))),
      samplePanel(null, entry.character, sid(), async () => {
        if (first) { first = false; return; }
        session = await api("GET", `/api/sessions/${sid()}`); // keep the panel; chips update on the next redraw
      }));
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
      right.append(busyLabel(line.id, "Generating…"));
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
      + `${playback.lineId === line.id ? "now-playing" : ""}`,
      "data-line": line.id,
      title: "Click to edit the line and its takes" },
    pickBox(line), handle(line), speaker(line),
    el("div", { class: "line-body" },
      el("div", { class: `line-text ${line.text ? "" : "faint"}` }, line.text || "Empty line \u2014 click to write it"),
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
      main.querySelector(".line-details textarea")?.focus();
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
    const text = el("textarea", { class: "textarea line-input", rows: textRows(line.text), "aria-label": "Line text", value: line.text,
      oninput: () => { clearTimeout(typing); pendingText[line.id] = saveText; typing = setTimeout(saveText, 600); },
      onchange: saveText });
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
    const count = picker.get().length;
    const busy = generating.has(line.id);
    const deleteButton = el("button", { class: "btn btn-ghost icon-btn", "aria-label": `Delete line ${i + 1}`, title: "Delete line" },
      icon(ICONS.trash));
    deleteButton.onclick = () => confirmDeleteLine(deleteButton, line, i);
    const generateButton = el("button", { class: "btn btn-primary", disabled: busy || !count || !line.text.trim(),
      title: line.text.trim() ? "" : "Write the line first",
      onclick: () => generate(line, picker.get(), lineSeeds[line.id] ?? seed) },
    busy ? busyLabel(line.id, "Generating\u2026") : `Generate ${plural(count || 0, "take")}`);
    text.addEventListener("input", () => {
      generateButton.disabled = busy || !count || !text.value.trim();
      generateButton.title = text.value.trim() ? "" : "Write the line first";
      text.rows = textRows(text.value);
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
    const counter = el("span", { class: "faint small num" }, `${line.text.length} characters`);
    text.addEventListener("input", () => { counter.textContent = `${text.value.length} characters`; });
    const head = el("div", { class: "detail-head", title: "Click an empty spot to close" },
      handle(line),
      el("label", { class: "row field", title: "Who speaks this line. Only characters in the cast are listed." },
        dot(characterColors(line.character)[0], 8), "Character", characterSelect),
      el("label", { class: "row field", title: "Which recording of the voice to clone. Samples recorded in different moods steer "
        + "the delivery. Without samples the model's default voice is used." }, "Sample", sampleSelect),
      el("label", { class: "row field", title: "The language the text is read in. \u201cSession\u201d follows the session's "
        + "language; only languages every selected model supports are listed." }, "Language",
        languageSelect(picker.get(), line.language, (code) => patch({ language: code }), session.language, true)),
      el("label", { class: "row field", title: "Silence after this line in the export, in seconds." }, "Pause", pause, "s"),
      el("div", { class: "spacer" }),
      el("div", { class: "pop-holder" }, deleteButton),
      el("button", { class: "btn btn-ghost icon-btn close-details", "aria-label": "Close details", title: "Close (Esc)", onclick: close },
        icon(ICON_CLOSE, 16)));
    head.addEventListener("click", (e) => { if (e.target === head || e.target.classList.contains("spacer")) close(); });
    const node = el("div", { class: "line-details", "data-line": line.id,
      onkeydown: (e) => { if (e.key === "Escape" && !e.target.closest(".popover")) { e.preventDefault(); close(); } } },
      head,
      el("div", { class: "detail-text" }, text, el("div", { class: "row" }, el("div", { class: "spacer" }), counter)),
      el("div", { class: "detail-row row wrap" },
        el("div", { class: "muted", title: TIP_MODELS }, "Generate with"), picker.element,
        el("label", { class: "row muted", title: TIP_SEED }, "Seed", lineSeed),
        generateButton,
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
      box.replaceChildren(
        el("span", { class: "warn" }, `This line is long (${value.length} characters). Models work best with a sentence or two; `
          + "very long lines can be cut off or drift."),
        parts.length > 1 && el("button", { class: "btn btn-small", onclick: async () => {
          await pendingText[line.id]?.();
          splitLine(line, splitSentences(textBox.value, SPLIT_SIZE));
        } }, `Split into ${parts.length} lines`));
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

  // Warns when a chosen model cannot speak the line's language, or the sample is in another language.
  function languageNotes(line, names) {
    const language = lineLanguage(line);
    const notes = [];
    for (const name of names) {
      const info = modelInfo(name);
      if (info && !info.languages.some((l) => l.code === language)) {
        notes.push(el("div", { class: "warn small" }, `${info.title} does not support ${languageName(language)}.`));
      }
    }
    const sample = sampleOf(line);
    if (sample?.language && sample.language !== language) {
      const fixes = names.map(modelInfo).filter((info) => info?.accent_setting).filter((info) => {
        const { key, value } = info.accent_setting;
        return ({ ...sessionValues(info.name), ...(line.settings[info.name] || {}) })[key] !== value;
      });
      notes.push(el("div", { class: "row small wrap" },
        el("span", { class: "warn" }, `The sample \u201c${sample.label}\u201d is ${languageName(sample.language)} and the line is `
          + `${languageName(language)}, so the voice may keep a ${languageName(sample.language)} accent.`),
        fixes.map((info) => el("button", { class: "btn btn-small", onclick: () => {
          const { key, value } = info.accent_setting;
          const label = info.settings.find((x) => x.key === key)?.label || key;
          api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${info.name}`, { ...(line.settings[info.name] || {}), [key]: value })
            .then((data) => { apply(data); setMessage(message, `${label} set to ${value} for this line.`); }, fail);
        } }, `Reduce accent (${titles()[info.name]})`))));
    }
    return notes.length ? el("div", { class: "detail-row language-notes" }, notes) : null;
  }

  function lineSettings(line, names) {
    if (!names.length) return null;
    const changes = names.reduce((n, name) => n + settingsChanges(line.settings[name], sessionValues(name)).length, 0);
    return el("section", { class: "detail-row line-settings", "aria-label": "Line settings" },
      el("div", { class: "row" },
        el("h3", {}, "Settings for this line"),
        el("div", { class: `small ${changes ? "accent" : "faint"}` },
          changes ? `${plural(changes, "change")} from session settings` : "Same as session settings"),
        el("div", { class: "spacer" }),
        el("button", { class: "btn btn-small", disabled: !Object.keys(line.settings).length, onclick: () =>
          api("DELETE", `/api/sessions/${sid()}/lines/${line.id}/settings`).then(apply, fail),
          title: "Forget this line's own settings and use the session's." }, "Reset to session settings")),
      modelTabs(names, titles(), (name) => {
        const base = sessionValues(name);
        const values = { ...base, ...(line.settings[name] || {}) };
        return sliders(modelInfo(name)?.settings || [], values, base,
          (spec, value, baseValue) => (value === baseValue ? "Same as session" : `Session: ${Number(baseValue).toFixed(2)}`),
          (key, value) => {
            const overrides = { ...(line.settings[name] || {}), [key]: value };
            if (value === base[key]) delete overrides[key];
            api("PUT", `/api/sessions/${sid()}/lines/${line.id}/settings/${name}`, overrides).then(apply, fail);
          });
      }));
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
    const rowNode = el("div", { class: "take" },
      el("input", { type: "radio", name: `take-${line.id}`, checked: isSelected, "aria-label": `Use take ${takeNumber(take.file)}`,
        title: "The selected take is the one used in the export.",
        onchange: () => api("POST", `/api/sessions/${sid()}/lines/${line.id}/takes/select`, { file: take.file }).then(apply, fail) }),
      player(`/files/sessions/${sid()}/${take.file}`, { buckets: 60, showTime: false, selected: isSelected }),
      el("div", { class: "take-info" },
        el("div", { class: "row" }, dot(modelColor(take.model)), el("span", {}, model),
          el("span", { class: "muted" }, `· take ${takeNumber(take.file) ?? "?"}`)),
        el("div", { class: "faint small" }, meta,
          take.custom_settings && [" · ", el("span", { class: "accent", title: "Generated with settings that differ from the session's current ones." }, "custom settings")],
          take.text_changed && [" · ", el("span", { class: "warn", title: `The line's text changed after this take. The take says: \u201c${take.text}\u201d` }, "text changed")])),
      !converted && take.settings && el("button", { class: "btn btn-small btn-ghost", title: "Copy this take's seed and settings to the line",
        onclick: () => useSettings(line, take) }, "Use these settings") || el("span"),
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
    const mic = el("select", { class: "select select-small", "aria-label": "Microphone" });
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
    let recorder = null;
    let ticker = null;
    const fill = () => microphones().then((devices) => {
      const current = mic.value;
      mic.replaceChildren(...devices.map((d, n) => el("option", { value: d.deviceId }, d.label || `Microphone ${n + 1}`)));
      if (!devices.length) mic.append(el("option", { value: "" }, "Default microphone"));
      if (devices.some((d) => d.deviceId === current)) mic.value = current;
    }).catch(() => {});
    button.onclick = async () => {
      if (!recorder) {
        try { recorder = await record(mic.value); } catch (error) { return setMessage(message, `Cannot use the microphone: ${error.message}`, "error"); }
        fill();
        button.classList.add("on");
        button.setAttribute("aria-label", "Stop");
        ticker = setInterval(() => {
          status.textContent = `Recording ${formatTime(recorder.seconds())}`;
          meter.firstChild.style.width = `${Math.min(100, recorder.level() * 100)}%`;
        }, 200);
        return;
      }
      clearInterval(ticker);
      const { samples, sampleRate } = await recorder.stop();
      recorder = null;
      button.classList.remove("on");
      button.setAttribute("aria-label", "Record");
      meter.firstChild.style.width = "0";
      convert(samples, sampleRate);
    };
    async function convert(samples, sampleRate) {
      if (samples.length < sampleRate * 0.3) { status.textContent = "Too short. Record the whole line."; return; }
      status.textContent = "Converting…";
      generating.set(line.id, Date.now());
      try {
        const { id } = await api("POST", `/api/sessions/${sid()}/lines/${line.id}/convert`, encodeWav(samples, sampleRate));
        await waitForJob(id);
      } catch (error) { fail(error); }
      generating.delete(line.id);
      await refresh();
    }
    fill();
    const name = castEntry(line.character)?.name || "the character";
    return el("section", { class: "perform" },
      el("h3", {}, "Perform this line"),
      el("div", { class: "muted small" }, `Record it with your own delivery; it becomes a take in ${name}’s voice.`),
      el("div", { class: "row perform-controls" }, button, status, meter,
        el("button", { class: "btn btn-small", onclick: () => fileInput.click() }, "Upload"), fileInput),
      el("label", { class: "row faint small" }, "Microphone", mic));
  }

  // --- Generation and export -----------------------------------------------------------------

  async function generate(line, names, seedValue) {
    if (!names.length) return setMessage(message, installed().length ? "Choose a model in “Generate with”." : "Install a model in the Models tab.", "warn");
    const number = session.lines.findIndex((l) => l.id === line.id) + 1;
    await pendingText[line.id]?.(); // typed text that was not saved yet
    generating.set(line.id, Date.now());
    draw();
    setMessage(message, `Generating line ${number}…`);
    try {
      const { id } = await api("POST", `/api/sessions/${sid()}/lines/${line.id}/generate`, { models: names, seed: seedValue || null });
      await waitForJob(id);
      setMessage(message, `Line ${number} done.`);
    } catch (error) { fail(error); }
    generating.delete(line.id);
    if (session?.id) await refresh();
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
      batch = id;
      draw();
      let last = "";
      const result = await waitForJob(id, (job) => {
        if (job.progress && job.progress !== last) {
          last = job.progress;
          setMessage(message, `${job.progress}…`);
          refresh();
        }
      });
      const skipped = result.skipped_empty ? ` Skipped ${plural(result.skipped_empty, "empty line")}.` : "";
      setMessage(message, last.startsWith("Stopped") ? last : `Generated ${plural(result.generated, "line")}.${skipped}`);
    } catch (error) { fail(error); }
    batch = null;
    await refresh();
  }

  const pendingTextIds = () => Object.keys(pendingText);

  async function exportSession() {
    setMessage(message, "Exporting…");
    try {
      const { id } = await api("POST", `/api/sessions/${sid()}/export`, {});
      const file = await waitForJob(id);
      const url = `/files/${file}`;
      const name = file.split("/").pop();
      setMessage(message, "");
      exportInfo.replaceChildren(el("span", { class: "muted" }, `Last export: ${name}`),
        player(url, { buckets: 40 }),
        el("a", { href: url, download: name }, "Download"),
        revealButton(file, { text: true }));
    } catch (error) { setMessage(message, error.message, "warn"); }
  }

  function footer() {
    return el("footer", { class: "main-foot" },
      picked.size ? selectionBar() : transport,
      batch && el("span", { class: "spinner", "aria-hidden": "true" }), message, el("div", { class: "spacer" }), exportInfo);
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
    const deleteButton = el("button", { class: "btn btn-small btn-danger", title: "Delete the selected lines and their takes" }, "Delete");
    deleteButton.onclick = () => confirmBulkDelete(deleteButton, ids, "selected");
    return el("div", { class: "selection-bar" },
      el("span", { class: "small selection-count" }, `${plural(ids.length, "line")} selected`),
      el("button", { class: "btn btn-small", disabled: !!batch, onclick: generatePicked,
        title: "Generate a take for each selected line with the models in \u201cGenerate with\u201d" }, "Generate"),
      el("div", { class: "pop-holder" }, characterButton),
      el("div", { class: "pop-holder" }, sampleButton),
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
    const { index, skipped } = findPlayable(session.lines, from, step);
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
    const audio = new Audio(`/files/sessions/${sid()}/${line.selected}`);
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
    const playable = session?.lines.some((l) => l.selected);
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
