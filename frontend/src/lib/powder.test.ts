import { test } from "node:test";
import assert from "node:assert/strict";
import { fillDepthMm, cavityFillPct, pistonMaterialFrac, thickPrecoatFeedMm } from "./powder.ts";

test("job source: print FEED demand + thick-precoat feed + margin, clamped to feed travel", () => {
  // The feed rises feed_thickness per layer (not the build's layer thickness), and priming's thick
  // precoats spend n x thick_feed of the cavity before the print starts.
  assert.equal(fillDepthMm({ source: "job", feedDemandMm: 24, thickPrecoatFeedMm: 21, marginMm: 5 }), 50);
  assert.equal(fillDepthMm({ source: "job", feedDemandMm: 200, thickPrecoatFeedMm: 21, marginMm: 5 }), 145);
});
test("the pyramid job (2026-09-22) needed ~100 mm, not the 20 mm it was primed with", () => {
  // 186 feed layers x 0.4 mm = 74.4 mm print demand; 3 thick precoats x 7 mm = 21 mm.
  const d = fillDepthMm({ source: "job", feedDemandMm: 74.4, thickPrecoatFeedMm: 21, marginMm: 5 });
  assert.ok(Math.abs(d - 100.4) < 1e-9);
});
test("thick precoat feed = precoats x feed per precoat (missing values -> 0)", () => {
  assert.equal(thickPrecoatFeedMm(3, 7), 21);
  assert.equal(thickPrecoatFeedMm(null, 7), 0);
  assert.equal(thickPrecoatFeedMm(3, undefined), 0);
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
