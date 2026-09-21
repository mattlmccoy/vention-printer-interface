import { test } from "node:test";
import assert from "node:assert/strict";
import { estimateDurationS, heaterOnTimeS } from "./estimate.ts";
import { DEFAULT_PLAN } from "./print_settings.ts";

test("estimate scales with layers and is in a sane range", () => {
  const one = { ...DEFAULT_PLAN, thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 }, printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 } };
  const ten = { ...one, printing: { ...one.printing, n_layers: 10 } };
  const t1 = estimateDurationS(one), t10 = estimateDurationS(ten);
  // fixed homing/finish overhead (two gantry homes at setup + finish + part->max) means < 10x
  assert.ok(t1 > 0 && t10 > t1 * 3);
  const total = estimateDurationS(DEFAULT_PLAN);
  assert.ok(total > 29 && total < 7200);
});

test("estimate matches the backend golden for the default plan (#6 FE/backend determinism)", () => {
  // Pinned to backend estimate_duration_s(PrintSettings(), 0.25) == 395.0 (default now includes the
  // 0.15 mm build backlash overshoot+return). The two implementations
  // must agree at the SAME wait floor, so the displayed estimate equals what the print actually runs.
  assert.equal(estimateDurationS(DEFAULT_PLAN, 0.25), 395.0);
  // Deterministic: identical inputs → identical output, always.
  assert.equal(estimateDurationS(DEFAULT_PLAN, 0.25), estimateDurationS(DEFAULT_PLAN, 0.25));
});

test("heater on-time", () => {
  assert.equal(heaterOnTimeS(DEFAULT_PLAN), 0);
  // one 425->600 sweep per printing layer at the heater speed
  assert.equal(heaterOnTimeS({ ...DEFAULT_PLAN, heater_enabled: true }), Math.round(10 * (600 - 425) / 50));
});
