import assert from "node:assert/strict";
import { test } from "node:test";

import {
  hasNativeSpeed,
  layerAccuracySummary,
  motionColumn,
  parseLayerAccuracy,
} from "./motion.ts";

const MOTION = [
  "host_timestamp_ns,pos_1,pos_2,pos_3,pos_4,vel_1,vel_2,vel_3,vel_4,accel_1,accel_2,accel_3,accel_4,vspeed_1,vspeed_2,vspeed_3,vspeed_4",
  "0,0.0,0,0,0,2.5,0,0,0,,,,,2.5,0,0,0", // first row: accel blank (no prior velocity)
  "500000000,0.5,0,0,0,,0,0,0,,,,,,0,0,0", // blank vel_1/accel_1 -> dropped from the series
  "1000000000,1.5,0,0,0,4.0,0,0,0,3.0,0,0,0,4.0,0,0,0",
].join("\n");

test("motionColumn reads one axis+metric, dropping blanks", () => {
  assert.deepEqual(motionColumn(MOTION, "vel", 1), [2.5, 4.0]); // middle blank dropped
  assert.deepEqual(motionColumn(MOTION, "pos", 1), [0.0, 0.5, 1.5]);
  assert.deepEqual(motionColumn(MOTION, "accel", 1), [3.0]);
  assert.deepEqual(motionColumn(MOTION, "vel", 3), [0, 0, 0]);
  assert.deepEqual(motionColumn(MOTION, "vel", 9), []); // no such axis column
});

test("hasNativeSpeed detects the vspeed columns", () => {
  assert.equal(hasNativeSpeed(MOTION), true);
  assert.equal(hasNativeSpeed("host_timestamp_ns,pos_1,vel_1,accel_1\n0,0,0,0"), false);
});

const ACCURACY = [
  "layer,phase,commanded_mm,actual_mm,deviation_mm,commanded_cum_mm,actual_cum_mm",
  "1,thin_precoat,0.2,0.19,-0.01,0.2,0.19",
  "2,printing,2.0,2.05,0.05,2.2,2.24",
  "3,postcoat,0,0.0,0.0,7.2,7.24", // postcoat excluded from the build-piston summary
  "4,printing,2.0,,,4.2,", // no telemetry -> unknown, excluded
].join("\n");

test("parseLayerAccuracy types rows and keeps unknowns as null", () => {
  const rows = parseLayerAccuracy(ACCURACY);
  assert.equal(rows.length, 4);
  assert.equal(rows[0].deviation_mm, -0.01);
  assert.equal(rows[3].actual_mm, null);
  assert.equal(rows[3].deviation_mm, null);
});

test("layerAccuracySummary scores only part-drop layers with a known deviation", () => {
  const s = layerAccuracySummary(parseLayerAccuracy(ACCURACY));
  assert.equal(s.n, 2); // layers 1 and 2 (postcoat excluded, layer 4 unknown excluded)
  assert.ok(Math.abs((s.meanAbsDevMm as number) - (0.01 + 0.05) / 2) < 1e-9);
  assert.equal(s.maxAbsDevMm, 0.05);
  assert.equal(s.maxLayer, 2);
});

test("layerAccuracySummary is empty (not zero) when nothing is scorable", () => {
  const s = layerAccuracySummary(parseLayerAccuracy("layer,phase,commanded_mm,actual_mm,deviation_mm,commanded_cum_mm,actual_cum_mm\n1,postcoat,0,0,0,0,0"));
  assert.equal(s.n, 0);
  assert.equal(s.meanAbsDevMm, null);
  assert.equal(s.maxLayer, null);
});
