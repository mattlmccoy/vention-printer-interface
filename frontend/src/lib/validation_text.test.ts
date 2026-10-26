import { test } from "node:test";
import assert from "node:assert/strict";
import { validationCoverageText, validationScaleText } from "./validation_text.ts";

test("states how many corners were scored and how many fell outside the calibrated area", () => {
  assert.equal(validationCoverageText({ n_points: 62, n_outside: 9, area_known: true }),
    "62 corners scored inside the calibrated area, 9 outside it (not scored)");
});

test("an older calibration says the area is unknown instead of implying a filtered score", () => {
  assert.equal(validationCoverageText({ n_points: 62, n_outside: 0, area_known: false }),
    "62 corners scored — calibrated area unknown (older calibration), so every corner counts");
});

test("an operator without the area fields (older backend) is labelled unknown, never 'inside'", () => {
  assert.match(validationCoverageText({ n_points: 24 }), /calibrated area unknown/);
});

test("a failure that is mostly scale says so, with the scale-removed numbers", () => {
  const t = validationScaleText({ max_mm: 0.129, rms_mm: 0.075, scale_bias: 1.0027, scale_free_max_mm: 0.04, scale_free_rms_mm: 0.018, target_mm: 0.05 });
  assert.match(t, /0\.27% too large/);
  assert.match(t, /worst 0\.040 mm, RMS 0\.018 mm/);
  assert.match(t, /mostly a scale error/);
});

test("a failure that is not scale says the rest is the lens or flatness", () => {
  const t = validationScaleText({ max_mm: 0.129, rms_mm: 0.075, scale_bias: 1.0001, scale_free_max_mm: 0.125, scale_free_rms_mm: 0.07, target_mm: 0.05 });
  assert.match(t, /not a scale error/);
});

test("an older operator without scale-removed numbers gets no claim", () => {
  assert.equal(validationScaleText({ max_mm: 0.1, rms_mm: 0.05, scale_bias: 1.002, target_mm: 0.05 }), "");
});
