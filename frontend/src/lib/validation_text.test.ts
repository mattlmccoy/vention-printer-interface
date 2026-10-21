import { test } from "node:test";
import assert from "node:assert/strict";
import { validationCoverageText } from "./validation_text.ts";

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
