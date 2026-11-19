// A timeline: lanes of clips in seconds, a playhead, a window of `window` seconds that scrolls and follows the
// playhead, zoom, a waveform under the first lane, and dragging clips in time (Dub). Generic, so trimming or more
// lanes can be added later: every position goes through timeToX/xToTime with one scale.
import { el } from "./app.js";
import { clampStart, followWindow, overlapRanges, timeToX, xToTime } from "./script.js";

const MIN_WINDOW = 5; // seconds visible at the closest zoom
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// lanes: [{id, label, draggable, clips: [{id, start, end, state, title}]}]; state "fits" | "long" | "missing" | "source".
export function timeline({ duration, window: shown = 30, lanes = [], onSeek = () => {}, onSelect = () => {},
  onMove = () => {} }) {
  const total = Math.max(duration, 0.001);
  let width = Math.min(shown, total); // seconds visible
  let current = lanes;
  let selected = null;
  let time = 0;
  let wave = null; // {values, perSecond}
  let scale = 1; // px per second

  const labels = el("div", { class: "tl-labels" });
  const content = el("div", { class: "tl-content" });
  const scroller = el("div", { class: "tl-scroll" }, content);
  const canvas = el("canvas", { class: "tl-wave", "aria-hidden": "true" });
  const playhead = el("div", { class: "tl-playhead", "aria-hidden": "true" });
  const range = el("span", { class: "faint small num" });
  const zoomOut = el("button", { type: "button", class: "btn btn-ghost btn-small", title: "Show more time",
    "aria-label": "Zoom out", onclick: () => zoom(2) }, "\u2212");
  const zoomIn = el("button", { type: "button", class: "btn btn-ghost btn-small", title: "Show less time",
    "aria-label": "Zoom in", onclick: () => zoom(0.5) }, "+");
  const element = el("div", { class: "timeline" },
    el("div", { class: "tl-frame" }, labels, el("div", { class: "tl-view" }, canvas, scroller)),
    el("div", { class: "row tl-tools" }, range, el("div", { class: "spacer" }), zoomOut, zoomIn));

  const visibleStart = () => scroller.scrollLeft / scale;
  const reveal = (t) => { scroller.scrollLeft = timeToX(followWindow(visibleStart(), width, t, total), scale); };

  function measure() {
    scale = Math.max(1, scroller.clientWidth) / width;
    content.style.width = `${timeToX(total, scale)}px`;
  }

  function draw() {
    const keep = visibleStart();
    measure();
    labels.replaceChildren(...current.map((lane) => el("div", { class: "tl-label faint small" }, lane.label)));
    content.replaceChildren(...current.map((lane) => {
      const row = el("div", { class: "tl-lane", "data-lane": lane.id });
      row.addEventListener("pointerdown", (e) => {
        if (e.target !== row) return;
        onSeek(Math.min(total, Math.max(0, xToTime(e.offsetX, scale))));
      });
      for (const overlap of overlapRanges(lane.clips)) {
        row.append(el("div", { class: "tl-overlap", style: { left: `${timeToX(overlap.start, scale)}px`,
          width: `${Math.max(2, timeToX(overlap.end - overlap.start, scale))}px` } }));
      }
      for (const clip of lane.clips) row.append(clipNode(lane, clip));
      return row;
    }), playhead);
    scroller.scrollLeft = timeToX(keep, scale);
    paint();
  }

  function clipNode(lane, clip) {
    const node = el("button", { type: "button", class: `tl-clip ${clip.state || ""} ${clip.id === selected ? "selected" : ""}`,
      title: clip.title || "", "data-clip": clip.id,
      style: { left: `${timeToX(clip.start, scale)}px`, width: `${Math.max(3, timeToX(clip.end - clip.start, scale))}px` } });
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") onSelect(lane.id, clip.id); });
    node.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      if (!lane.draggable) return void onSelect(lane.id, clip.id);
      const origin = e.clientX;
      const length = clip.end - clip.start;
      let start = clip.start;
      try { node.setPointerCapture(e.pointerId); } catch { /* a synthetic event has no pointer to capture */ }
      const move = (m) => {
        start = clampStart(clip.start + xToTime(m.clientX - origin, scale), length, total);
        node.style.left = `${timeToX(start, scale)}px`;
      };
      const up = (u) => {
        node.removeEventListener("pointermove", move);
        node.removeEventListener("pointerup", up);
        if (Math.abs(u.clientX - origin) < 3) return void onSelect(lane.id, clip.id); // a click, not a drag
        onMove(clip.id, Math.round(start * 1000) / 1000);
      };
      node.addEventListener("pointermove", move);
      node.addEventListener("pointerup", up);
    });
    return node;
  }

  // The playhead, the visible range, and the waveform of what is in view (the canvas covers only the view).
  function paint() {
    playhead.style.left = `${timeToX(time, scale)}px`;
    const from = visibleStart();
    range.textContent = `${fmt(from)} \u2013 ${fmt(Math.min(total, from + width))}`;
    const pixels = Math.max(1, scroller.clientWidth);
    const lane = content.querySelector(".tl-lane");
    canvas.width = pixels;
    canvas.height = lane ? lane.offsetHeight : 22;
    canvas.style.top = `${lane ? lane.offsetTop : 0}px`;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!wave) return;
    context.fillStyle = getComputedStyle(element).getPropertyValue("--muted").trim() || "#888";
    const middle = canvas.height / 2;
    for (let x = 0; x < pixels; x++) {
      const first = Math.floor(xToTime(scroller.scrollLeft + x, scale) * wave.perSecond);
      const last = Math.max(first + 1, Math.floor(xToTime(scroller.scrollLeft + x + 1, scale) * wave.perSecond));
      let peak = 0;
      for (let i = first; i < last && i < wave.values.length; i++) peak = Math.max(peak, wave.values[i]);
      const height = Math.max(1, peak * (canvas.height - 2));
      context.fillRect(x, middle - height / 2, 1, height);
    }
  }

  function zoom(factor) {
    const centre = visibleStart() + width / 2;
    width = Math.min(total, Math.max(MIN_WINDOW, width * factor));
    draw();
    scroller.scrollLeft = timeToX(Math.max(0, centre - width / 2), scale);
    paint();
    zoomIn.disabled = width <= MIN_WINDOW;
    zoomOut.disabled = width >= total;
  }

  scroller.addEventListener("scroll", paint);
  const resize = new ResizeObserver(() => {
    if (!element.isConnected) return resize.disconnect();
    draw();
  });
  resize.observe(scroller);
  zoomOut.disabled = width >= total;
  draw();
  return {
    element,
    setLanes(next) { current = next; draw(); },
    setWave(values, perSecond) { wave = { values, perSecond }; paint(); },
    // `follow` keeps the playhead in view (while playing, or after a seek).
    setTime(t, follow = true) {
      time = t;
      if (follow) reveal(t);
      paint();
    },
    select(clipId, show = false) {
      selected = clipId;
      for (const node of content.querySelectorAll(".tl-clip")) node.classList.toggle("selected", node.dataset.clip === clipId);
      const node = content.querySelector(`.tl-clip[data-clip="${clipId}"]`);
      if (show && node) reveal(parseFloat(node.style.left) / scale);
    },
  };
}
