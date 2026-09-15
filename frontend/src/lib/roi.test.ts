import { test } from "node:test";
import assert from "node:assert/strict";
import { GOLD_LAYOUT_MM, pxPerMmFromCircle, roiBoxesFromCircle } from "./roi.ts";

// Test circle chosen so ppm and every product avoid .5 boundaries, so JS Math.round
// and Python int(round(...)) (banker's rounding) agree exactly. radius=400 -> ppm=8.0.
const circle = { cx: 400, cy: 300, radius: 400 };

test("pxPerMmFromCircle: 2*radius/diameter", () => {
  assert.equal(pxPerMmFromCircle(400), 8.0); // 2*400/100
  assert.equal(pxPerMmFromCircle(50, 100), 1.0);
});

test("roiBoxesFromCircle mirrors backend mm_box_to_px_rect exactly", () => {
  // Hand-computed from _AUTO_LAYOUT_MM with ppm=8.0:
  //   x=round(cx + x_mm*ppm), y=round(cy - y_mm*ppm), w=round(w_mm*ppm), h=round(h_mm*ppm)
  const expected = {
    dot: { x: 207, y: 20, w: 240, h: 240 }, // 400-24.1*8=207.2; 300-35*8=20; 30*8=240
    checkerboard: { x: 443, y: 97, w: 160, h: 160 }, // 400+5.4*8=443.2; 300-25.4*8=96.8; 20*8
    rings: { x: 123, y: 244, w: 352, h: 352 }, // 400-34.6*8=123.2; 300-7*8=244; 44*8
    pitch: { x: 472, y: 236, w: 208, h: 208 }, // 400+9*8=472; 300-8*8=236; 26*8
  };
  assert.deepEqual(roiBoxesFromCircle(circle), expected);
});

test("GOLD_LAYOUT_MM keys are exactly dot, checkerboard, rings, pitch", () => {
  assert.deepEqual(Object.keys(GOLD_LAYOUT_MM).sort(), [
    "checkerboard",
    "dot",
    "pitch",
    "rings",
  ]);
});
