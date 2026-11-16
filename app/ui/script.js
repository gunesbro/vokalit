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
