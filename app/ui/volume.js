// The app's playback volume: one level for every sound the app plays (players, Studio playback, the Dub preview), so
// listening does not need the system volume turned down. Exports and generated files are not touched.
import { volumeGain } from "./script.js";

const KEY = "vokalit.volume";
let percent = (() => {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === null ? 100 : Math.min(100, Math.max(0, Number(saved) || 0));
  } catch { return 100; }
})();
const followers = new Set(); // WeakRefs to <audio> elements and gain nodes that play at the volume

export const masterVolume = () => percent;

function each(apply) {
  for (const ref of followers) {
    const target = ref.deref();
    if (target) apply(target);
    else followers.delete(ref);
  }
}

const level = (target, gain) => {
  if ("gain" in target) target.gain.value = gain;
  else target.volume = gain;
};

export function setMasterVolume(value) {
  percent = Math.min(100, Math.max(0, Math.round(value)));
  try { localStorage.setItem(KEY, String(percent)); } catch { /* storage may be unavailable */ }
  each((target) => level(target, volumeGain(percent)));
}

// An <audio> plays at the volume, and follows it when it changes.
export function trackAudio(audio) {
  level(audio, volumeGain(percent));
  followers.add(new WeakRef(audio));
  return audio;
}

// Where a Web Audio graph should end instead of context.destination: a gain at the volume, following it.
export function outputFor(context) {
  const node = context.createGain();
  level(node, volumeGain(percent));
  node.connect(context.destination);
  followers.add(new WeakRef(node));
  return node;
}
