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
