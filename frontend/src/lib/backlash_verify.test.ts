import { test } from "node:test";
import assert from "node:assert/strict";
import { binLevels, verifyVerdict } from "./backlash_verify.ts";

test("binLevels groups quantised reps into per-level counts, ascending", () => {
  // encoder-quantised reps: mostly -0.1, one 0.0
  const levels = binLevels([-0.1, -0.1, 0.0, -0.1, -0.1, -0.1]);
  assert.deepEqual(levels, [
    { value: -0.1, count: 5 },
    { value: 0.0, count: 1 },
  ]);
});

test("binLevels snaps near-quantum values to the same level", () => {
  const levels = binLevels([-0.098, -0.101, 0.002]);
  assert.deepEqual(levels, [
    { value: -0.1, count: 2 },
    { value: 0.0, count: 1 },
  ]);
});

test("binLevels empty -> empty", () => {
  assert.deepEqual(binLevels([]), []);
});

test("verifyVerdict: agreement within one count is consistent", () => {
  const v = verifyVerdict(-0.1, -0.1, 0.1);
  assert.equal(v.consistent, true);
  assert.equal(v.deltaMm, 0);
});

test("verifyVerdict: one-count apart still consistent (readout resolution)", () => {
  const v = verifyVerdict(-0.1, 0.0, 0.1);
  assert.equal(v.consistent, true);
  assert.ok(Math.abs(v.deltaMm - 0.1) < 1e-9);
});

test("verifyVerdict: more than one count apart is inconsistent", () => {
  const v = verifyVerdict(-0.1, 0.2, 0.1);
  assert.equal(v.consistent, false);
  assert.ok(Math.abs(v.deltaMm - 0.3) < 1e-9);
});
