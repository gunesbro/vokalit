import { test } from "node:test";
import assert from "node:assert/strict";
import { activeClip, clampSize, clipFilter, createHistory, followWindow, onlyModel, volumeRamps } from "../script.js";
import { clampStart, clipsToPlay, overlapRanges, parseTranslations, pasteTranslations, timeToX, transcriptForTranslation,
  xToTime } from "../script.js";
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

test("pasteTranslations fills the following sentences, one line each", () => {
  assert.deepEqual(pasteTranslations(["d1", "d2", "d3"], 1, "Hello.\n\nHow are you?\nExtra"), { d2: "Hello.", d3: "How are you?" });
  assert.deepEqual(pasteTranslations(["d1"], 0, "  One line  "), { d1: "One line" });
});

test("transcriptForTranslation numbers the sentences under an instruction", () => {
  assert.equal(transcriptForTranslation(["Merhaba.", "Evet."], "English"),
    "Translate each numbered line into English. Keep the numbers, one line per sentence.\n\n1. Merhaba.\n2. Evet.");
});

test("parseTranslations places numbered lines by number and reports the missing ones", () => {
  const reply = "Here you go:\n\n1. Hello.\n3) I wanted this.\n 2 - Yes.\n7. Extra";
  assert.deepEqual(parseTranslations(reply, 4), { texts: ["Hello.", "Yes.", "I wanted this.", null], missing: [4] });
});

test("parseTranslations without numbers takes the lines in order", () => {
  assert.deepEqual(parseTranslations("Hello.\n\nYes.\n", 3), { texts: ["Hello.", "Yes.", null], missing: [3] });
});

test("createHistory undoes and redoes in order, and a new step clears redo", async () => {
  const log = [];
  const step = (name) => ({ label: name, undo: async () => log.push(`undo ${name}`), redo: async () => log.push(`redo ${name}`) });
  const h = createHistory();
  h.push(step("a"));
  h.push(step("b"));
  assert.equal(h.undoLabel(), "b");
  assert.equal(await h.undo(), "b");
  assert.equal(h.redoLabel(), "b");
  assert.equal(await h.redo(), "b");
  await h.undo();
  h.push(step("c"));
  assert.equal(h.redoLabel(), null);
  assert.equal(await h.undo(), "c");
  assert.equal(await h.undo(), "a");
  assert.equal(await h.undo(), null);
  assert.deepEqual(log, ["undo b", "redo b", "undo b", "undo c", "undo a"]);
});

test("createHistory keeps the last steps up to its limit", async () => {
  const h = createHistory(2);
  for (const name of ["a", "b", "c"]) h.push({ label: name, undo: async () => {}, redo: async () => {} });
  assert.equal(await h.undo(), "c");
  assert.equal(await h.undo(), "b");
  assert.equal(await h.undo(), null);
});

test("createHistory keeps a step whose undo failed", async () => {
  const h = createHistory();
  h.push({ label: "a", undo: async () => { throw new Error("offline"); }, redo: async () => {} });
  await assert.rejects(h.undo(), /offline/);
  assert.equal(h.undoLabel(), "a");
});

test("clipFilter picks untranslated, missing and long sentences", () => {
  const clips = [{ id: "d1", translation: "Hi." }, { id: "d2", translation: " " }, { id: "d3", translation: "Yes." }];
  const fit = { d1: { state: "fits" }, d2: { state: "missing" }, d3: { state: "long" } };
  assert.deepEqual(clipFilter(clips, fit, "all"), ["d1", "d2", "d3"]);
  assert.deepEqual(clipFilter(clips, fit, "untranslated"), ["d2"]);
  assert.deepEqual(clipFilter(clips, fit, "missing"), ["d2"]);
  assert.deepEqual(clipFilter(clips, fit, "long"), ["d3"]);
});

test("activeClip finds the sentence under the playhead", () => {
  const clips = [{ id: "a", start: 0, length: 2 }, { id: "b", start: 3, length: 2 }];
  assert.equal(activeClip(clips, 1.5), "a");
  assert.equal(activeClip(clips, 2.5), null);
  assert.equal(activeClip(clips, 4.99), "b");
});

test("followWindow keeps the playhead visible, a page at a time", () => {
  assert.equal(followWindow(0, 30, 10, 100), 0);
  assert.equal(followWindow(0, 30, 31, 100), 31);
  assert.equal(followWindow(40, 30, 10, 100), 10);
  assert.equal(followWindow(0, 30, 95, 100), 70);
});

test("createHistory hands back what a step's undo and redo return", async () => {
  const h = createHistory();
  h.push({ label: "a", undo: async () => "before", redo: async () => "after" });
  assert.deepEqual(await h.undo(), "a");
  assert.equal(h.lastResult(), "before");
  await h.redo();
  assert.equal(h.lastResult(), "after");
});

test("createHistory ignores an undo while another is running", async () => {
  const log = [];
  let release;
  const h = createHistory();
  h.push({ label: "s1", undo: async () => log.push("undo s1"), redo: async () => {} });
  h.push({ label: "s2", undo: () => new Promise((done) => { release = () => { log.push("undo s2"); done(); }; }), redo: async () => {} });
  const first = h.undo();
  assert.equal(await h.undo(), null);
  release();
  assert.equal(await first, "s2");
  assert.deepEqual(log, ["undo s2"]);
  assert.equal(h.undoLabel(), "s1");
});

test("createHistory drops the steps of something that no longer exists", async () => {
  const h = createHistory();
  const step = (label, language) => ({ label, language, undo: async () => {}, redo: async () => {} });
  h.push(step("a", "en"));
  h.push(step("b", "de"));
  h.push(step("c", "de"));
  await h.undo();
  h.drop((s) => s.language === "de");
  assert.equal(h.undoLabel(), "a");
  assert.equal(h.redoLabel(), null);
});

test("clipFilter leaves kept sentences out of the work to do", () => {
  const clips = [{ id: "d1", translation: "" }, { id: "d2", translation: "" }];
  const fit = { d1: { state: "kept" }, d2: { state: "missing" } };
  assert.deepEqual(clipFilter(clips, fit, "untranslated"), ["d2"]);
  assert.deepEqual(clipFilter(clips, fit, "missing"), ["d2"]);
  assert.deepEqual(clipFilter(clips, fit, "kept"), ["d1"]);
});

test("volumeRamps raises the original to full volume over kept stretches", () => {
  assert.deepEqual(volumeRamps([{ start: 2, end: 4 }], 0.15, 0.05),
    [[0, 0.15], [1.95, 0.15], [2, 1], [4, 1], [4.05, 0.15]]);
});

test("onlyModel picks the one installed model that speaks the language", () => {
  const a = { name: "a", languages: [{ code: "en", name: "English" }, { code: "tr", name: "Turkish" }] };
  const b = { name: "b", languages: [{ code: "en", name: "English" }] };
  assert.equal(onlyModel([a, b], "tr"), "a");
  assert.equal(onlyModel([a, b], "en"), null); // two speak it: the user chooses
  assert.equal(onlyModel([a, b], "de"), null);
  assert.equal(onlyModel([], "en"), null);
});

test("clampSize keeps a size between its limits, the minimum winning when they cross", () => {
  assert.equal(clampSize(500, 320, 800), 500);
  assert.equal(clampSize(100, 320, 800), 320);
  assert.equal(clampSize(900, 320, 800), 800);
  assert.equal(clampSize(400, 320, 200), 320);
});
