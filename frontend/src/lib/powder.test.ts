import { test } from "node:test";
import assert from "node:assert/strict";
import { fillDepthMm, cavityFillPct, pistonMaterialFrac } from "./powder.ts";

test("job source: total thickness + margin, clamped to feed travel", () => {
  assert.equal(fillDepthMm({ source: "job", totalThicknessMm: 24, marginMm: 5 }), 29);
  assert.equal(fillDepthMm({ source: "job", totalThicknessMm: 200, marginMm: 5 }), 145);
});
test("manual layers x thickness + margin", () => {
  assert.equal(fillDepthMm({ source: "layers", nLayers: 40, layerThicknessMm: 0.5, marginMm: 3 }), 23);
});
test("manual depth passes through, clamped to >= 0", () => {
  assert.equal(fillDepthMm({ source: "depth", manualDepthMm: 31.5 }), 31.5);
  assert.equal(fillDepthMm({ source: "depth", manualDepthMm: -4 }), 0);
});
test("cavity fill percent of feed travel", () => {
  assert.equal(cavityFillPct(29), 20);
  assert.equal(cavityFillPct(300), 100);
});
test("piston material fraction: flush=full, deep=empty (well fills from the top down)", () => {
  // 0 mm = flush with the bed = well FULL; travel mm = piston fully down = EMPTY.
  assert.equal(pistonMaterialFrac(0, 145), 1);
  assert.equal(pistonMaterialFrac(145, 145), 0);
  // a shallow 20 mm cavity leaves most of the well full (small cavity at the top)
  assert.ok(Math.abs(pistonMaterialFrac(20, 145) - 0.862) < 1e-3);
  // clamped both ends; non-finite / null -> 0 (empty, unknown)
  assert.equal(pistonMaterialFrac(-10, 145), 1);
  assert.equal(pistonMaterialFrac(200, 145), 0);
  assert.equal(pistonMaterialFrac(null, 145), 0);
});
