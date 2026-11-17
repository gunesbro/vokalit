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
