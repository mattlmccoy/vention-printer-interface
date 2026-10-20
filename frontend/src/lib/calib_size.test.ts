import { test } from "node:test";
import assert from "node:assert/strict";
import { calibrationSizeWarning } from "./calib_size.ts";

test("no warning when the science resolution matches the calibration's photo size", () => {
  assert.equal(calibrationSizeWarning("5120x3840", [5120, 3840]), null);
});

test("no warning without a calibration (nothing to mismatch)", () => {
  assert.equal(calibrationSizeWarning("5120x3840", null), null);
});

test("warns, naming both sizes, when the science resolution differs from the calibration", () => {
  const w = calibrationSizeWarning("5120x3840", [1920, 1080]);
  assert.ok(w);
  assert.match(w, /5120×3840/);
  assert.match(w, /1920×1080/);
  assert.match(w, /not measured/);
});

test("an unreadable resolution setting gives no warning rather than a wrong one", () => {
  assert.equal(calibrationSizeWarning("", [1920, 1080]), null);
});
