// Waveform bars, a small player, and a trim range editor.
import { el, icon, ICONS } from "./app.js";
import { decode, encodeWav, peaks, trim } from "./audio.js";

const peakCache = new Map();

export async function urlPeaks(url, buckets) {
  const key = `${url}|${buckets}`;
  if (!peakCache.has(key)) peakCache.set(key, decode(url).then(({ samples }) => peaks(samples, buckets)));
  return peakCache.get(key);
}

export function bars(values, className = "") {
  return el("div", { class: `wave ${className}`, "aria-hidden": "true" },
    values.map((v) => el("span", { style: { height: `${Math.max(12, Math.round(v * 100))}%` } })));
}

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// A play button + waveform that fills as it plays. `selected` uses the accent color.
export function player(url, { buckets = 48, selected = false, label = "Play", showTime = true } = {}) {
  const audio = new Audio(url);
  const wave = el("div", { class: `wave ${selected ? "selected" : ""}`, "aria-hidden": "true" });
  const button = el("button", { class: "play", "aria-label": label, title: label, onclick: () => (audio.paused ? audio.play() : audio.pause()) },
    icon(ICONS.play, 12));
  const time = el("span", { class: "time num" });
  const root = el("div", { class: "player" }, button, wave, showTime && time);
  urlPeaks(url, buckets).then((values) => {
    wave.replaceChildren(...values.map((v) => el("span", { style: { height: `${Math.max(12, Math.round(v * 100))}%` } })));
  }).catch(() => wave.replaceChildren(el("span", { class: "faint small" }, "Cannot read audio")));
  const paint = () => {
    const played = audio.duration ? audio.currentTime / audio.duration : 0;
    [...wave.children].forEach((bar, i, all) => bar.classList.toggle("played", i / all.length < played));
    time.textContent = fmt(audio.paused && !audio.currentTime ? audio.duration || 0 : audio.currentTime);
  };
  audio.addEventListener("loadedmetadata", paint);
  audio.addEventListener("timeupdate", paint);
  audio.addEventListener("play", () => button.replaceChildren(icon(ICONS.pause, 12)));
  audio.addEventListener("pause", () => button.replaceChildren(icon(ICONS.play, 12)));
  audio.addEventListener("ended", () => { audio.currentTime = 0; paint(); });
  return root;
}

// Lets the user drag start/end handles over a recording. getRange() → [startSec, endSec].
export function rangeEditor(samples, sampleRate, onChange = () => {}) {
  const duration = samples.length / sampleRate;
  let start = 0;
  let end = duration;
  const selection = el("div", { class: "range-selection" });
  const left = el("div", { class: "range-handle", role: "slider", "aria-label": "Start", tabindex: 0 });
  const right = el("div", { class: "range-handle", role: "slider", "aria-label": "End", tabindex: 0 });
  const track = el("div", { class: "range-track" }, bars(peaks(samples, 160), "big"), selection, left, right);
  const summary = el("div", { class: "muted small num" });
  let audio = null;
  const playButton = el("button", { class: "btn btn-small", onclick: () => {
    if (audio && !audio.paused) { audio.pause(); return; }
    const url = URL.createObjectURL(new Blob([encodeWav(trim(samples, sampleRate, start, end), sampleRate)], { type: "audio/wav" }));
    audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    audio.play();
  } }, "Play selection");

  const paint = () => {
    selection.style.left = `${(start / duration) * 100}%`;
    selection.style.width = `${((end - start) / duration) * 100}%`;
    left.style.left = `${(start / duration) * 100}%`;
    right.style.left = `${(end / duration) * 100}%`;
    left.setAttribute("aria-valuenow", start.toFixed(1));
    right.setAttribute("aria-valuenow", end.toFixed(1));
    summary.textContent = `${start.toFixed(1)}–${end.toFixed(1)} s · ${(end - start).toFixed(1)} s selected`;
    onChange(start, end);
  };
  const drag = (which) => (event) => {
    event.preventDefault();
    const box = track.getBoundingClientRect();
    const move = (e) => {
      const t = Math.max(0, Math.min(duration, ((e.clientX - box.left) / box.width) * duration));
      if (which === "start") start = Math.min(t, end - 0.5);
      else end = Math.max(t, start + 0.5);
      paint();
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const keys = (which) => (e) => {
    const step = e.shiftKey ? 1 : 0.1;
    const delta = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
    if (!delta) return;
    if (which === "start") start = Math.max(0, Math.min(end - 0.5, start + delta));
    else end = Math.min(duration, Math.max(start + 0.5, end + delta));
    paint();
  };
  left.addEventListener("pointerdown", drag("start"));
  right.addEventListener("pointerdown", drag("end"));
  left.addEventListener("keydown", keys("start"));
  right.addEventListener("keydown", keys("end"));
  queueMicrotask(paint);
  return { element: el("div", { class: "range" }, track, el("div", { class: "row" }, playButton, summary)), getRange: () => [start, end] };
}
