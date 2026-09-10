import { test } from "node:test";
import assert from "node:assert/strict";
import { fillDepthMm, cavityFillPct } from "./powder.ts";

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
