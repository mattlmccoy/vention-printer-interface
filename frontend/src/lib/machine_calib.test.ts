import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_CALIB, parseCalibration, pistonPoint, railPoint, setPoint } from "./machine_calib.ts";

test("parse falls back per field", () => {
  const c = parseCalibration({ rails: { printhead: { x0: 1, y0: 2 } }, image: { w: "x" } });
  assert.equal(c.rails.printhead.x0, 1);
  assert.equal(c.rails.printhead.x1, DEFAULT_CALIB.rails.printhead.x1);
  assert.equal(c.image.w, DEFAULT_CALIB.image.w);
});

test("rail and piston interpolation clamp to travel", () => {
  const l = { x0: 0, y0: 0, x1: 100, y1: 50 };
  assert.deepEqual(railPoint(l, 465, 930), { x: 50, y: 25 });
  assert.deepEqual(railPoint(l, 5000, 930), { x: 100, y: 50 });
  assert.deepEqual(pistonPoint({ x: 7, y0: 10, y1: 110 }, 72.5), { x: 7, y: 60 });
  assert.deepEqual(pistonPoint({ x: 7, y0: 10, y1: 110 }, -3), { x: 7, y: 10 });
});

test("setPoint is pure and targets the right endpoint", () => {
  const c2 = setPoint(DEFAULT_CALIB, "rails.recoater.1", { x: 9, y: 8 });
  assert.equal(c2.rails.recoater.x1, 9);
  assert.equal(DEFAULT_CALIB.rails.recoater.x1, 1400);
  const c3 = setPoint(DEFAULT_CALIB, "pistons.build.0", { x: 3, y: 4 });
  assert.deepEqual([c3.pistons.build.x, c3.pistons.build.y0], [3, 4]);
});
