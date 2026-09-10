import { test } from "node:test";
import assert from "node:assert/strict";
import { describeEvent } from "./eventlog.ts";

test("home names the axes", () => {
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: [4] } }),
    "Homed Recoater Gantry");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: [3, 4] } }),
    "Homed Printhead Gantry, Recoater Gantry");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "home", data: { axes: "all" } }),
    "Homed all axes");
});

test("move + heater + connect read naturally", () => {
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "heater_on", data: {} }), "Heater on");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "connected", data: { backend: "machinemotion", ip: "192.168.7.2" } }),
    "Connected to MachineMotion (192.168.7.2)");
  assert.equal(describeEvent({ host_timestamp_ns: 0, label: "move", data: { axis: 1, applied_mm: 2.5 } }),
    "Moved Part Piston 2.5 mm");
});

test("unknown labels fall back to the raw summary", () => {
  assert.match(describeEvent({ host_timestamp_ns: 0, label: "custom_thing", data: { a: 1 } }), /custom_thing/);
});
