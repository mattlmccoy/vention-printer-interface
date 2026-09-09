import { test } from "node:test";
import assert from "node:assert/strict";
import { estimateDurationS, heaterOnTimeS } from "./estimate.ts";
import { DEFAULT_PLAN } from "./print_settings.ts";

test("estimate scales with layers and is in a sane range", () => {
  const one = { ...DEFAULT_PLAN, precoat: { ...DEFAULT_PLAN.precoat, n_layers: 0 }, printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 } };
  const ten = { ...one, printing: { ...one.printing, n_layers: 10 } };
  const t1 = estimateDurationS(one), t10 = estimateDurationS(ten);
  assert.ok(t1 > 0 && t10 > t1 * 5);
  const total = estimateDurationS(DEFAULT_PLAN);
  assert.ok(total > 29 && total < 7200);
});

test("heater on-time", () => {
  assert.equal(heaterOnTimeS(DEFAULT_PLAN), 0);
  assert.equal(heaterOnTimeS({ ...DEFAULT_PLAN, heater_enabled: true }), Math.round(10 * (2 * 595) / 50));
});
