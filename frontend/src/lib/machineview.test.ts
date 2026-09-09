import { test } from "node:test";
import assert from "node:assert/strict";
import { heaterGlyph, layoutMachine, limitBands } from "./machineview.ts";

test("layout scales gantries to width and pistons to height", () => {
  const g = layoutMachine(1000, 400);
  assert.ok(g.scale > 0);
  assert.equal(g.axes[4].track.w, 930 * g.scale);
  assert.equal(g.axes[3].track.w, 840 * g.scale);
  assert.equal(g.axes[1].track.h, 145 * g.scale);
  assert.ok(g.axes[4].track.x + g.axes[4].track.w <= 1000);
  assert.ok(g.bed.y + g.bed.h <= 400);
});

test("px/mm round-trip and clamping", () => {
  const g = layoutMachine(800, 300);
  const rc = g.axes[4];
  assert.equal(rc.px(0), rc.track.x);
  assert.ok(Math.abs(rc.mm(rc.px(465)) - 465) < 1e-9);
  assert.equal(rc.px(5000), rc.track.x + 930 * g.scale);
  const part = g.axes[1];
  assert.equal(part.px(0), part.track.y);
  assert.ok(part.px(100) > part.px(10)); // pistons increase downward
});

test("limit bands cover only the excluded ranges", () => {
  const g = layoutMachine(800, 300);
  const bands = limitBands(g.axes[3], 10, 800);
  assert.equal(bands.length, 2);
  assert.ok(bands[0].w > 0 && bands[1].w > 0);
  assert.equal(limitBands(g.axes[3], 0, 840).length, 0);
});

test("heater glyph follows the recoater", () => {
  const g = layoutMachine(800, 300);
  assert.ok(heaterGlyph(g, 600).x > heaterGlyph(g, 5).x);
});
