// The page's preferences (the playback volume, the Dub panes' sizes), kept by the server: the page's own storage
// belongs to its address, and the server's port, part of that address, changes every launch.
import { api } from "./app.js";

let saved = {};
const timers = {};

// Once at start, before the first screen.
export async function loadPreferences() {
  try { saved = await api("GET", "/api/preferences"); } catch { saved = {}; }
}

export const preference = (key, fallback) => saved[key] ?? fallback;

// Sent a moment after the last change: a dragged slider or pane changes many times a second.
export function savePreference(key, value) {
  saved[key] = value;
  clearTimeout(timers[key]);
  timers[key] = setTimeout(() => api("PATCH", "/api/preferences", { [key]: value }).catch(() => {}), 300);
}
