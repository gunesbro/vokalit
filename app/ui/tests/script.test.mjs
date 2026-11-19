import { test } from "node:test";
import assert from "node:assert/strict";
import { clampStart, clipsToPlay, overlapRanges, timeToX, xToTime } from "../script.js";
import { descriptionGroups, designLanguage, designText, filterOptions, formatTime, insertTag, isCut, moveLine, parsePause,
  pickSelected,
  pickerLabel, settingsChanges,
  takeNumber } from "../script.js";

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

test("filterOptions puts names starting with the search first, then words, then anywhere; a code matches too", () => {
  const options = [
    { value: "tk", label: "Turkmen" }, { value: "tr", label: "Turkish" }, { value: "ota", label: "Ottoman Turkish" },
    { value: "en", label: "English" }, { value: "zh", label: "Chinese" }, { value: "x", label: "Kurtur" },
  ];
  assert.deepEqual(filterOptions(options, "turk").map((o) => o.value), ["tk", "tr", "ota"]);
  assert.deepEqual(filterOptions(options, "  TUR ").map((o) => o.value), ["tk", "tr", "ota", "x"]);
  assert.deepEqual(filterOptions(options, "zh").map((o) => o.value), ["zh"]);
  assert.equal(filterOptions(options, "").length, 6);
});

test("designLanguage keeps a language the model has, else English, else its first", () => {
  assert.equal(designLanguage(["en", "tr"], "tr"), "tr");
  assert.equal(designLanguage(["en", "de"], "kk"), "en");
  assert.equal(designLanguage(["zh", "ja"], "kk"), "zh");
});

test("designText has its own sentence only for English and Turkish", () => {
  assert.equal(designText("tr").own, true);
  assert.equal(designText("en").own, true);
  assert.deepEqual(designText("de"), { text: designText("en").text, own: false });
});

test("isCut tells a trimmed clip from the whole one", () => {
  assert.equal(isCut(0, 12, 12), false);
  assert.equal(isCut(0.02, 11.99, 12), false);
  assert.equal(isCut(1.5, 12, 12), true);
  assert.equal(isCut(0, 9, 12), true);
});

test("designText sentences are long enough for a 10 s sample", () => {
  // Measured: the Turkish sentence of 22 words came out at 4-9.9 s with OmniVoice.
  for (const code of ["en", "tr"]) assert.ok(designText(code).text.split(/\s+/).length >= 38, code);
});

test("pickSelected prefers the address, then the remembered one if it still exists, then the first", () => {
  assert.equal(pickSelected(["a", "b", "c"], "c", "b"), "c");
  assert.equal(pickSelected(["a", "b", "c"], undefined, "b"), "b");
  assert.equal(pickSelected(["a", "b"], undefined, "gone"), "a");
  assert.equal(pickSelected([], undefined, "b"), undefined);
});

test("descriptionGroups maps a description back to its attribute groups", () => {
  const options = { gender: ["male", "female"], age: ["elderly"], style: ["whisper"], accent: ["british accent"] };
  assert.deepEqual(descriptionGroups(options, "female, elderly, whisper"), { gender: "female", age: "elderly", style: "whisper" });
  assert.deepEqual(descriptionGroups(options, ""), {});
  assert.deepEqual(descriptionGroups(options, "british accent, purple"), { accent: "british accent" });
});

test("parsePause reads seconds between 0 and 10, with a comma or a point", () => {
  assert.equal(parsePause("1.5"), 1.5);
  assert.equal(parsePause(" 0,8 "), 0.8);
  assert.equal(parsePause("0"), 0);
  assert.equal(parsePause("10"), 10);
  for (const bad of ["", "  ", "-1", "10.5", "abc"]) assert.equal(parsePause(bad), null, bad);
});

test("timeToX and xToTime convert with one scale", () => {
  assert.equal(timeToX(2.5, 40), 100);
  assert.equal(xToTime(100, 40), 2.5);
});

test("clampStart keeps a clip inside the source", () => {
  assert.equal(clampStart(-2, 3, 10), 0);
  assert.equal(clampStart(9, 3, 10), 7);
  assert.equal(clampStart(4, 3, 10), 4);
  assert.equal(clampStart(1, 12, 10), 0);
});

test("clipsToPlay schedules from the playhead", () => {
  const clips = [{ id: "a", start: 0, duration: 2 }, { id: "b", start: 3, duration: 2 }, { id: "c", start: 1, duration: 3 },
    { id: "d", start: 0, duration: 1 }];
  assert.deepEqual(clipsToPlay(clips, 1.5), [{ id: "a", offset: 1.5, delay: 0 }, { id: "b", offset: 0, delay: 1.5 },
    { id: "c", offset: 0.5, delay: 0 }]);
});

test("overlapRanges finds where a clip runs into the next", () => {
  assert.deepEqual(overlapRanges([{ start: 4, end: 9 }, { start: 0, end: 4.3 }, { start: 9.5, end: 10 }]), [{ start: 4, end: 4.3 }]);
  assert.deepEqual(overlapRanges([]), []);
});
