// Pure helpers for the Studio screen (tested with node --test).

// Moves line `id` before (or after) `targetId`; returns the new order.
export function moveLine(order, id, targetId, after) {
  if (id === targetId) return [...order];
  const rest = order.filter((x) => x !== id);
  const index = rest.indexOf(targetId) + (after ? 1 : 0);
  return [...rest.slice(0, index), id, ...rest.slice(index)];
}

export function pickerLabel(selected, titles) {
  if (!selected.length) return "Choose models";
  if (selected.length > 2) return `${selected.length} models`;
  return selected.map((name) => titles[name] || name).join(", ");
}

// Keys of `overrides` whose value differs from `base`.
export function settingsChanges(overrides, base) {
  return Object.entries(overrides || {}).filter(([key, value]) => base[key] !== value).map(([key]) => key);
}

export function takeNumber(file) {
  const match = file.match(/take(\d+)\.wav$/);
  return match ? Number(match[1]) : null;
}

export function formatTime(seconds) {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

// Time for a click at `fraction` (0..1) of a waveform, kept inside [start, end].
export function seekTo(fraction, duration, start = 0, end = duration) {
  return Math.min(end, Math.max(start, fraction * duration));
}

// Languages that every chosen model supports (no choice: every installed model), sorted by name.
export function commonLanguages(models, names) {
  const chosen = models.filter((m) => names.includes(m.name));
  const pool = chosen.length ? chosen : models.filter((m) => m.installed);
  if (!pool.length) return [];
  const shared = pool.slice(1).reduce((list, m) => list.filter((l) => m.languages.some((x) => x.code === l.code)),
    pool[0].languages);
  return [...shared].sort((a, b) => a.name.localeCompare(b.name));
}

// Splits long text into chunks of whole sentences, each at most `max` characters when possible.
// A single sentence longer than `max` is split between words.
export function splitSentences(text, max) {
  const sentences = text.trim().split(/(?<=[.!?…;:])\s+/).filter(Boolean);
  const pieces = sentences.flatMap((sentence) => {
    if (sentence.length <= max) return [sentence];
    const words = [];
    let current = "";
    for (const word of sentence.split(/\s+/)) {
      if (current && `${current} ${word}`.length > max) { words.push(current); current = word; }
      else current = current ? `${current} ${word}` : word;
    }
    return current ? [...words, current] : words;
  });
  const chunks = [];
  for (const piece of pieces) {
    const last = chunks[chunks.length - 1];
    if (last && `${last} ${piece}`.length <= max) chunks[chunks.length - 1] = `${last} ${piece}`;
    else chunks.push(piece);
  }
  return chunks;
}

// From line `from`, steps (+1 or -1) to the first line with a selected take.
// Returns its index (-1 when there is none) and the indexes passed over because they had no take.
export function findPlayable(lines, from, step) {
  const skipped = [];
  for (let i = from; i >= 0 && i < lines.length; i += step) {
    if (lines[i].selected) return { index: i, skipped };
    skipped.push(i);
  }
  return { index: -1, skipped };
}

// Puts "[tag]" where the cursor is (replacing a selection), with a space on each side unless one is already there.
// Returns the new text and the cursor position after the tag (and an added space).
export function insertTag(value, start, end, tag) {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = !after || !/^\s/.test(after) ? " " : "";
  const inserted = `${lead}[${tag}]${trail}`;
  return { value: before + inserted + after, caret: before.length + inserted.length };
}

// Options matching a search, best first: the code itself, names that start with it, a word that starts with it, then
// names containing it. An empty search keeps every option in order.
export function filterOptions(options, search) {
  const q = search.trim().toLowerCase();
  if (!q) return options;
  const rank = (o) => {
    const label = o.label.toLowerCase();
    if (o.value.toLowerCase() === q) return 0;
    if (label.startsWith(q)) return 1;
    if (label.split(/[\s(\-]+/).some((word) => word.startsWith(q))) return 2;
    return label.includes(q) ? 3 : null;
  };
  return options.map((o) => [rank(o), o]).filter(([r]) => r !== null).sort((a, b) => a[0] - b[0]).map(([, o]) => o);
}

// What designed voices read: about 15-20 seconds of speech, so a candidate is long enough to keep as a sample even
// when the model speaks fast.
const DESIGN_TEXT = {
  en: "The morning was quiet, and the city was just waking up. I poured a cup of coffee, opened the window, "
    + "and listened to the rain for a while before the long day began. Somewhere down the street, a bus stopped, "
    + "a dog barked, and an old radio started playing a familiar song.",
  tr: "Sabah sessizdi ve \u015fehir yeni uyan\u0131yordu. Bir fincan kahve koydum, pencereyi a\u00e7t\u0131m ve uzun "
    + "g\u00fcn ba\u015flamadan \u00f6nce bir s\u00fcre ya\u011fmuru dinledim. Hava serindi ve sokaklar bombo\u015ftu. "
    + "Soka\u011f\u0131n sonunda bir otob\u00fcs durdu, bir k\u00f6pek havlad\u0131 ve eski bir radyoda tan\u0131d\u0131k "
    + "bir \u015fark\u0131 \u00e7almaya ba\u015flad\u0131. Kahvemi bitirip pencereyi kapatt\u0131m ve i\u015fe gitmek "
    + "i\u00e7in haz\u0131rlanmaya ba\u015flad\u0131m.",
};
// The sentence for a language; own is false when it falls back to English.
export const designText = (language) => ({ text: DESIGN_TEXT[language] || DESIGN_TEXT.en, own: language in DESIGN_TEXT });

// The design language after a model change: the current one if the model has it, else English, else its first.
export const designLanguage = (codes, current) => (codes.includes(current) ? current : codes.includes("en") ? "en" : codes[0]);

// Whether a review range cuts the clip (more than a hair at either end), so its known text may no longer match.
export const isCut = (start, end, duration) => start > 0.05 || end < duration - 0.05;

// Which list item a screen opens: the one in the address, else the one open last time if it still exists, else the
// first.
export const pickSelected = (ids, fromAddress, remembered) =>
  fromAddress || (ids.includes(remembered) ? remembered : ids[0]);

// An OmniVoice description ("female, elderly") as {group: attribute}, to fill the selects again.
export function descriptionGroups(options, description) {
  const groups = {};
  for (const item of description.split(",").map((part) => part.trim()).filter(Boolean)) {
    const group = Object.keys(options).find((g) => options[g].includes(item));
    if (group) groups[group] = item;
  }
  return groups;
}

// A pause typed in seconds ("1.5" or "1,5"), or null unless it is a number from 0 to 10.
export function parsePause(text) {
  const value = Number(text.trim().replace(",", "."));
  return text.trim() && Number.isFinite(value) && value >= 0 && value <= 10 ? value : null;
}

// --- Timeline (Dub): seconds <-> pixels with one scale (px per second), so zoom is a change of scale. ---

export const timeToX = (t, scale) => t * scale;
export const xToTime = (x, scale) => x / scale;

// A clip's start kept inside the source: 0 <= start <= duration - length (0 when the clip is longer than the source).
export const clampStart = (start, length, duration) => Math.min(Math.max(0, start), Math.max(0, duration - length));

// Clips ({id, start, duration}) to start at playhead `t`: playing now (offset into the clip) or later (delay).
export const clipsToPlay = (clips, t) => clips
  .filter((c) => c.start + c.duration > t)
  .map((c) => (c.start <= t ? { id: c.id, offset: t - c.start, delay: 0 } : { id: c.id, offset: 0, delay: c.start - t }));

// Where a clip ({start, end}) runs into the next one by start time.
export function overlapRanges(clips) {
  const sorted = [...clips].sort((a, b) => a.start - b.start);
  const ranges = [];
  for (let i = 0; i + 1 < sorted.length; i++) {
    const [clip, next] = [sorted[i], sorted[i + 1]];
    if (clip.end > next.start) ranges.push({ start: next.start, end: Math.min(clip.end, next.end) });
  }
  return ranges;
}

// Several pasted lines fill consecutive sentences from `fromIndex`, one non-empty line each; extra lines are dropped.
export function pasteTranslations(clipIds, fromIndex, text) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return Object.fromEntries(lines.slice(0, clipIds.length - fromIndex).map((line, i) => [clipIds[fromIndex + i], line]));
}

// The transcript to give a translation tool: an instruction, then the sentences numbered, one per line.
export const transcriptForTranslation = (sentences, languageName) =>
  `Translate each numbered line into ${languageName}. Keep the numbers, one line per sentence.\n\n`
  + sentences.map((text, i) => `${i + 1}. ${text}`).join("\n");

// A translation tool's reply as one text per sentence (null where none): numbered lines ("3." "3)" "3 -") go to their
// number, other lines are ignored; without any numbers, the non-empty lines are taken in order.
export function parseTranslations(reply, count) {
  const texts = Array(count).fill(null);
  const lines = reply.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const numbered = lines.map((line) => line.match(/^(\d+)\s*[.):-]\s*(.+)$/)).filter(Boolean);
  if (numbered.length) {
    for (const [, number, text] of numbered) if (number >= 1 && number <= count) texts[number - 1] = text.trim();
  } else {
    lines.slice(0, count).forEach((line, i) => { texts[i] = line; });
  }
  return { texts, missing: texts.flatMap((text, i) => (text === null ? [i + 1] : [])) };
}

// Undo/redo of steps {label, undo, redo} (async). A new step clears redo; past `limit` the oldest step is dropped. A step
// whose undo or redo fails stays where it was.
export function createHistory(limit = 100) {
  const done = [];
  const undone = [];
  return {
    push(step) {
      done.push(step);
      if (done.length > limit) done.shift();
      undone.length = 0;
    },
    async undo() {
      const step = done.at(-1);
      if (!step) return null;
      await step.undo();
      undone.push(done.pop());
      return step.label;
    },
    async redo() {
      const step = undone.at(-1);
      if (!step) return null;
      await step.redo();
      done.push(undone.pop());
      return step.label;
    },
    undoLabel: () => done.at(-1)?.label ?? null,
    redoLabel: () => undone.at(-1)?.label ?? null,
  };
}

// Dub sentences shown by a filter: "all", "untranslated", "missing" (no take) or "long" (runs into the next).
export function clipFilter(clips, fit, name) {
  const keep = {
    all: () => true,
    untranslated: (c) => !c.translation.trim(),
    missing: (c) => fit[c.id]?.state === "missing",
    long: (c) => fit[c.id]?.state === "long",
  }[name] || (() => true);
  return clips.filter(keep).map((c) => c.id);
}

// The clip ({id, start, length}) under the playhead `t`, or null.
export const activeClip = (clips, t) => clips.find((c) => t >= c.start && t < c.start + c.length)?.id ?? null;

// A timeline window's start (seconds) that keeps `t` visible: unchanged while t is inside, else a page starting at t
// (kept within the duration).
export function followWindow(start, width, t, duration) {
  if (t >= start && t < start + width) return start;
  return Math.max(0, Math.min(t, duration - width));
}
