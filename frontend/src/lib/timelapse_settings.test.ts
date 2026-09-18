import { test } from "node:test";
import assert from "node:assert/strict";
import { clampInterval, loadOverviewTimelapse, saveOverviewTimelapse } from "./timelapse_settings.ts";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

test("defaults are off at 3 s", () => {
  assert.deepEqual(loadOverviewTimelapse(new Mem()), { enabled: false, intervalS: 3 });
});

test("round-trips enabled + interval, clamping the interval", () => {
  const s = new Mem();
  saveOverviewTimelapse(s, { enabled: true, intervalS: 5 });
  assert.deepEqual(loadOverviewTimelapse(s), { enabled: true, intervalS: 5 });
  saveOverviewTimelapse(s, { enabled: true, intervalS: 999 });
  assert.equal(loadOverviewTimelapse(s).intervalS, 60);
  saveOverviewTimelapse(s, { enabled: true, intervalS: 0.01 });
  assert.equal(loadOverviewTimelapse(s).intervalS, 0.5);
});

test("clampInterval handles junk", () => {
  assert.equal(clampInterval("nope"), 3);
  assert.equal(clampInterval(10), 10);
  assert.equal(clampInterval(-2), 0.5);
});

test("malformed storage falls back to defaults", () => {
  const s = new Mem();
  s.setItem("vpi.overviewTimelapse", "not json");
  assert.deepEqual(loadOverviewTimelapse(s), { enabled: false, intervalS: 3 });
});
