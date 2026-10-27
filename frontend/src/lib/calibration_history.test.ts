import { test } from "node:test";
import assert from "node:assert/strict";
import { restorePlan, summaryFacts, validationBadge, type CalibrationSummary } from "./calibration_history.ts";

// GET /api/vision/calibrations on the REAL 2026-10-26 files (calibration in use + its numbers-only
// certified validation), captured from vision/calibration_history.py.
const real: CalibrationSummary = {
  version: "cal-20261026T192538Z", saved_at: "2026-10-26T19:25:38Z", method: "auto-sweep", active: true, archived: true,
  image_size: [5120, 3840], lens_rms_mm: 0.0353880221909533, shift_rms_mm: 0.061291196476435036, scale_ratio: 1.002039356381092,
  n_views: 14, area_mm: [89.06755190712536, 60.09725265019986], point_method: null,
  self_check: { passed: true, rms_mm: 0.02755221833556134 }, images: [],
  validation: { count: 1, status: "failed", latest: { stamp: null, legacy: true, passed: false, rms_mm: 0.07514783201420489,
    max_mm: 0.12901066836609384, target_mm: 0.05, scale_bias: 1.0026662082141908 } },
};

test("a failed numbers-only validation reads as failed and says no photo was kept", () => {
  const b = validationBadge(real.validation);
  assert.equal(b.tone, "err");
  assert.match(b.text, /failed/);
  assert.match(b.text, /0\.129 mm/);
  assert.match(b.text, /numbers only/);
});

test("no validation never reads as healthy", () => {
  const b = validationBadge({ count: 0, status: "none", latest: null });
  assert.equal(b.tone, "warn");
  assert.equal(b.text, "not validated");
});

test("a passing validation shows its worst point against the target", () => {
  const b = validationBadge({ count: 2, status: "passed", latest: { stamp: "20261027T150000000000Z", legacy: false, passed: true,
    rms_mm: 0.03, max_mm: 0.045, target_mm: 0.05, scale_bias: 1.0004 } });
  assert.equal(b.tone, "ok");
  assert.match(b.text, /worst 0\.045 mm \(target 0\.05 mm\)/);
});

test("the summary lists the real run's numbers", () => {
  const f = Object.fromEntries(summaryFacts(real));
  assert.equal(f["photo size"], "5120 × 3840");
  assert.equal(f["lens fit"], "0.035 mm");
  assert.equal(f["encoder shift"], "0.061 mm RMS");
  assert.equal(f["calibrated area"], "89 × 60 mm");
  assert.equal(f["self-check"], "passed (0.028 mm RMS)");
  assert.equal(f["points fitted"], "every identified point (before 0.21.0)");
});

test("unknown values show a dash, never zero", () => {
  const f = Object.fromEntries(summaryFacts({ ...real, method: "manual", lens_rms_mm: null, scale_ratio: null, n_views: null,
    area_mm: null, self_check: null, image_size: null }));
  assert.equal(f["lens fit"], "—");
  assert.equal(f["calibrated area"], "—");
  assert.equal(f["self-check"], "not run");
  assert.equal(f["photo size"], "—");
});

test("restoring warns when the photo size differs from the calibration in use", () => {
  const older = { ...real, version: "cal-20261021T174751Z", image_size: [1920, 1080] as [number, number], active: false };
  const p = restorePlan(older, real);
  assert.match(p.confirm, /cal-20261021T174751Z/);
  assert.match(p.warning ?? "", /1920 × 1080/);
  assert.match(p.warning ?? "", /5120 × 3840/);
  assert.equal(restorePlan({ ...real, version: "cal-x", active: false }, real).warning, null);
  assert.match(restorePlan(older, null).confirm, /no calibration is in use/);
});
