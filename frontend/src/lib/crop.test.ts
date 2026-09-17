import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_CROP, clampZoom, clampPct, cropStyle, panOrigin } from "./crop.ts";

test("clampZoom bounds to [1, 4] and rejects junk", () => {
  assert.equal(clampZoom(0.5), 1);
  assert.equal(clampZoom(9), 4);
  assert.equal(clampZoom(2.5), 2.5);
  assert.equal(clampZoom(Number.NaN), 1);
});

test("clampPct bounds to [0, 100]", () => {
  assert.equal(clampPct(-10), 0);
  assert.equal(clampPct(150), 100);
  assert.equal(clampPct(42), 42);
});

test("panOrigin is a no-op at zoom 1 (nothing hidden to pan)", () => {
  assert.deepEqual(panOrigin(NO_CROP, 50, 50, 400, 300), NO_CROP);
});

test("panOrigin moves the origin opposite the drag and clamps to [0,100]", () => {
  // zoom 2, 400px wide: hidden span = (2-1)*400 = 400px maps to 0..100% origin.
  // drag image right +200px -> origin decreases by 200/400*100 = 50 -> 50-50 = 0.
  const c = panOrigin({ zoom: 2, ox: 50, oy: 50 }, 200, 0, 400, 300);
  assert.equal(c.ox, 0);
  assert.equal(c.oy, 50);
  // a large drag clamps rather than overshooting
  assert.equal(panOrigin({ zoom: 2, ox: 50, oy: 50 }, -9999, 0, 400, 300).ox, 100);
});

test("cropStyle emits scale + transform-origin", () => {
  assert.deepEqual(cropStyle({ zoom: 2.5, ox: 30, oy: 70 }), {
    transform: "scale(2.5)",
    transformOrigin: "30% 70%",
  });
});
