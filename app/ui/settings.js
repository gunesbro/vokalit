// Shared Studio controls: model picker, popovers, generation-setting sliders.
import { el, icon, ICONS } from "./app.js";
import { filterOptions, pickerLabel } from "./script.js";

const COLORS = { chatterbox: "#e9a15b", omnivoice: "#56b6c2", "chatterbox-vc": "#c678dd" };
const FALLBACK = ["#98c379", "#d19a66", "#7aa2f7", "#e5807a"];

export function modelColor(name) {
  if (COLORS[name]) return COLORS[name];
  const sum = [...name].reduce((total, ch) => total + ch.charCodeAt(0), 0);
  return FALLBACK[sum % FALLBACK.length];
}

export const dot = (color, size = 6) => el("span", { class: "dot", "aria-hidden": "true",
  style: { width: `${size}px`, height: `${size}px`, background: color } });

// Opens `content` under `anchor`; closes on outside click or Escape. Returns close().
export function popover(anchor, content, { align = "left", up = false } = {}) {
  document.querySelector(".popover")?.dispatchEvent(new Event("close"));
  const box = el("div", { class: "popover" }, content);
  const holder = anchor.parentElement;
  holder.classList.add("pop-holder");
  box.style[align] = "0";
  if (up) Object.assign(box.style, { top: "auto", bottom: "calc(100% + 6px)" }); // opens above (e.g. from the footer)
  holder.append(box);
  const close = () => {
    box.remove();
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", escape);
    anchor.setAttribute("aria-expanded", "false");
  };
  const outside = (e) => { if (!box.contains(e.target) && !anchor.contains(e.target)) close(); };
  const escape = (e) => { if (e.key === "Escape") close(); };
  box.addEventListener("close", close);
  setTimeout(() => document.addEventListener("pointerdown", outside, true));
  document.addEventListener("keydown", escape);
  anchor.setAttribute("aria-expanded", "true");
  return close;
}

// Multi-select dropdown of installed models. onChange(names) after each toggle.
export function modelPicker(installed, selected, onChange) {
  let current = selected.filter((name) => installed.some((m) => m.name === name));
  const titles = Object.fromEntries(installed.map((m) => [m.name, m.title.split(" ")[0]]));
  const button = el("button", { class: "btn picker", "aria-haspopup": "listbox", "aria-label": "Models to generate with" });
  const paint = () => button.replaceChildren(
    el("span", { class: "dots" }, current.map((name) => dot(modelColor(name)))),
    installed.length ? pickerLabel(current, titles) : "No models installed",
    icon(ICONS.chevron, 12));
  button.onclick = () => {
    if (button.getAttribute("aria-expanded") === "true") return document.querySelector(".popover")?.dispatchEvent(new Event("close"));
    popover(button, el("div", { class: "menu", role: "listbox", "aria-label": "Installed models", "aria-multiselectable": "true" },
      installed.map((model) => el("label", { class: "menu-item" },
        el("input", { type: "checkbox", checked: current.includes(model.name), onchange: (e) => {
          current = e.target.checked ? [...current, model.name] : current.filter((n) => n !== model.name);
          current = installed.map((m) => m.name).filter((n) => current.includes(n)); // keep the Models order
          paint();
          onChange(current);
        } }),
        dot(modelColor(model.name), 8),
        el("span", { class: "grow" }, model.title),
        el("span", { class: "faint small" }, model.summary.split(" · ")[0]))),
      el("div", { class: "menu-sep" }),
      el("a", { class: "menu-link", href: "#/models" }, installed.length ? "Install more in Models" : "Install a model in the Models tab")));
  };
  paint();
  return { element: el("div", { class: "pop-holder" }, button), get: () => current };
}

// Tabs, one per model: tabs(names, titles, render(name) -> Node).
// Which tab was open, per place (`key`), so redrawing after a change keeps the same model open.
const openTabs = new Map();

export function modelTabs(names, titles, render, key = null) {
  const body = el("div");
  const bar = el("div", { class: "tabs", role: "tablist" });
  const show = (name) => {
    if (key) openTabs.set(key, name);
    for (const tab of bar.children) tab.setAttribute("aria-selected", tab.dataset.model === name ? "true" : "false");
    body.replaceChildren(render(name));
  };
  for (const name of names) {
    bar.append(el("button", { class: "tab", role: "tab", "data-model": name, onclick: () => show(name) },
      dot(modelColor(name)), titles[name] || name));
  }
  if (names.length) show(names.includes(openTabs.get(key)) ? openTabs.get(key) : names[0]);
  return el("div", {}, names.length > 1 ? bar : null, body);
}

// One slider per setting. `values` are shown, `base` is what they are compared with.
// note(spec, value, base) gives the text under a slider. onCommit(key, value) when a slider is released.
export function sliders(schema, values, base, note, onCommit) {
  if (!schema.length) return el("p", { class: "muted small" }, "This model has no generation settings.");
  return el("div", { class: "sliders" }, schema.map((spec) => {
    const changed = values[spec.key] !== base[spec.key];
    const shown = (v) => Number(v).toFixed(spec.step >= 1 ? 0 : 2); // whole-number settings (steps) without decimals
    const number = el("div", { class: `num ${changed ? "accent" : "muted"}` }, shown(values[spec.key]));
    const input = el("input", { type: "range", min: spec.min, max: spec.max, step: spec.step, value: values[spec.key],
      "aria-label": spec.label,
      oninput: () => { number.textContent = shown(input.value); },
      onchange: () => onCommit(spec.key, Number(input.value)) });
    return el("div", { class: `slider ${changed ? "changed" : ""}` },
      el("div", { class: "row" }, el("label", {}, spec.label), el("div", { class: "spacer" }), number),
      input,
      el("div", { class: "faint small" }, note(spec, values[spec.key], base[spec.key])));
  }));
}

// A menu at the mouse position (right-click). Closes on outside click, Escape or scrolling. Returns close().
export function contextMenu(event, content) {
  event.preventDefault();
  document.querySelector(".popover")?.dispatchEvent(new Event("close"));
  const box = el("div", { class: "popover context-menu" }, content);
  document.body.append(box);
  const { innerWidth, innerHeight } = window;
  const rect = box.getBoundingClientRect();
  box.style.left = `${Math.min(event.clientX, innerWidth - rect.width - 8)}px`;
  box.style.top = `${Math.min(event.clientY, innerHeight - rect.height - 8)}px`;
  const close = () => {
    box.remove();
    document.removeEventListener("pointerdown", outside, true);
    document.removeEventListener("keydown", escape);
    window.removeEventListener("wheel", close, true);
  };
  const outside = (e) => { if (!box.contains(e.target)) close(); };
  const escape = (e) => { if (e.key === "Escape") close(); };
  box.addEventListener("close", close);
  setTimeout(() => document.addEventListener("pointerdown", outside, true));
  document.addEventListener("keydown", escape);
  window.addEventListener("wheel", close, true);
  return close;
}

// A choice among many (languages): a button that opens a search box and the matching options. Type to filter, Enter
// takes the first match, Esc closes. onChange(value) after a pick. `small` for tight rows.
export function searchSelect({ options, value, onChange, label, placeholder = "Search", small = false }) {
  const current = () => options.find((o) => o.value === value)?.label ?? value ?? "";
  const button = el("button", { type: "button", class: `select search-select ${small ? "select-small" : ""}`,
    "aria-haspopup": "listbox", "aria-label": label, title: label }, current());
  button.onclick = () => {
    const input = el("input", { class: "input", placeholder, "aria-label": placeholder });
    const list = el("div", { class: "menu search-list", role: "listbox" });
    const pick = (option) => {
      document.querySelector(".popover")?.dispatchEvent(new Event("close"));
      value = option.value;
      button.textContent = current();
      onChange(option.value);
    };
    let shown = [];
    let focused = 0; // the option the arrow keys are on; Enter takes it
    const items = () => [...list.querySelectorAll(".menu-item")];
    const paintFocus = () => {
      items().forEach((item, i) => item.classList.toggle("focused", i === focused));
      items()[focused]?.scrollIntoView({ block: "nearest" });
    };
    const paint = () => {
      shown = filterOptions(options, input.value).slice(0, 200); // a long list is cut; typing narrows it
      const total = filterOptions(options, input.value).length;
      list.replaceChildren(...shown.map((o) => el("button", { type: "button",
        class: `menu-item ${o.value === value ? "active" : ""}`, role: "option", onclick: () => pick(o) }, o.label)));
      if (!total) list.append(el("div", { class: "faint small menu-empty" }, "No match"));
      if (total > shown.length) list.append(el("div", { class: "faint small menu-empty" }, `Type to see the other ${total - shown.length}`));
      // Start on the current choice when nothing is typed, otherwise on the best match.
      focused = input.value.trim() ? 0 : Math.max(0, shown.findIndex((o) => o.value === value));
      paintFocus();
    };
    input.addEventListener("input", paint);
    input.addEventListener("keydown", (e) => {
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && shown.length) {
        e.preventDefault();
        focused = (focused + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
        paintFocus();
      }
      if (e.key === "Enter") { e.preventDefault(); if (shown[focused]) pick(shown[focused]); }
    });
    popover(button, el("div", { class: "search-box" }, input, list));
    paint();
    items()[focused]?.scrollIntoView({ block: "center" });
    input.focus();
  };
  return el("div", { class: "pop-holder" }, button);
}
