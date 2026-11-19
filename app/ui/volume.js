// The app's playback volume: one level for every sound the app plays (players, Studio playback, the Dub preview), so
// listening does not need the system volume turned down. Exports and generated files are not touched.
import { preference, savePreference } from "./preferences.js";
import { volumeGain } from "./script.js";

let percent = 100; // until the preferences are loaded (loadMasterVolume)
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

const clamp = (value) => Math.min(100, Math.max(0, Math.round(value)));

function apply(value) {
  percent = clamp(value);
  each((target) => level(target, volumeGain(percent)));
}

// The volume kept from the last run; anything that is not a number is full volume.
export function loadMasterVolume() {
  const kept = Number(preference("volume", 100));
  apply(Number.isFinite(kept) ? kept : 100);
}

export function setMasterVolume(value) {
  apply(value);
  savePreference("volume", percent);
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
