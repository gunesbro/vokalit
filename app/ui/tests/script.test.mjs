import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTime, moveLine, pickerLabel, settingsChanges, takeNumber } from "../script.js";

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
