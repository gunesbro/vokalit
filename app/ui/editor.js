import { insertTag } from "./script.js";

// The line editor: plain text with sound tags shown as chips. The text is stored with canonical tags, e.g.
// "Hi [laughter] there"; each model gets them in its own syntax on the server.

// Text and known tags, in order: [{ text }, { tag }, ...]. Unknown brackets stay text.
export function parseText(text, known) {
  if (!known.length) return text ? [{ text }] : [];
  const pattern = new RegExp(`\\[(${known.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\]`, "g");
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ tag: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

export function joinParts(parts) {
  return parts.map((p) => (p.tag ? `[${p.tag}]` : p.text)).join("");
}

// A text field for a line: plain text, with known sound tags shown as chips (× removes one). Behaves like a
// textarea for the code around it: `.value` is the canonical text and it fires "input" when that changes.
// `insertSound(tag)` puts a chip at the caret. Paste is plain text; formatting commands are ignored.
// Typing "[" opens a list of sounds (`suggestions`: [{ tag, label, note }], note = which models perform it); typing
// narrows it, arrows move, Enter or Tab takes one, Esc closes.
export function soundEditor({ value = "", tags = [], labels = {}, ariaLabel = "Text", placeholder = "", suggestions = [], el }) {
  const field = el("div", { class: "textarea sound-editor", contenteditable: "true", role: "textbox", "aria-multiline": "true",
    "aria-label": ariaLabel, "data-placeholder": placeholder, spellcheck: "true" });
  let current = value;
  let lastCaret = value.length; // where Add sound inserts after the field lost focus
  // Our own undo history: the browser's is lost whenever chips are redrawn. Typing within a second is one step.
  const history = [{ text: value, caret: value.length }];
  let step = 0;
  let lastRecord = 0;
  const record = (text, caret, group = false) => {
    history.splice(step + 1);
    if (group && step > 0 && Date.now() - lastRecord < 1000) history[step] = { text, caret };
    else { history.push({ text, caret }); step = history.length - 1; }
    lastRecord = Date.now();
  };
  const restore = (to) => {
    if (to < 0 || to >= history.length) return;
    step = to;
    lastRecord = 0;
    const { text, caret } = history[step];
    render(text, caret);
    current = text;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const chip = (tag, editable = true) => el("span", { class: "sound-chip", contenteditable: "false", "data-tag": tag,
    title: `Sound: ${labels[tag] || tag}` }, labels[tag] || tag,
  editable && el("button", { type: "button", class: "chip-x", tabindex: "-1", "aria-label": `Remove ${labels[tag] || tag}`,
    onmousedown: (e) => e.preventDefault(),
    onclick: (e) => { e.target.closest(".sound-chip").remove(); update(); } }, "×"));

  const render = (text, caret = null) => {
    field.replaceChildren(...parseText(text, tags).map((p) => (p.tag ? chip(p.tag) : document.createTextNode(p.text))));
    if (text.endsWith("\n")) field.append(el("br")); // so a last empty line shows
    if (caret !== null) setCaret(caret);
  };

  // The canonical text of the field's contents.
  const read = (nodes = field.childNodes) => [...nodes].map((node) => {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
    if (node.classList?.contains("sound-chip")) return `[${node.dataset.tag}]`;
    if (node.nodeName === "BR") return node === field.lastChild ? "" : "\n";
    return (node.nodeName === "DIV" ? "\n" : "") + read(node.childNodes); // a line the browser wrapped in a div
  }).join("");

  // Caret position in canonical text, and back.
  const caretOffset = () => {
    const selection = document.getSelection();
    if (!selection.rangeCount || !field.contains(selection.focusNode)) return null;
    const range = document.createRange();
    range.selectNodeContents(field);
    range.setEnd(selection.focusNode, selection.focusOffset);
    return read(range.cloneContents().childNodes).length;
  };
  const setCaret = (offset) => {
    let left = offset;
    const range = document.createRange();
    for (const node of field.childNodes) {
      const length = node.nodeType === Node.TEXT_NODE ? node.textContent.length : read([node]).length;
      if (left <= length && node.nodeType === Node.TEXT_NODE) { range.setStart(node, left); break; }
      if (left < length) { range.setStartBefore(node); break; }
      left -= length;
      range.setStartAfter(node);
    }
    range.collapse(true);
    const selection = document.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  };

  // --- "[" suggestions -------------------------------------------------------------------------------------
  let menu = null; // { box, items, active, start } while open; start = offset of the "["
  const closeMenu = () => { menu?.box.remove(); menu = null; };
  const choose = (tag) => {
    const caret = caretOffset() ?? current.length;
    const before = current.slice(0, menu.start);
    const after = current.slice(caret);
    closeMenu();
    const { value: text, caret: at } = insertTag(before + after, before.length, before.length, tag);
    render(text, at);
    current = text;
    lastCaret = at;
    record(text, at);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const paintMenu = () => {
    menu.items.forEach((item, i) => item.classList.toggle("active", i === menu.active));
    menu.items[menu.active]?.scrollIntoView({ block: "nearest" }); // the list scrolls with the arrow keys
  };
  function suggest() {
    const caret = caretOffset();
    const typed = caret === null ? null : current.slice(0, caret).match(/\[([a-z-]*)$/i);
    const matches = typed ? suggestions.filter((s) => s.tag.startsWith(typed[1].toLowerCase())
      || s.label.toLowerCase().includes(typed[1].toLowerCase())) : [];
    if (!matches.length) return closeMenu();
    const start = caret - typed[0].length;
    if (!menu) {
      menu = { box: el("div", { class: "menu suggest-menu", role: "listbox" }), items: [], active: 0, start };
      document.body.append(menu.box);
    }
    menu.start = start;
    menu.items = matches.map((s) => el("button", { type: "button", class: "menu-item suggest-item", role: "option",
      onmousedown: (e) => { e.preventDefault(); choose(s.tag); } },
    el("span", {}, s.label), s.note && el("span", { class: "faint small" }, s.note)));
    menu.active = Math.min(menu.active, matches.length - 1);
    // A heading before each group (Sounds, Emotions, ...), as in the Add tag menu
    menu.box.replaceChildren(...matches.flatMap((s, n) => (n === 0 || s.group !== matches[n - 1].group
      ? [el("div", { class: "faint small suggest-head" }, s.group || "Tags"), menu.items[n]] : [menu.items[n]])));
    paintMenu();
    const rect = document.getSelection().getRangeAt(0).getBoundingClientRect();
    const fallback = field.getBoundingClientRect();
    const left = Math.min(rect.left || fallback.left, window.innerWidth - menu.box.offsetWidth - 8); // stays on screen
    Object.assign(menu.box.style, { left: `${Math.max(8, left)}px`, top: `${(rect.bottom || fallback.top + 24) + 4}px` });
  }

  function update() {
    const text = read();
    // A tag typed or pasted as text becomes a chip.
    const typedTag = [...field.childNodes].some((n) => n.nodeType === Node.TEXT_NODE
      && parseText(n.textContent, tags).some((p) => p.tag));
    if (typedTag || [...field.childNodes].some((n) => n.nodeName === "DIV")) render(text, caretOffset() ?? text.length);
    if (text === current) return;
    current = text;
    record(text, caretOffset() ?? text.length, true);
    field.dispatchEvent(new Event("input", { bubbles: true }));
    suggest();
  }

  field.addEventListener("input", (e) => { if (e.isTrusted) { e.stopImmediatePropagation(); update(); } }, true);
  field.addEventListener("beforeinput", (e) => {
    if (e.inputType.startsWith("format")) e.preventDefault();
    if (e.inputType === "historyUndo" || e.inputType === "historyRedo") {
      e.preventDefault();
      restore(step + (e.inputType === "historyUndo" ? -1 : 1));
    }
  });
  field.addEventListener("keydown", (e) => {
    if (menu) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        menu.active = (menu.active + (e.key === "ArrowDown" ? 1 : -1) + menu.items.length) % menu.items.length;
        return paintMenu();
      }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); return menu.items[menu.active].dispatchEvent(new MouseEvent("mousedown")); }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); return closeMenu(); }
    }
    if (e.key === "Enter") { e.preventDefault(); document.execCommand("insertText", false, "\n"); }
    const key = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (key === "z" || key === "y")) {
      e.preventDefault();
      restore(step + (key === "y" || e.shiftKey ? 1 : -1));
    }
  });
  field.addEventListener("paste", (e) => {
    e.preventDefault();
    document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
  });
  field.addEventListener("drop", (e) => e.preventDefault()); // dragged formatted content
  const remember = () => { const at = caretOffset(); if (at !== null) lastCaret = at; };
  field.addEventListener("keyup", remember);
  field.addEventListener("mouseup", remember);
  field.addEventListener("blur", () => { remember(); closeMenu(); });

  Object.defineProperty(field, "value", { get: () => current, set: (text) => { current = text; render(text); } });
  field.insertSound = (tag) => {
    const at = Math.min(caretOffset() ?? lastCaret, current.length);
    const { value: text, caret } = insertTag(current, at, at, tag);
    field.focus();
    render(text, caret);
    current = text;
    lastCaret = caret;
    record(text, caret);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };
  render(value);
  return field;
}

// Read-only text with chips, for a collapsed line.
export function soundText(text, tags, labels, el) {
  return parseText(text, tags).map((p) => (p.tag
    ? el("span", { class: "sound-chip", title: `Sound: ${labels[p.tag] || p.tag}` }, labels[p.tag] || p.tag)
    : p.text));
}
