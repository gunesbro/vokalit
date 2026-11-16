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
