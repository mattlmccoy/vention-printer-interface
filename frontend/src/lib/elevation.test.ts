import { test } from "node:test";
import assert from "node:assert/strict";
import { layoutElevation } from "./elevation.ts";

test("rails span travel and pistons map downward", () => {
  const e = layoutElevation(900, 380);
  assert.ok(Math.abs(e.railRc.w - 930 * e.scaleX) < 1e-9);
  assert.ok(e.railPh.w < e.railRc.w);
  assert.equal(e.gantryX(4, 0), e.railRc.x);
  assert.ok(e.gantryX(4, 930) <= 900 - 40 + 1e-9);
  assert.equal(e.pistonTopY(1, 0), e.build.y);
  assert.ok(e.pistonTopY(1, 145) > e.pistonTopY(1, 10));
  assert.ok(e.pistonTopY(2, 999) <= e.bed.y + e.bed.h + 1e-9);
  assert.ok(e.feed.x < e.build.x);
});
