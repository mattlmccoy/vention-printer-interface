import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { captureFailureMessage, contentStats, truncationReason } from "./capture_diagnostics.ts";

const rgba = (greys: number[]): Uint8ClampedArray =>
  new Uint8ClampedArray(greys.flatMap((g) => [g, g, g, 255]));

test("a flat frame is blank and says how flat", () => {
  const s = contentStats(rgba(Array(100).fill(128)));
  assert.equal(s.ok, false);
  assert.equal(s.range, 0);
  assert.equal(s.std, 0);
  assert.equal(s.mean, 128);
});

test("a frame with real contrast has content (same rule as before: range >= 20 and std >= 8)", () => {
  const s = contentStats(rgba([...Array(50).fill(100), ...Array(50).fill(140)]));
  assert.equal(s.ok, true);
  assert.equal(s.range, 40);
  assert.equal(s.std, 20);
});

test("low contrast just under the thresholds is rejected", () => {
  const s = contentStats(rgba([...Array(50).fill(120), ...Array(50).fill(134)]));
  assert.equal(s.ok, false); // range 14 < 20
});

test("the message names every browser attempt and the fallback result", () => {
  const m = captureFailureMessage({
    layer: 1,
    attempts: ["photo: looked blank (range 12, std 5, mean 131)", "frame: NotReadableError: Could not start video source", "video: no picture (0x0)"],
    upload: null,
    fallback: "503 science capture service is not running",
  });
  assert.equal(m,
    "Science capture failed for layer 1 · browser: photo: looked blank (range 12, std 5, mean 131); " +
    "frame: NotReadableError: Could not start video source; video: no picture (0x0) · " +
    "operator fallback: 503 science capture service is not running");
});

test("an upload refusal is reported as such (the still itself was fine)", () => {
  const m = captureFailureMessage({ layer: 4, attempts: [], upload: "413 payload too large", fallback: "503 science capture service is not running" });
  assert.match(m, /browser still taken but the upload was refused: 413 payload too large/);
  assert.match(m, /operator fallback: 503/);
});

test("no browser detail is said out loud, never left blank", () => {
  const m = captureFailureMessage({ layer: 2, attempts: [], upload: null, fallback: "boom" });
  assert.match(m, /browser: no reason recorded/);
});

// Real-frame fixtures (downsampled to the browser check's 64x96): the Windows YUY2 frame whose bottom
// never arrived (see backend/tests/test_frame_integrity.py) and a real print crop.
const fixture = (name: string) => {
  const f = JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8")) as { width: number; height: number; rgba: number[] };
  return { ...f, px: new Uint8ClampedArray(f.rgba) };
};

test("the real truncated frame is caught", () => {
  const f = fixture("frame_truncated_64x96.json");
  assert.match(truncationReason(f.px, f.width, f.height) ?? "", /truncated/);
});

test("a real print frame passes", () => {
  const f = fixture("frame_good_dot_roi_64x96.json");
  assert.equal(truncationReason(f.px, f.width, f.height), null);
});

test("a green ramp repeated on every row (no real image above) is not truncation", () => {
  const w = 64, h = 96, px = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const i = (y * w + x) * 4; px[i + 1] = Math.round((255 * x) / (w - 1)); px[i + 3] = 255; }
  assert.equal(truncationReason(px, w, h), null);
});
