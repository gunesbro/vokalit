// Waveform bars, a small player, and a trim range editor.
import { el, icon, ICONS } from "./app.js";
import { decode, peaks } from "./audio.js";
import { seekTo } from "./script.js";

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

// One Audio per file, shared by every player showing it, so a redraw keeps playback going. When no player
// for a file is on the page any more (its take or sample was deleted, or the screen changed), it stops.
const live = new Map(); // url -> { audio, owners: Map<Element, AbortController> }

function audioFor(url, owner) {
  let entry = live.get(url);
  if (!entry) {
    entry = { audio: new Audio(url), owners: new Map() };
    live.set(url, entry);
  }
  const controller = new AbortController();
  entry.owners.set(owner, controller);
  return { audio: entry.audio, signal: controller.signal };
}

function sweep() {
  for (const [url, entry] of live) {
    for (const [owner, controller] of entry.owners) {
      if (!owner.isConnected) { controller.abort(); entry.owners.delete(owner); }
    }
    if (!entry.owners.size) { entry.audio.pause(); entry.audio.removeAttribute("src"); live.delete(url); }
  }
}
setInterval(sweep, 250);

// Pauses every player (used when "Play all" starts).
export function pauseAll() {
  for (const entry of live.values()) entry.audio.pause();
}

// Stops a file right away (before deleting it).
export function stopAudio(url) {
  const entry = live.get(url);
  if (entry) { entry.audio.pause(); entry.audio.currentTime = 0; }
}

// A play button + waveform that fills as it plays. `selected` uses the accent color.
export function player(url, { buckets = 48, selected = false, label = "Play", showTime = true } = {}) {
  const wave = el("div", { class: `wave ${selected ? "selected" : ""}`, "aria-hidden": "true" });
  const button = el("button", { class: "play", "aria-label": label, title: label, onclick: () => (audio.paused ? audio.play() : audio.pause()) });
  // The button is the owner: Characters moves it out of the player into its own column.
  const { audio, signal } = audioFor(url, button);
  const paintButton = () => button.replaceChildren(icon(audio.paused ? ICONS.play : ICONS.pause, 12));
  paintButton();
  const time = el("span", { class: "time num" });
  const root = el("div", { class: "player" }, button, wave, showTime && time);
  urlPeaks(url, buckets).then((values) => {
    wave.replaceChildren(...values.map((v) => el("span", { style: { height: `${Math.max(12, Math.round(v * 100))}%` } })));
    paint();
  }).catch(() => wave.replaceChildren(el("span", { class: "faint small" }, "Cannot read audio")));
  const paint = () => {
    const played = audio.duration ? audio.currentTime / audio.duration : 0;
    [...wave.children].forEach((bar, i, all) => bar.classList.toggle("played", i / all.length < played));
    time.textContent = fmt(audio.paused && !audio.currentTime ? audio.duration || 0 : audio.currentTime);
  };
  audio.addEventListener("loadedmetadata", paint, { signal });
  audio.addEventListener("timeupdate", paint, { signal });
  audio.addEventListener("play", paintButton, { signal });
  // Lets "Play all" step aside when a single take or sample is played.
  audio.addEventListener("play", () => document.dispatchEvent(new CustomEvent("vokalit-player-play")), { signal });
  audio.addEventListener("pause", paintButton, { signal });
  audio.addEventListener("ended", () => { audio.currentTime = 0; paint(); }, { signal });
  paint();
  // Clicking the waveform jumps there and plays from that point.
  wave.style.cursor = "pointer";
  wave.addEventListener("click", (e) => {
    if (!audio.duration) return;
    const box = wave.getBoundingClientRect();
    audio.currentTime = seekTo((e.clientX - box.left) / box.width, audio.duration);
    paint();
    if (audio.paused) audio.play();
  });
  return root;
}

// Plays [start, end] of a recording with sample accuracy. Same small interface as an <audio> element:
// paused, currentTime (get/set), play(), pause(); plus close(). onChange runs on play, pause and the natural end.
function clipPlayer(samples, sampleRate, range, onChange) {
  const duration = samples.length / sampleRate;
  let context = null;
  let buffer = null;
  let source = null;
  let startedAt = 0;
  let offset = 0;
  const position = () => (source ? offset + (context.currentTime - startedAt) : offset);
  const stopSource = () => {
    if (!source) return;
    source.onended = null;
    try { source.stop(); } catch { /* already stopped */ }
    source.disconnect();
    source = null;
  };
  return {
    get paused() { return !source; },
    get currentTime() { return Math.min(position(), duration); },
    set currentTime(t) {
      const playing = !!source;
      stopSource();
      offset = t;
      if (playing) this.play();
    },
    play() {
      context ||= new AudioContext();
      if (!buffer) {
        buffer = context.createBuffer(1, samples.length, sampleRate);
        buffer.copyToChannel(samples, 0);
      }
      const [start, end] = range();
      if (offset < start || offset >= end - 0.05) offset = start;
      stopSource();
      source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.onended = () => { source = null; offset = range()[0]; onChange(); };
      context.resume();
      startedAt = context.currentTime;
      source.start(0, offset, end - offset);
      onChange();
    },
    pause() {
      if (!source) return;
      offset = position();
      stopSource();
      onChange();
    },
    close() { stopSource(); context?.close(); },
  };
}

// Lets the user drag start/end handles over a recording and play the selection,
// with a playhead; clicking the waveform moves the playhead. getRange() → [startSec, endSec].
export function rangeEditor(samples, sampleRate, onChange = () => {}) {
  const duration = samples.length / sampleRate;
  let start = 0;
  let end = duration;
  // Web Audio plays exactly start..end (an <audio> element could only be stopped a few hundred ms late).
  const audio = clipPlayer(samples, sampleRate, () => [start, end], () => { paintButton(); paintHead(); });
  const selection = el("div", { class: "range-selection" });
  const playhead = el("div", { class: "range-playhead" });
  const left = el("div", { class: "range-handle", role: "slider", "aria-label": "Start", tabindex: 0 });
  const right = el("div", { class: "range-handle", role: "slider", "aria-label": "End", tabindex: 0 });
  const track = el("div", { class: "range-track" }, bars(peaks(samples, 160), "big"), selection, playhead, left, right);
  const summary = el("div", { class: "muted small num" });
  const clock = el("span", { class: "num small" });
  const playButton = el("button", { class: "btn btn-small", onclick: () => (audio.paused ? play() : audio.pause()) });

  const pct = (t) => `${(t / duration) * 100}%`;
  const paintButton = () => playButton.replaceChildren(icon(audio.paused ? ICONS.play : ICONS.pause, 12),
    audio.paused ? "Play selection" : "Pause");
  const paintHead = () => {
    playhead.style.left = pct(audio.currentTime);
    clock.textContent = `${fmt(audio.currentTime)}.${Math.floor((audio.currentTime % 1) * 10)}`;
  };
  function play() {
    if (audio.currentTime < start || audio.currentTime >= end - 0.05) audio.currentTime = start;
    audio.play();
  }
  const paint = () => {
    selection.style.left = pct(start);
    selection.style.width = pct(end - start);
    left.style.left = pct(start);
    right.style.left = pct(end);
    left.setAttribute("aria-valuenow", start.toFixed(1));
    right.setAttribute("aria-valuenow", end.toFixed(1));
    summary.textContent = `${start.toFixed(1)}\u2013${end.toFixed(1)} s \u00b7 ${(end - start).toFixed(1)} s selected`;
    if (audio.currentTime < start || audio.currentTime > end) audio.currentTime = start;
    paintHead();
    onChange(start, end);
  };
  // Playhead follows while playing; the player is closed when the editor leaves the page.
  const follow = () => { if (!audio.paused) paintHead(); if (track.isConnected) requestAnimationFrame(follow); else audio.close(); };

  track.addEventListener("click", (e) => {
    if (e.target === left || e.target === right) return;
    const box = track.getBoundingClientRect();
    audio.currentTime = seekTo((e.clientX - box.left) / box.width, duration, start, end);
    paintHead();
  });
  const drag = (which) => (event) => {
    event.preventDefault();
    event.stopPropagation();
    audio.pause(); // moving a handle while playing would play past the new end
    const box = track.getBoundingClientRect();
    const move = (e) => {
      const t = seekTo((e.clientX - box.left) / box.width, duration);
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
    audio.pause();
    if (which === "start") start = Math.max(0, Math.min(end - 0.5, start + delta));
    else end = Math.min(duration, Math.max(start + 0.5, end + delta));
    paint();
  };
  left.addEventListener("pointerdown", drag("start"));
  right.addEventListener("pointerdown", drag("end"));
  left.addEventListener("click", (e) => e.stopPropagation());
  right.addEventListener("click", (e) => e.stopPropagation());
  left.addEventListener("keydown", keys("start"));
  right.addEventListener("keydown", keys("end"));
  paintButton();
  queueMicrotask(() => { paint(); requestAnimationFrame(follow); });
  return {
    element: el("div", { class: "range" }, track,
      el("div", { class: "row" }, playButton, clock, summary,
        el("span", { class: "faint small" }, "Click the waveform to move the playhead."))),
    getRange: () => [start, end],
  };
}
