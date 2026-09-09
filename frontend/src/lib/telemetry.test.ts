import { test } from "node:test";
import assert from "node:assert/strict";
import { AXES, TRAVEL_MM, TraceBuffer, isStale } from "./telemetry.ts";

test("axes and travel match the backend constants", () => {
  assert.deepEqual([...AXES], [1, 2, 3, 4]);
  assert.deepEqual(TRAVEL_MM, { 1: 145, 2: 145, 3: 840, 4: 930 });
});

test("trace buffer keeps capacity and windows by time", () => {
  const b = new TraceBuffer(4);
  for (let i = 0; i < 6; i++) b.push(i, i * 10);
  assert.equal(b.length, 4);
  assert.deepEqual(b.window(100), [[2, 20], [3, 30], [4, 40], [5, 50]]);
  assert.deepEqual(b.window(1), [[4, 40], [5, 50]]);
  b.clear();
  assert.deepEqual(b.window(10), []);
});

test("staleness", () => {
  assert.equal(isStale(null, 5000), false);
  assert.equal(isStale(1000, 2000), false);
  assert.equal(isStale(1000, 3500), true);
});
