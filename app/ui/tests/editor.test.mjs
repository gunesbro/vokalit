import { test } from "node:test";
import assert from "node:assert/strict";
import { joinParts, parseText } from "../editor.js";

const known = ["laughter", "sigh"];

test("parseText splits text and known sound tags", () => {
  assert.deepEqual(parseText("Hi [laughter] there[sigh]", known),
    [{ text: "Hi " }, { tag: "laughter" }, { text: " there" }, { tag: "sigh" }]);
});

test("unknown brackets stay text", () => {
  assert.deepEqual(parseText("[note] hi [cough]", known), [{ text: "[note] hi [cough]" }]);
});

test("joinParts gives back the same text", () => {
  for (const text of ["", "plain", "[sigh]", "a [laughter]\nb [sigh] c", "[laughter][sigh]"]) {
    assert.equal(joinParts(parseText(text, known)), text);
  }
});

test("hyphenated tags are chips, and [surprise] is not [surprise-ah]", () => {
  const tags = ["surprise", "surprise-ah", "speed-slow", "long-pause"];
  assert.deepEqual(parseText("[speed-slow]Hi [surprise] [surprise-ah][long-pause]", tags),
    [{ tag: "speed-slow" }, { text: "Hi " }, { tag: "surprise" }, { text: " " }, { tag: "surprise-ah" }, { tag: "long-pause" }]);
});
