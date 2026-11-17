import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTime, insertTag, moveLine, pickerLabel, settingsChanges, takeNumber } from "../script.js";

test("moveLine places a line before or after the target", () => {
  assert.deepEqual(moveLine(["a", "b", "c", "d"], "d", "b", false), ["a", "d", "b", "c"]);
  assert.deepEqual(moveLine(["a", "b", "c", "d"], "a", "c", true), ["b", "c", "a", "d"]);
  assert.deepEqual(moveLine(["a", "b", "c"], "b", "b", true), ["a", "b", "c"]);
});

test("pickerLabel names up to two models, then counts", () => {
  const titles = { a: "Chatterbox", b: "OmniVoice", c: "Fish" };
  assert.equal(pickerLabel([], titles), "Choose models");
  assert.equal(pickerLabel(["a", "b"], titles), "Chatterbox, OmniVoice");
  assert.equal(pickerLabel(["a", "b", "c"], titles), "3 models");
});

test("settingsChanges lists only overrides that differ from the base", () => {
  assert.deepEqual(settingsChanges({ x: 0.5, y: 0.9 }, { x: 0.5, y: 0.7 }), ["y"]);
  assert.deepEqual(settingsChanges(undefined, { x: 1 }), []);
});

test("takeNumber reads the number from the file name", () => {
  assert.equal(takeNumber("takes/03-burak-chatterbox-take12.wav"), 12);
  assert.equal(takeNumber("odd.wav"), null);
});

test("formatTime shows minutes and seconds", () => {
  assert.equal(formatTime(14.4), "0:14");
  assert.equal(formatTime(75), "1:15");
});

test("seekTo maps a click position to a time inside the selection", async () => {
  const { seekTo } = await import("../script.js");
  assert.equal(seekTo(0.5, 20), 10);
  assert.equal(seekTo(0.1, 20, 4, 16), 4);
  assert.equal(seekTo(0.95, 20, 4, 16), 16);
  assert.equal(seekTo(-1, 20), 0);
});

test("commonLanguages keeps languages every chosen model supports", async () => {
  const { commonLanguages } = await import("../script.js");
  const models = [
    { name: "a", installed: true, languages: [{ code: "en", name: "English" }, { code: "tr", name: "Turkish" }] },
    { name: "b", installed: true, languages: [{ code: "tr", name: "Turkish" }, { code: "de", name: "German" }] },
    { name: "c", installed: false, languages: [{ code: "fr", name: "French" }] },
  ];
  assert.deepEqual(commonLanguages(models, ["a", "b"]).map((l) => l.code), ["tr"]);
  assert.deepEqual(commonLanguages(models, ["a"]).map((l) => l.code), ["en", "tr"]);
  assert.deepEqual(commonLanguages(models, []).map((l) => l.code), ["tr"]); // no choice: what installed models share
  assert.deepEqual(commonLanguages([], []), []);
});

test("splitSentences groups sentences into chunks under the limit", async () => {
  const { splitSentences } = await import("../script.js");
  assert.deepEqual(splitSentences("One. Two! Three?", 9), ["One. Two!", "Three?"]);
  assert.deepEqual(splitSentences("Short line.", 300), ["Short line."]);
  assert.deepEqual(splitSentences("A sentence... Next one; still going. Last", 20),
    ["A sentence...", "Next one;", "still going. Last"]);
  const long = "word ".repeat(100).trim(); // no punctuation: split on spaces
  const parts = splitSentences(long, 120);
  assert.ok(parts.every((p) => p.length <= 120) && parts.join(" ") === long);
  assert.deepEqual(splitSentences("   ", 10), []);
});

test("findPlayable walks to the next or previous line with a selected take", async () => {
  const { findPlayable } = await import("../script.js");
  const lines = [{ selected: "a" }, { selected: null }, { selected: null }, { selected: "d" }];
  assert.deepEqual(findPlayable(lines, 1, 1), { index: 3, skipped: [1, 2] });
  assert.deepEqual(findPlayable(lines, 0, 1), { index: 0, skipped: [] });
  assert.deepEqual(findPlayable(lines, 2, -1), { index: 0, skipped: [2, 1] });
  assert.deepEqual(findPlayable(lines, 4, 1), { index: -1, skipped: [] });
  assert.deepEqual(findPlayable([{ selected: null }], 0, 1), { index: -1, skipped: [0] });
});

test("insertTag puts the tag at the cursor with spaces around it", () => {
  assert.deepEqual(insertTag("Hello world", 5, 5, "laughter"), { value: "Hello [laughter] world", caret: 16 });
  assert.deepEqual(insertTag("", 0, 0, "laughter"), { value: "[laughter] ", caret: 11 });
  assert.deepEqual(insertTag("Hi ", 3, 3, "sigh"), { value: "Hi [sigh] ", caret: 10 });
  assert.deepEqual(insertTag("Hi there", 3, 8, "sigh"), { value: "Hi [sigh] ", caret: 10 }); // replaces a selection
});
