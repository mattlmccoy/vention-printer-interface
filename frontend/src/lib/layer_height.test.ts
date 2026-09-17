import { test } from "node:test";
import assert from "node:assert/strict";
import { LAYER_HEIGHTS_MM, LAYER_HEIGHT_QUANTUM_MM, snapLayerHeightMm } from "./layer_height.ts";

test("exposed presets are 0.1 mm multiples only (no 0.15 / sub-0.1)", () => {
  // The MachineMotion position readout is quantized to 0.1 mm, so a layer height that isn't a
  // multiple of 0.1 mm (0.05, 0.15, ...) can't be placed or verified. Only expose 0.1 mm multiples.
  assert.deepEqual(LAYER_HEIGHTS_MM, [0.1, 0.2, 0.3]);
  assert.equal(LAYER_HEIGHT_QUANTUM_MM, 0.1);
  // every preset is already on the 0.1 mm grid (snapping it is a no-op)
  for (const h of LAYER_HEIGHTS_MM) assert.equal(snapLayerHeightMm(h), h);
});

test("snapLayerHeightMm rounds to the nearest achievable 0.1 mm level", () => {
  assert.equal(snapLayerHeightMm(0.15), 0.2); // between quanta -> nearest 0.1 level
  assert.equal(snapLayerHeightMm(0.1), 0.1);
  assert.equal(snapLayerHeightMm(0.2), 0.2);
  assert.equal(snapLayerHeightMm(0.24), 0.2);
  assert.equal(snapLayerHeightMm(0.26), 0.3);
  assert.equal(snapLayerHeightMm(2.0), 2.0);
});

test("snapLayerHeightMm floors at one quantum (never sub-0.1 / zero / junk)", () => {
  assert.equal(snapLayerHeightMm(0.05), 0.1); // below the readout floor -> the floor
  assert.equal(snapLayerHeightMm(0.0), 0.1);
  assert.equal(snapLayerHeightMm(-1), 0.1);
  assert.equal(snapLayerHeightMm(Number.NaN), 0.1);
});
