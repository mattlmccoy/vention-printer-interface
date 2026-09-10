import { test } from "node:test";
import assert from "node:assert/strict";
import { exposure } from "./heater_model.ts";

const base = {
  layerMm: 0.2, areaMm2: 900.0, carbonWt: 0.15, powderDensityGCm3: 1.01,
  inkCarbonWt: 0.25, ipaDhvapJG: 663.0, sectionPowerW: 75.0,
};

test("ipa exposure energy and time", () => {
  const e = exposure(base);
  assert.equal(round(e.powderMassG, 4), 0.1818);
  assert.equal(round(e.ipaMassG, 4), 0.0962);
  assert.equal(round(e.energyJ, 1), 63.8);
  assert.equal(round(e.timeS, 2), 0.85);
});

test("sweep speed from pass length", () => {
  const e = exposure(base);
  assert.equal(round(e.sweepSpeed(30.0), 1), round(30.0 / e.timeS, 1));
});

test("multipass scales energy and time", () => {
  const e1 = exposure(base);
  const e2 = exposure({ ...base, passes: 2 });
  assert.equal(round(e2.energyJ, 3), round(e1.energyJ * 2, 3));
  assert.equal(round(e2.timeS, 3), round(e1.timeS * 2, 3));
});

function round(x: number, n: number): number {
  const f = 10 ** n;
  return Math.round(x * f) / f;
}
