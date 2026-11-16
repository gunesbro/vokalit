import { test } from "node:test";
import assert from "node:assert/strict";
import { encodeWav, peaks, trim } from "../audio.js";

const text = (view, offset, length) => String.fromCharCode(...new Uint8Array(view.buffer, offset, length));

test("encodeWav writes a 16-bit mono PCM header", () => {
  const buffer = encodeWav(new Float32Array(100), 24000);
  const view = new DataView(buffer);
  assert.equal(buffer.byteLength, 44 + 200);
  assert.equal(text(view, 0, 4), "RIFF");
  assert.equal(view.getUint32(4, true), 36 + 200);
  assert.equal(text(view, 8, 4), "WAVE");
  assert.equal(text(view, 12, 4), "fmt ");
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), 24000);
  assert.equal(view.getUint32(28, true), 48000);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(text(view, 36, 4), "data");
  assert.equal(view.getUint32(40, true), 200);
});

test("encodeWav clips samples to the 16-bit range", () => {
  const view = new DataView(encodeWav(Float32Array.from([2, -2, 0.5]), 8000));
  assert.equal(view.getInt16(44, true), 32767);
  assert.equal(view.getInt16(46, true), -32768);
  assert.equal(view.getInt16(48, true), 16384);
});

test("trim keeps the chosen range", () => {
  const samples = new Float32Array(3 * 1000).map((_, i) => i);
  const part = trim(samples, 1000, 1, 2);
  assert.equal(part.length, 1000);
  assert.equal(part[0], 1000);
});

test("trim clamps a range outside the audio", () => {
  assert.equal(trim(new Float32Array(1000), 1000, -1, 5).length, 1000);
});

test("peaks returns one value per bucket between 0 and 1", () => {
  const samples = Float32Array.from({ length: 1000 }, (_, i) => Math.sin(i / 10) * (i < 500 ? 0.2 : 0.9));
  const values = peaks(samples, 10);
  assert.equal(values.length, 10);
  assert.ok(values.every((v) => v >= 0 && v <= 1));
  assert.ok(values[9] > values[0]);
});
