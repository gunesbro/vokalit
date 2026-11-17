// Characters screen: library list, rename, delete, and the samples panel (also used by Studio).
import { api, editableTitle, el, icon, ICONS, revealButton, setMessage } from "./app.js";
import { decode, encodeWav, microphones, record, trim } from "./audio.js";
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
    const language = el("select", { class: "select", "aria-label": "Sample language", title: "The language spoken in this sample. When a line is in another language, the Studio warns about accent.",
      onchange: () => api("PATCH", path(`/samples/${sample.id}`), { language: language.value || null }).then(refresh, fail) },
    el("option", { value: "" }, "Not set"));
    languages().then((list) => {
      language.append(...list.map((l) => el("option", { value: l.code }, l.name)));
      language.value = sample.language || "";
    });
    const url = sampleUrl(charId, sample.file, sessionId);
    const wave = player(url, { buckets: 140, showTime: false });
    const play = wave.querySelector(".play");
    row.append(
      el("button", { class: `star ${isDefault ? "on" : ""}`,
        title: isDefault ? "Default sample: used by lines that do not choose a sample" : "Make this the default sample",
        "aria-label": isDefault ? "Default sample" : "Make default", "aria-pressed": isDefault ? "true" : "false",
        onclick: () => isDefault || api("PATCH", path(`/samples/${sample.id}`), { default: true }).then(refresh, fail) },
      icon(["M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"], 16)),
      play, label, language, wave,
      el("div", { class: "muted num" }, `${sample.duration.toFixed(1)} s · ${sample.source === "recording" ? "recorded" : "uploaded"}`),
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
    const mic = el("select", { class: "select", "aria-label": "Microphone" });
    const fileInput = el("input", { type: "file", accept: "audio/*", class: "sr-only", onchange: () => upload(fileInput.files[0]) });
    const recordButton = el("button", { class: "btn record-btn", onclick: toggleRecord }, el("span", { class: "rec-dot" }), "Record");
    const timer = el("span", { class: "num timer" }, "0:00");
    const meter = el("div", { class: "meter" }, el("div"));
    const hint = el("div", { class: "muted small" }, `Samples need at least ${MIN_SECONDS} seconds of clear speech.`);
    const review = el("div", { class: "review" });
    const box = el("div", { class: "add-sample" },
      el("h3", {}, "Add a sample"),
      el("div", { class: "row wrap" },
        el("label", { class: "row muted" }, "Microphone", mic),
        recordButton, timer, meter,
        el("div", { class: "spacer" }),
        el("button", { class: "btn", onclick: () => fileInput.click() }, "Upload file"), fileInput),
      hint, review,
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
      } catch {
        mic.replaceChildren(el("option", { value: "" }, "Default microphone"));
      }
    }

    async function toggleRecord() {
      if (recorder) return stopRecording();
      review.replaceChildren();
      try {
        recorder = await record(mic.value);
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

    function showReview(samples, sampleRate, source) {
      const status = el("span", { class: "small" });
      const save = el("button", { class: "btn btn-primary", disabled: true }, "Add sample");
      // What the sample says: Whisper writes it (and hears the language) when installed, otherwise it is typed.
      const field = el("textarea", { class: "textarea transcript-input", rows: 2, "aria-label": "What does this sample say?",
        placeholder: "Type what is said in the sample" });
      const fieldNote = el("div", { class: "muted small" });
      const againButton = el("button", { class: "btn btn-ghost btn-small", hidden: true, title: "Let Whisper write it again",
        onclick: () => transcribe() }, "Transcribe again");
      let typed = false; // the user's own text is not replaced by a later automatic transcription
      let language = null; // what Whisper heard
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
        lengthOk = end - start >= MIN_SECONDS;
        paintSave();
        status.textContent = lengthOk ? "" : `Select at least ${MIN_SECONDS} seconds.`;
        status.className = lengthOk ? "small" : "warn small";
        clearTimeout(pending);
        pending = setTimeout(() => whisper.then((ok) => ok && !typed && lengthOk && field.isConnected && transcribe()), 800);
      });
      whisper.then((ok) => {
        againButton.hidden = !ok;
        if (ok) return;
        fieldNote.className = "muted small";
        fieldNote.replaceChildren("Type exactly what is said in the sample. Some models use it to copy the voice. Install Whisper on the ",
          el("a", { href: "#/models" }, "Models screen"), " to have it written for you.");
      });
      save.onclick = async () => {
        const [start, end] = range.getRange();
        save.disabled = true;
        try {
          const extra = `source=${source}&transcript=${encodeURIComponent(field.value.trim())}`
            + (language ? `&language=${language}` : "");
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
