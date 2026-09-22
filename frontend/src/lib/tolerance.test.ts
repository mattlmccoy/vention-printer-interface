import { test } from "node:test";
import assert from "node:assert/strict";
import { passMax, passMin, bandFraction } from "./tolerance.ts";

test("passMax: value within an upper limit passes (error/tolerance bands)", () => {
  assert.equal(passMax(0.03, 0.05), true);
  assert.equal(passMax(0.05, 0.05), true);   // on the band = pass
  assert.equal(passMax(0.08, 0.05), false);
});

test("passMin: value at least a target passes (resolution lp/mm)", () => {
  assert.equal(passMin(12, 10), true);
  assert.equal(passMin(10, 10), true);
  assert.equal(passMin(8, 10), false);
});

test("bandFraction: value as a fraction of the limit, clamped for plotting", () => {
  assert.equal(bandFraction(0, 0.05), 0);
  assert.equal(bandFraction(0.05, 0.05), 1);
  assert.equal(bandFraction(0.10, 0.05), 2);        // 2x over
  assert.equal(bandFraction(0.50, 0.05), 2.5);      // clamped to the 2.5 plotting ceiling
  assert.equal(bandFraction(0.05, 0), 0);           // guard divide-by-zero
});
