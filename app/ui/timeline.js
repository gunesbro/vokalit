// A timeline: lanes of clips over the source's duration, a playhead, and dragging clips in time (Dub).
// Generic on purpose (lanes and clips in seconds, one scale), so zoom, trimming and more lanes can be added later.
import { el } from "./app.js";
import { clampStart, overlapRanges, timeToX, xToTime } from "./script.js";

const LABEL = 64; // px: the lane names column

// lanes: [{id, label, draggable, clips: [{id, start, end, state, title}]}]; state "fits" | "long" | "missing".
export function timeline({ duration, lanes = [], onSeek = () => {}, onSelect = () => {}, onMove = () => {} }) {
  const tracks = el("div", { class: "tl-tracks" });
  const playhead = el("div", { class: "tl-playhead", "aria-hidden": "true" });
  const body = el("div", { class: "tl-body" }, tracks, playhead);
  const element = el("div", { class: "timeline" }, body);
  element.style.setProperty("--tl-label", `${LABEL}px`);
  let current = lanes;
  let selected = null;
  let time = 0;
  let scale = 1; // px per second: the width over the duration (zoom would change only this)

  const measure = () => { scale = Math.max(1, body.clientWidth - LABEL) / Math.max(duration, 0.001); };

  function draw() {
    measure();
    tracks.replaceChildren(...current.map((lane) => {
      const row = el("div", { class: "tl-lane", "data-lane": lane.id });
      row.addEventListener("pointerdown", (e) => {
        if (e.target !== row) return;
        onSeek(Math.min(duration, Math.max(0, xToTime(e.offsetX, scale))));
      });
      for (const range of overlapRanges(lane.clips)) {
        row.append(el("div", { class: "tl-overlap", style: { left: `${timeToX(range.start, scale)}px`,
          width: `${Math.max(2, timeToX(range.end - range.start, scale))}px` } }));
      }
      for (const clip of lane.clips) row.append(clipNode(lane, clip));
      return el("div", { class: "tl-row" }, el("div", { class: "tl-label faint small" }, lane.label), row);
    }));
    paintTime();
  }

  function clipNode(lane, clip) {
    const node = el("button", { type: "button", class: `tl-clip ${clip.state || ""} ${clip.id === selected ? "selected" : ""}`,
      title: clip.title || "", "data-clip": clip.id,
      style: { left: `${timeToX(clip.start, scale)}px`, width: `${Math.max(3, timeToX(clip.end - clip.start, scale))}px` } });
    node.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      if (!lane.draggable) return void onSelect(lane.id, clip.id);
      const origin = e.clientX;
      const length = clip.end - clip.start;
      let start = clip.start;
      node.setPointerCapture(e.pointerId);
      const move = (m) => {
        start = clampStart(clip.start + xToTime(m.clientX - origin, scale), length, duration);
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

  function paintTime() {
    playhead.style.left = `calc(var(--tl-label) + ${timeToX(time, scale)}px)`;
  }

  new ResizeObserver(() => element.isConnected && draw()).observe(body);
  draw();
  return {
    element,
    setLanes(lanes) { current = lanes; draw(); },
    setTime(t) { time = t; paintTime(); },
    select(clipId) { selected = clipId; draw(); },
  };
}
