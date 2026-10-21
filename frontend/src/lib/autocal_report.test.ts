import { test } from "node:test";
import assert from "node:assert/strict";
import { canSolvePartial, checkRows, compareCalibrations } from "./autocal_report.ts";

// The 23-photo run of 2026-10-21 (real numbers, from experiments/.autocal_last_sweep.json).
const run = {
  passed: true, n_views: 23, reprojection_rms_px: 1.448, reprojection_rms_mm: 0.0372, px_mm: 0.02569,
  shift_rms_mm: 0.0593, shift_worst_mm: 0.168, scale_ratio: 1.0014, image_size: [5120, 3840] as [number, number],
  valid_region_mm: [[-67, -15], [34, -15], [34, 47], [-67, 47]] as [number, number][],
  limits: { min_views: 5, reprojection_mm: 0.05, shift_rms_mm: 0.1 },
};

test("a stopped run can be solved once it has at least 5 usable photos", () => {
  const shots = (n: number, usable: number) => Array.from({ length: n }, (_, i) => ({ usable: i < usable }));
  assert.equal(canSolvePartial(shots(23, 23), 5), true);
  assert.equal(canSolvePartial(shots(6, 4), 5), false);
  assert.equal(canSolvePartial([], 5), false);
});

test("each check is listed with its value, its limit and pass/fail", () => {
  const rows = checkRows(run);
  const lens = rows.find((r) => r.label === "lens fit")!;
  assert.equal(lens.ok, true);
  assert.match(lens.value, /0\.037 mm/);
  assert.match(lens.limit, /0\.05 mm/);
  assert.equal(rows.find((r) => r.label === "encoder-shift check")!.ok, true);
  assert.equal(rows.find((r) => r.label === "usable photos")!.value, "23");
  assert.equal(rows.find((r) => r.label === "scale vs recoater")!.ok, null); // informational
});

test("an older saved run without limits uses the current limits, labelled as such", () => {
  const { limits: _drop, ...old } = run;
  const lens = checkRows(old).find((r) => r.label === "lens fit")!;
  assert.match(lens.limit, /0\.05 mm/);
});

test("compare: a run at another photo size says the saved calibration does not apply", () => {
  const c = compareCalibrations(run, { version: "cal-20261021T174751Z", image_size: [1920, 1080], reprojection_rms_mm: null, reprojection_rms_px: 0.285, shift_rms_mm: 0.039, scale_ratio: 1.0021, area_mm: [42, 32], method: "auto-sweep" });
  assert.equal(c.tone, "warn");
  assert.match(c.verdict, /1920×1080/);
  assert.match(c.verdict, /does not apply/);
  assert.equal(c.rows.find((r) => r.label === "calibrated area")!.saved, "42 × 32 mm");
  assert.equal(c.rows.find((r) => r.label === "calibrated area")!.now, "101 × 62 mm");
});

test("compare: with nothing saved, this run would be the first", () => {
  const c = compareCalibrations(run, null);
  assert.match(c.verdict, /no calibration saved/i);
  assert.equal(c.rows.length, 0);
});

test("compare: same size, better encoder shift and lens fit reads 'better'", () => {
  const c = compareCalibrations(run, { version: "cal-x", image_size: [5120, 3840], reprojection_rms_mm: 0.045, reprojection_rms_px: 1.75, shift_rms_mm: 0.08, scale_ratio: 1.003, area_mm: [90, 60], method: "auto-sweep" });
  assert.equal(c.tone, "ok");
  assert.match(c.verdict, /better/);
});
