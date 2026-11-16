// App shell: API client, DOM helper, message line, job polling, screen router.
import { renderCharacters } from "./characters.js";
import { renderModels } from "./models.js";
import { renderStudio } from "./studio.js";

const TOKEN = document.querySelector('meta[name="vokalit-token"]').content;

export async function api(method, path, body) {
  const headers = { "X-Vokalit-Token": TOKEN };
  let payload;
  if (body instanceof ArrayBuffer || body instanceof Blob) {
    headers["Content-Type"] = "audio/wav";
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(path, { method, headers, body: payload });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error((data && data.error) || `Request failed (${response.status}).`);
  return data;
}

// Polls a background job until it ends. onUpdate gets the job each time.
export async function waitForJob(id, onUpdate = () => {}) {
  for (;;) {
    const job = await api("GET", `/api/jobs/${id}`);
    onUpdate(job);
    if (job.state === "done") return job.result;
    if (job.state === "failed") throw new Error(job.error);
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

// Builds DOM nodes. Text is always set as text, never parsed as HTML (user data is shown everywhere).
export function el(tag, attrs = {}, ...children) {
  const node = document.createElementNS(
    tag === "svg" || tag === "path" || tag === "circle" || tag === "rect" ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml",
    tag,
  );
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.setAttribute("class", value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    // `value` must be a property (a textarea ignores the attribute); SVG sizes must stay attributes.
    else if (key === "value" || (key in node && typeof value !== "string" && !(node instanceof SVGElement))) node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function icon(paths, size = 14) {
  const svg = el("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
  for (const d of paths) svg.append(el("path", { d }));
  return svg;
}

export const ICONS = {
  plus: ["M12 5v14M5 12h14"],
  close: ["M6 6l12 12M18 6L6 18"],
  trash: ["M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"],
  play: ["M7 4.5l12 7.5-12 7.5z"],
  pause: ["M8 5v14M16 5v14"],
  chevron: ["M6 9l6 6 6-6"],
  folder: ["M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"],
  pencil: ["M4 20h4L19 9l-4-4L4 16v4z", "M13.5 6.5l4 4"],
};

// A text field that clearly looks editable: the input plus a pencil that focuses it.
export function editableTitle(input) {
  return el("label", { class: "editable-title", title: "Click to rename" }, input,
    el("span", { class: "pencil", "aria-hidden": "true" }, icon(ICONS.pencil, 13)));
}

let platform = "";
const revealLabel = () => (platform === "win32" ? "Show in File Explorer" : platform === "darwin" ? "Show in Finder" : "Open containing folder");

// Opens the system file manager at an audio file. `path` is relative to workspace/ (as in /files/ URLs).
export function revealButton(path, { text = false } = {}) {
  const button = el("button", { class: text ? "btn btn-small btn-ghost" : "btn btn-ghost icon-btn", title: revealLabel(),
    "aria-label": revealLabel(), onclick: () => api("POST", "/api/reveal", { path }).catch((error) => {
      button.title = error.message;
    }) }, icon(ICONS.folder), text && revealLabel());
  return button;
}

// One message line per screen: setMessage(node, text, "error" | "warn" | "info").
export function setMessage(node, text = "", kind = "info") {
  node.textContent = text;
  node.className = `message ${kind}`;
  node.setAttribute("role", "status");
}

const SCREENS = {
  models: renderModels,
  studio: renderStudio,
  characters: renderCharacters,
};

let current = null;

// Screens handle their own sub-paths (#/characters/<id>), so only a change of screen re-renders.
function route() {
  const name = (location.hash.match(/^#\/(\w+)/) || [])[1] || "studio";
  if (name === current) return;
  current = name;
  const screen = document.getElementById("screen");
  screen.replaceChildren();
  for (const link of document.querySelectorAll(".rail a")) {
    link.toggleAttribute("aria-current", link.dataset.screen === name);
    if (link.dataset.screen === name) link.setAttribute("aria-current", "page");
  }
  (SCREENS[name] || SCREENS.studio)(screen);
}

async function showGpu() {
  const node = document.getElementById("gpu");
  try {
    const { gpu, platform: name } = await api("GET", "/api/system");
    platform = name;
    node.classList.add(gpu ? "ok" : "missing");
    node.title = gpu || "No NVIDIA GPU found";
  } catch {
    node.title = "GPU status unknown";
  }
}

window.addEventListener("hashchange", route);
route();
showGpu();
