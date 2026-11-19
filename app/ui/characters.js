// Characters screen: library list, rename, delete, and the samples panel (also used by Studio).
import { api, editableTitle, el, icon, ICONS, rememberMicrophone, revealButton, setMessage, waitForJob } from "./app.js";
import { decode, encodeWav, microphones, record, trim } from "./audio.js";
import { designLanguage, designText, isCut } from "./script.js";
import { searchSelect } from "./settings.js";
import { player, rangeEditor, stopAudio } from "./waveform.js";

const MIN_SECONDS = 10;
const COLORS = [["#7aa2f7", "#1b2436"], ["#bb9af7", "#2a2038"], ["#e5c07b", "#2e2716"], ["#6fbf8a", "#17291f"],
  ["#e5807a", "#33201f"], ["#7dcfff", "#162a33"]];

// [color, tint] for a character, stable for its ID.
export function characterColors(id) {
  const hash = [...id].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7);
  return COLORS[hash % COLORS.length];
}

export function avatar(id, name, size = 28) {
  const [color, tint] = characterColors(id);
  return el("div", { class: "avatar", style: { width: `${size}px`, height: `${size}px`, color, background: tint } },
    (name.trim()[0] || "?").toUpperCase());
}

// Every language any model supports, for tagging samples (fetched once).
let allLanguages = null;
function languages() {
  allLanguages ||= api("GET", "/api/models").then((list) => {
    const byCode = new Map(list.flatMap((m) => m.languages).map((l) => [l.code, l]));
    return [...byCode.values()].sort((a, b) => a.name.localeCompare(b.name));
  }).catch(() => []);
  return allLanguages;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const query = (sessionId) => (sessionId ? `?session=${encodeURIComponent(sessionId)}` : "");

export function sampleUrl(charId, file, sessionId) {
  const base = sessionId ? `sessions/${sessionId}/characters/${charId}` : `characters/${charId}`;
  return `/files/${base}/${file}`;
}

export async function renderCharacters(root) {
  const list = el("div", { class: "list" });
  const main = el("div", { class: "main" });
  root.append(
    el("aside", { class: "sidebar" },
      el("div", { class: "sidebar-head" },
        el("h2", {}, "Characters"),
        el("button", { class: "btn icon-btn", title: "New character", "aria-label": "New character", onclick: create },
          icon(ICONS.plus))),
      list),
    main);

  let characters = [];
  const selectedId = () => (location.hash.match(/^#\/characters\/([0-9-]+)/) || [])[1] || characters[0]?.id;

  async function refreshList() {
    characters = await api("GET", "/api/characters");
    const current = selectedId();
    list.replaceChildren(...characters.map((c) => el("a", {
      class: "list-item character-item", href: `#/characters/${c.id}`, "aria-current": c.id === current ? "true" : "false",
    },
    avatar(c.id, c.name),
    el("div", {},
      el("div", { class: "name" }, c.name),
      el("div", { class: "sub" }, c.samples.length
        ? `${plural(c.samples.length, "sample")} · ${plural(c.used_in.length, "session")}`
        : "No samples · default voice")))));
    if (!characters.length) list.append(el("p", { class: "muted small pad" }, "No characters yet."));
  }

  async function showSelected() {
    const id = selectedId();
    main.replaceChildren();
    if (!id) {
      main.append(el("div", { class: "empty" }, el("h1", {}, "No characters yet"),
        el("p", {}, "A character is a voice you can reuse across sessions."),
        el("button", { class: "btn btn-primary", onclick: create }, "New character")));
      return;
    }
    const character = characters.find((c) => c.id === id);
    if (!character) {
      main.append(el("div", { class: "empty" }, el("p", {}, "This character no longer exists.")));
      return;
    }
    main.append(header(character), el("div", { class: "main-body" }, samplePanel(null, id, null, refreshList)));
  }

  function header(character) {
    const message = el("div", { class: "message" });
    const name = el("input", { class: "title-input", value: character.name, "aria-label": "Character name",
      onchange: async () => {
        const value = name.value.trim();
        if (!value) { name.value = character.name; return; }
        try {
          await api("PATCH", `/api/characters/${character.id}`, { name: value });
          character.name = value;
          badge.replaceWith(badge = avatar(character.id, value, 32));
          await refreshList();
        } catch (error) { setMessage(message, error.message, "error"); }
      } });
    let badge = avatar(character.id, character.name, 32);
    const head = el("header", { class: "main-head" },
      badge, editableTitle(name),
      el("div", { class: "muted small" }, character.used_in.length ? `Used in ${character.used_in.join(", ")}` : "Not used in any session"),
      el("div", { class: "spacer" }), message,
      el("button", { class: "btn btn-danger", onclick: () => confirmDelete(head, character) }, "Delete character"));
    return head;
  }

  function confirmDelete(head, character) {
    head.parentNode.querySelector(".confirm")?.remove();
    const box = el("div", { class: "confirm confirm-bar" },
      el("strong", {}, `Delete ${character.name}?`),
      el("div", { class: "muted" }, character.used_in.length
        ? `Its samples are removed permanently. Used in ${character.used_in.join(", ")}: those lines keep their takes, but need another character to generate.`
        : "Its samples are removed permanently."),
      el("div", { class: "row" },
        el("button", { class: "btn btn-danger", onclick: async () => {
          await api("DELETE", `/api/characters/${character.id}`);
          location.hash = "#/characters";
          await refreshList();
          showSelected();
        } }, "Delete"),
        el("button", { class: "btn btn-ghost", onclick: () => box.remove() }, "Cancel")));
    head.after(box);
  }

  async function create() {
    const character = await api("POST", "/api/characters", { name: "New character" });
    location.hash = `#/characters/${character.id}`;
    await refreshList();
    await showSelected();
    main.querySelector(".title-input")?.select();
  }

  const onHash = async () => {
    if (!location.hash.startsWith("#/characters") || !root.isConnected) {
      window.removeEventListener("hashchange", onHash);
      return;
    }
    await refreshList();
    showSelected();
  };
  window.addEventListener("hashchange", onHash);
  // Sample counts in the list follow files deleted in File Explorer (the server drops them on read).
  const onFocus = () => {
    if (!root.isConnected) return window.removeEventListener("focus", onFocus);
    refreshList().catch(() => {});
  };
  window.addEventListener("focus", onFocus);
  await refreshList();
  showSelected();
}

// Samples table + "Add a sample". container may be null (a new element is returned).
export function samplePanel(container, charId, sessionId, onChange = () => {}) {
  const root = container || el("div");
  root.classList.add("samples");
  const message = el("div", { class: "message" });
  const table = el("div");
  const adder = addSample();
  root.replaceChildren(
    el("div", { class: "section-head" }, el("h2", {}, "Samples"),
      el("span", { class: "muted small" }, "Lines pick one sample. Record the same voice in different moods to steer delivery."),
      el("div", { class: "spacer" }), message),
    table, adder);

  const path = (suffix = "") => `/api/characters/${charId}${suffix}${query(sessionId)}`;
  const fail = (error) => setMessage(message, error.message, "error");
  // Whisper writes transcripts; without it they are typed. Checked when the panel opens.
  const whisper = api("GET", "/api/components")
    .then(({ items }) => Boolean(items.find((c) => c.name === "whisper")?.installed)).catch(() => false);

  let shown = null;
  async function refresh(data) {
    const character = data || await api("GET", path());
    if (!data && JSON.stringify(character) === shown) return; // focus check: nothing changed
    shown = JSON.stringify(character);
    draw(character);
    onChange(character);
    // Whisper is writing transcripts in the background: look again shortly.
    if (character.samples.some((s) => s.transcribing)) setTimeout(() => root.isConnected && refresh().catch(() => {}), 2000);
  }

  // Coming back to the window (e.g. after deleting a file in File Explorer) reloads the character; the server
  // drops samples whose file is gone.
  const onFocus = () => {
    if (!root.isConnected) return window.removeEventListener("focus", onFocus);
    if (root.querySelector(".review-box, .confirm") || root.querySelector(".record-btn.recording")) return;
    refresh().catch(() => {});
  };
  window.addEventListener("focus", onFocus);

  function draw(character) {
    if (!character.samples.length) {
      table.replaceChildren(el("p", { class: "muted" }, "No samples yet. Without one, the model's default voice is used."));
      return;
    }
    table.replaceChildren(
      el("div", { class: "table-head sample-grid" }, el("div"), el("div"), el("div", {}, "Label"), el("div", {}, "Language"),
        el("div", {}, "Waveform"),
        el("div", {}, "Length"), el("div")),
      ...character.samples.map((sample) => sampleRow(character, sample)));
  }

  function sampleRow(character, sample) {
    const isDefault = sample.id === character.default_sample;
    const row = el("div", { class: "table-row sample-grid" });
    const label = el("input", { class: "input", value: sample.label, "aria-label": "Sample label",
      title: "A name for this sample, e.g. calm or excited. Lines pick samples by this name.", onchange: () => {
      const value = label.value.trim();
      if (!value) { label.value = sample.label; return; }
      api("PATCH", path(`/samples/${sample.id}`), { label: value }).then(refresh, fail);
    } });
    // The language spoken in the sample; searchable, since some models speak hundreds.
    const language = el("div", { title: "The language spoken in this sample. When a line is in another language, the Studio warns about accent." });
    languages().then((list) => language.replaceChildren(searchSelect({
      options: [{ value: "", label: "Not set" }, ...list.map((l) => ({ value: l.code, label: l.name }))],
      value: sample.language || "", label: "Sample language", placeholder: "Search languages",
      onChange: (code) => api("PATCH", path(`/samples/${sample.id}`), { language: code || null }).then(refresh, fail) })));
    const url = sampleUrl(charId, sample.file, sessionId);
    const wave = player(url, { buckets: 140, showTime: false });
    const play = wave.querySelector(".play");
    row.append(
      el("button", { class: `star ${isDefault ? "on" : ""}`,
        title: isDefault ? "Default sample: new lines start with it. Lines already written keep their sample."
          : "Make this the default sample for new lines",
        "aria-label": isDefault ? "Default sample" : "Make default", "aria-pressed": isDefault ? "true" : "false",
        onclick: () => isDefault || api("PATCH", path(`/samples/${sample.id}`), { default: true }).then(refresh, fail) },
      icon(["M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"], 16)),
      play, label, language, wave,
      el("div", { class: "muted num" }, `${sample.duration.toFixed(1)} s · ${{ recording: "recorded", design: "designed" }[sample.source] || "uploaded"}`),
      el("div", { class: "row end" }, revealButton(url.slice("/files/".length)),
        el("button", { class: "btn btn-ghost icon-btn", title: "Delete sample", "aria-label": "Delete sample",
        onclick: () => confirmDeleteSample(row, sample) }, icon(ICONS.trash))),
      transcriptLine(sample));
    return row;
  }

  // What the sample says: shown, corrected by hand, or written again by Whisper.
  function transcriptLine(sample) {
    const box = el("div", { class: "sample-transcript" });
    const again = (label) => el("button", { class: "btn btn-ghost btn-small", title: "Let Whisper write it again from the recording",
      onclick: async (event) => {
        event.currentTarget.disabled = true;
        event.currentTarget.textContent = "Transcribing\u2026";
        api("POST", path(`/samples/${sample.id}/transcribe`)).then(refresh, (error) => { fail(error); refresh(); });
      } }, label);
    const edit = () => {
      const field = el("textarea", { class: "textarea transcript-input", rows: 2, value: sample.transcript || "",
        "aria-label": "What the sample says" });
      const save = el("button", { class: "btn btn-primary btn-small", disabled: !field.value.trim(), onclick: () =>
        api("PATCH", path(`/samples/${sample.id}`), { transcript: field.value }).then(refresh, fail) }, "Save");
      field.addEventListener("input", () => { save.disabled = !field.value.trim(); });
      box.replaceChildren(field, el("div", { class: "row" }, save,
        el("button", { class: "btn btn-ghost btn-small", onclick: paint }, "Cancel")));
      field.focus();
    };
    const paint = () => {
      if (sample.transcribing) return box.replaceChildren(el("span", { class: "muted small" }, "Transcribing\u2026"));
      const pencil = el("button", { class: "btn btn-ghost icon-btn", title: "Correct the transcript", "aria-label": "Edit transcript",
        onclick: edit }, icon(["M4 20h4L19 9l-4-4L4 16z", "M13.5 6.5l4 4"]));
      box.replaceChildren(
        sample.transcript
          ? el("span", { class: "muted small transcript-text", title: "What the sample says. Some models use it to copy the voice." },
            `\u201c${sample.transcript}\u201d`)
          : el("span", { class: "faint small" }, "No transcript"),
        sample.transcript ? pencil : el("button", { class: "btn btn-ghost btn-small", onclick: edit }, "Add"));
      whisper.then((ok) => ok && box.append(again(sample.transcript ? "Transcribe again" : "Transcribe")));
    };
    paint();
    return box;
  }

  function confirmDeleteSample(row, sample) {
    row.querySelector(".confirm")?.remove();
    const box = el("div", { class: "confirm" },
      el("span", {}, `Delete “${sample.label}”? Lines using it switch to the default sample.`),
      el("div", { class: "row" },
        el("button", { class: "btn btn-danger", onclick: () => {
          stopAudio(sampleUrl(charId, sample.file, sessionId));
          api("DELETE", path(`/samples/${sample.id}`)).then(refresh, fail);
        } }, "Delete"),
        el("button", { class: "btn btn-ghost", onclick: () => box.remove() }, "Cancel")));
    row.append(box);
  }

  function addSample() {
    const mic = el("select", { class: "select", "aria-label": "Microphone",
      onchange: () => { mic.title = mic.selectedOptions[0]?.textContent || ""; } });
    const fileInput = el("input", { type: "file", accept: "audio/*", class: "sr-only", onchange: () => upload(fileInput.files[0]) });
    const recordButton = el("button", { class: "btn record-btn", onclick: toggleRecord }, el("span", { class: "rec-dot" }), "Record");
    const timer = el("span", { class: "num timer" }, "0:00");
    const meter = el("div", { class: "meter" }, el("div"));
    const hint = el("div", { class: "muted small" }, `Samples need at least ${MIN_SECONDS} seconds of clear speech.`);
    const review = el("div", { class: "review" });
    const designer = el("div", { class: "designer", hidden: true });
    const box = el("div", { class: "add-sample" },
      el("h3", {}, "Add a sample"),
      el("div", { class: "row wrap" },
        el("label", { class: "row muted mic-field" }, "Microphone", mic),
        recordButton, timer, meter,
        el("div", { class: "spacer" }),
        el("button", { class: "btn", onclick: () => fileInput.click() }, "Upload file"), fileInput,
        el("button", { class: "btn", onclick: () => toggleDesigner() }, "Design voice")),
      designer, hint, review,
      el("div", { class: "faint small" }, "Only use your own voice or voices you have permission to use."));

    let recorder = null;
    let ticker = null;

    async function fillMicrophones() {
      try {
        const devices = await microphones();
        const current = mic.value;
        mic.replaceChildren(...devices.map((d, i) => el("option", { value: d.deviceId }, d.label || `Microphone ${i + 1}`)));
        if (!devices.length) mic.append(el("option", { value: "" }, "Default microphone"));
        if (devices.some((d) => d.deviceId === current)) mic.value = current;
        mic.title = mic.selectedOptions[0]?.textContent || "";  // the full name when it is cut off
      } catch {
        mic.replaceChildren(el("option", { value: "" }, "Default microphone"));
      }
    }

    async function toggleRecord() {
      if (recorder) return stopRecording();
      review.replaceChildren();
      try {
        recorder = await record(mic.value, rememberMicrophone);
      } catch (error) {
        recorder = null;
        return setMessage(message, `Cannot use the microphone: ${error.message}`, "error");
      }
      setMessage(message, "");
      fillMicrophones(); // labels appear only after permission is granted
      recordButton.replaceChildren(el("span", { class: "rec-dot on" }), "Stop");
      recordButton.classList.add("recording");
      ticker = setInterval(() => {
        if (!box.isConnected) { // left the screen: end the recording and release the microphone
          clearInterval(ticker);
          recorder?.stop().catch(() => {});
          recorder = null;
          return;
        }
        const s = recorder.seconds();
        timer.textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
        meter.firstChild.style.width = `${Math.min(100, recorder.level() * 100)}%`;
        hint.textContent = s < MIN_SECONDS
          ? `Keep going: samples need at least ${MIN_SECONDS} seconds.`
          : "Long enough. Stop when you are done.";
        hint.className = s < MIN_SECONDS ? "warn small" : "muted small";
      }, 200);
    }

    async function stopRecording() {
      clearInterval(ticker);
      const { samples, sampleRate } = await recorder.stop();
      recorder = null;
      recordButton.replaceChildren(el("span", { class: "rec-dot" }), "Record");
      recordButton.classList.remove("recording");
      meter.firstChild.style.width = "0";
      hint.textContent = `Samples need at least ${MIN_SECONDS} seconds of clear speech.`;
      hint.className = "muted small";
      showReview(samples, sampleRate, "recording");
    }

    async function upload(file) {
      fileInput.value = "";
      if (!file) return;
      try {
        const { samples, sampleRate } = await decode(file);
        showReview(samples, sampleRate, "upload");
      } catch {
        setMessage(message, "Cannot read this file. Use WAV, MP3, M4A, OGG or FLAC.", "error");
      }
    }

    // Design: a model speaks a text in voices made from a description; one of them is kept as a sample.
    async function toggleDesigner() {
      if (!designer.hidden) return closeDesigner();
      designer.hidden = false;
      designer.replaceChildren(el("div", { class: "muted small" }, "Loading models\u2026"));
      let list;
      try {
        list = (await api("GET", "/api/models")).filter((m) => m.design);
      } catch (error) {
        designer.hidden = true;
        return fail(error);
      }
      drawDesigner(list);
    }

    let designJob = null; // the running job, cancelled when the panel closes
    function closeDesigner() {
      if (designJob) api("POST", `/api/jobs/${designJob}/cancel`).catch(() => {});
      designJob = null;
      designer.hidden = true;
      designer.replaceChildren();
    }

    function drawDesigner(list) {
      const usable = list.filter((m) => m.installed);
      const head = el("div", { class: "row" }, el("h4", {}, "Design a voice"), el("div", { class: "spacer" }),
        el("button", { class: "btn btn-ghost btn-small", onclick: closeDesigner }, "Close"));
      if (!usable.length) {
        designer.replaceChildren(head, el("p", { class: "muted small" },
          `${list.map((m) => m.title).join(" and ")} can make a voice from a description. Install one on the `,
          el("a", { href: "#/models" }, "Models screen"), "."));
        return;
      }
      let model = usable[0];
      let language = "en";
      let typedText = false;
      const modelSelect = el("select", { class: "select", "aria-label": "Model", onchange: () => {
        model = usable.find((m) => m.name === modelSelect.value);
        drawOptions();
      } }, ...list.map((m) => el("option", { value: m.name, disabled: !m.installed },
        m.installed ? m.title : `${m.title} (install it in Models)`)));
      modelSelect.value = model.name;
      const text = el("textarea", { class: "textarea", rows: 3, "aria-label": "Text the voices read",
        oninput: () => { typedText = true; textNote.hidden = true; } });
      const languageHolder = el("span");
      const textNote = el("div", { class: "warn small", hidden: true });
      const description = el("div", { class: "row wrap" });
      const generate = el("button", { class: "btn btn-primary", onclick: () => run() }, "Generate 3 voices");
      const status = el("span", { class: "small muted" });
      const results = el("div", { class: "design-results" });
      let describe = () => "";

      function setLanguage(code) {
        const sentence = designText(code);
        if (!typedText) text.value = sentence.text;
        language = code;
        const name = model.languages.find((l) => l.code === code)?.name || code;
        textNote.hidden = typedText || sentence.own;
        textNote.textContent = `This sentence is English: write one in ${name} so the voices speak it.`;
        drawDescription(); // OmniVoice accents are for English only
      }

      function drawOptions() {
        const code = designLanguage(model.languages.map((l) => l.code), language);
        languageHolder.replaceChildren(searchSelect({ label: "Language", small: true, value: code,
          options: model.languages.map((l) => ({ value: l.code, label: l.name })), onChange: setLanguage }));
        setLanguage(code);
      }

      function drawDescription() {
        if (model.design.kind === "text") {
          const box = el("input", { class: "input design-text", maxlength: model.design.max_length,
            "aria-label": "Voice description", placeholder: "e.g. a warm, deep male voice, speaking slowly" });
          describe = () => box.value;
          return description.replaceChildren(box);
        }
        const options = model.design.options;
        const pick = (group, name) => el("select", { class: "select select-small", "aria-label": name, "data-group": group },
          el("option", { value: "" }, `Any ${name.toLowerCase()}`), ...options[group].map((o) => el("option", { value: o }, o)));
        const selects = [pick("gender", "Gender"), pick("age", "Age"), pick("pitch", "Pitch")];
        if (language === "en") selects.push(pick("accent", "Accent"));
        const whisper = el("input", { type: "checkbox" });
        describe = () => [...selects.map((s) => s.value), whisper.checked ? "whisper" : ""].filter(Boolean).join(", ");
        description.replaceChildren(...selects, el("label", { class: "row small" }, whisper, "Whisper"));
      }

      async function run() {
        generate.disabled = true;
        results.replaceChildren();
        status.className = "small muted";
        status.replaceChildren("Generating\u2026");
        try {
          const job = await api("POST", `/api/characters/${charId}/design${query(sessionId)}`,
            { model: model.name, language, text: text.value, description: describe() });
          designJob = job.id;
          status.append(" ", el("button", { class: "btn btn-ghost btn-small", onclick: () => {
            api("POST", `/api/jobs/${job.id}/cancel`).catch(() => {});
          } }, "Cancel"));
          const result = await waitForJob(job.id);
          if (designJob !== job.id) return; // the panel was closed
          status.textContent = "Listen and keep the one you like.";
          drawCandidates(result);
        } catch (error) {
          status.className = error.cancelled ? "small muted" : "small warn";
          status.textContent = error.cancelled ? "Cancelled." : error.message;
        } finally {
          designJob = null;
          generate.disabled = false;
        }
      }

      function drawCandidates(result) {
        const label = (result.description || "designed voice").slice(0, 40);
        results.replaceChildren(...result.candidates.map((candidate, i) => el("div", { class: "row design-candidate" },
          player(`/files/${candidate.file}`, { label: `Play voice ${i + 1}` }),
          el("button", { class: "btn btn-small", onclick: async () => {
            try {
              const { samples, sampleRate } = await decode(`/files/${candidate.file}`);
              showReview(samples, sampleRate, "design", { text: result.text, language: result.language, label });
            } catch (error) {
              fail(error);
            }
          } }, "Keep this one"))));
      }

      designer.replaceChildren(head,
        el("div", { class: "row wrap" }, el("label", { class: "row muted" }, "Model", modelSelect),
          el("label", { class: "row muted" }, "Language", languageHolder)),
        el("label", { class: "field-label" }, "Text the voices read"), text, textNote,
        el("label", { class: "field-label" }, "Voice"), description,
        el("div", { class: "faint small" }, `Keep the text long enough for ${MIN_SECONDS} seconds of speech.`),
        el("div", { class: "row" }, generate, status), results);
      drawOptions();
    }

    // known: what a designed sample says, its language and label, so Whisper is not asked.
    function showReview(samples, sampleRate, source, known = null) {
      const status = el("span", { class: "small" });
      const save = el("button", { class: "btn btn-primary", disabled: true }, "Add sample");
      // What the sample says: Whisper writes it (and hears the language) when installed, otherwise it is typed.
      const field = el("textarea", { class: "textarea transcript-input", rows: 2, "aria-label": "What does this sample say?",
        placeholder: "Type what is said in the sample" });
      const fieldNote = el("div", { class: "muted small" });
      const againButton = el("button", { class: "btn btn-ghost btn-small", hidden: true, title: "Let Whisper write it again",
        onclick: () => transcribe() }, "Transcribe again");
      let typed = Boolean(known); // the user's own text is not replaced by a later automatic transcription
      let language = known?.language || null; // what Whisper heard
      if (known) {
        field.value = known.text;
        fieldNote.textContent = "The text the voice read.";
      }
      let lengthOk = false;
      let request = 0;
      let pending = null; // the automatic transcription after the trim settles
      const paintSave = () => { save.disabled = !lengthOk || !field.value.trim(); };
      field.addEventListener("input", () => { typed = true; paintSave(); });

      async function transcribe() {
        const mine = ++request;
        const [start, end] = range.getRange();
        field.disabled = true;
        againButton.disabled = true;
        fieldNote.className = "muted small";
        fieldNote.textContent = "Transcribing\u2026";
        try {
          const heard = await api("POST", "/api/transcribe", encodeWav(trim(samples, sampleRate, start, end), sampleRate));
          if (mine !== request) return;
          field.value = heard.text;
          language = heard.language;
          typed = false;
          fieldNote.textContent = "Written by Whisper. Correct it if something is wrong.";
        } catch (error) {
          if (mine !== request) return;
          fieldNote.className = "warn small";
          fieldNote.textContent = `Whisper could not write it (${error.message}). Type it instead.`;
        } finally {
          if (mine === request) {
            field.disabled = false;
            againButton.disabled = false;
            paintSave();
          }
        }
      }

      const range = rangeEditor(samples, sampleRate, (start, end) => {
        if (known && typed) {
          const cut = isCut(start, end, samples.length / sampleRate);
          fieldNote.className = cut ? "warn small" : "muted small";
          fieldNote.textContent = cut ? "You cut the clip: make sure the text matches only what is left."
            : "The text the voice read.";
        }
        lengthOk = end - start >= MIN_SECONDS;
        paintSave();
        status.textContent = lengthOk ? "" : `Select at least ${MIN_SECONDS} seconds.`;
        status.className = lengthOk ? "small" : "warn small";
        clearTimeout(pending);
        pending = setTimeout(() => whisper.then((ok) => ok && !typed && lengthOk && field.isConnected && transcribe()), 800);
      });
      whisper.then((ok) => {
        againButton.hidden = !ok;
        if (ok || known) return;
        fieldNote.className = "muted small";
        fieldNote.replaceChildren("Type exactly what is said in the sample. Some models use it to copy the voice. Install Whisper on the ",
          el("a", { href: "#/models" }, "Models screen"), " to have it written for you.");
      });
      save.onclick = async () => {
        const [start, end] = range.getRange();
        save.disabled = true;
        try {
          const extra = `source=${source}&transcript=${encodeURIComponent(field.value.trim())}`
            + (language ? `&language=${language}` : "") + (known ? `&label=${encodeURIComponent(known.label)}` : "");
          const data = await api("POST", `${path("/samples")}${sessionId ? "&" : "?"}${extra}`,
            encodeWav(trim(samples, sampleRate, start, end), sampleRate));
          review.replaceChildren();
          timer.textContent = "0:00";
          setMessage(message, "Sample added.", "info");
          refresh(data);
        } catch (error) {
          save.disabled = false;
          fail(error);
        }
      };
      review.replaceChildren(el("div", { class: "review-box" },
        el("div", { class: "muted small" }, "Drag the handles to cut silence or mistakes from the start and end."),
        range.element,
        el("label", { class: "field-label" }, "What does this sample say?"),
        field,
        el("div", { class: "row" }, fieldNote, el("div", { class: "spacer" }), againButton),
        el("div", { class: "row" }, save, el("button", { class: "btn btn-ghost", onclick: () => review.replaceChildren() }, "Discard"), status)));
    }

    fillMicrophones();
    return box;
  }

  refresh().catch(fail);
  return root;
}
