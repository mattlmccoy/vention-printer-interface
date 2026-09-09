import { test } from "node:test";
import assert from "node:assert/strict";
import { armHint, fmtMm, fmtSecs, fmtSpeed, gates, tri } from "./format.ts";
import type { StatusPayload } from "./telemetry.ts";

function status(state: StatusPayload["controller"]["state"], armed: boolean, recipe = "idle"): StatusPayload {
  return {
    device: {},
    controller: { state, backend: "simulated", armed, fault_reasons: [], warnings: [], read_error: null,
      limits: { max_speed: {}, max_accel: {}, travel_min: {}, travel_max: {}, heater_max_on_s: 120, telemetry_timeout_s: 2, near_limit_mm: 5 },
      heater: { on: null, commanded_on: false, on_s: 0, max_on_s: 120 }, telemetry: null },
    axis_motion: {},
    recipe: { state: recipe as StatusPayload["recipe"]["state"], step_index: 0, n_steps: 0, phase: "", layer: 0, n_layers: 0, part_height_mm: 0, elapsed_s: 0, dry_run: false, single_step: false, reason: "", current_step: null, plan: null },
    auto_log: true,
    recording: { active: false, run: null },
  };
}

test("gates mirror the T&C rules", () => {
  assert.equal(gates(null, false).connected, false);
  const g = gates(status("connected", false), true);
  assert.deepEqual([g.connected, g.armed, g.controllable, g.faulted], [true, false, false, false]);
  const a = gates(status("connected", true), true);
  assert.equal(a.controllable, true);
  const f = gates(status("fault", true), true);
  assert.deepEqual([f.connected, f.controllable, f.faulted], [true, true, true]);
  assert.equal(gates(status("connected", true), false).controllable, false);
  assert.equal(gates(status("connected", true, "paused"), true).recipeActive, true);
});

test("formatters", () => {
  assert.equal(fmtMm(12.345), "12.35 mm");
  assert.equal(fmtMm(null), "—");
  assert.equal(fmtSpeed(2.5), "2.5 mm/s");
  assert.equal(fmtSpeed(100), "100 mm/s");
  assert.equal(fmtSecs(75), "1:15");
  assert.equal(fmtSecs(9), "9s");
  assert.equal(tri(null, "ON", "off"), "?");
  assert.equal(tri(true, "ON", "off"), "ON");
});

test("arm hint is state-specific", () => {
  assert.match(armHint(gates(null, false), []), /unreachable/);
  assert.match(armHint(gates(status("connected", false), true), []), /ARM/);
  assert.match(armHint(gates(status("fault", false), true), ["x"]), /FAULT: x/);
});
