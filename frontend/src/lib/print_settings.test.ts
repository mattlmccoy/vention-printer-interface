import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PLAN, compilePrint, describeStep, totalLayers, totalThickness, validate } from "./print_settings.ts";

test("defaults match V1.py and the backend", () => {
  assert.equal(totalThickness(DEFAULT_PLAN), 30);
  assert.equal(totalLayers(DEFAULT_PLAN), 12);
  assert.deepEqual(validate(DEFAULT_PLAN), []);
});

test("printability and travel reasons", () => {
  const bad = { ...DEFAULT_PLAN, printing: { ...DEFAULT_PLAN.printing, n_layers: 100 } };
  assert.match(validate(bad)[0], /thickness/);
  assert.match(validate({ ...DEFAULT_PLAN, recoater_end_mm: 5000 })[0], /recoater_end_mm/);
});

test("compile matches the backend order for one print layer (37 steps, heater on)", () => {
  const one = { ...DEFAULT_PLAN, precoat: { ...DEFAULT_PLAN.precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 }, heater_enabled: true };
  const steps = compilePrint(one);
  assert.equal(steps.length, 37);
  assert.equal(steps[14].label, "layer_start");
  assert.equal(steps[36].label, "layer_end");
  assert.equal(steps[36].part_height_mm, 2);
  assert.deepEqual(steps.map((s) => s.index), [...Array(37).keys()]);
});

test("compile of the full default plan: 12 layers, heights, resets", () => {
  const steps = compilePrint({ ...DEFAULT_PLAN, n_heater_passes: 3 });
  assert.equal(steps.filter((s) => s.kind === "move_abs" && s.value === 600).length, 30);
  const ends = steps.filter((s) => s.label === "layer_end").map((s) => s.part_height_mm);
  assert.deepEqual([ends[0], ends[1], ends.at(-1)], [5, 7, 30]);
  assert.equal(steps.filter((s) => s.kind === "set_speed" && s.axis === 4 && s.value === 100).length, 12);
  assert.equal(steps.filter((s) => s.kind === "heater").length, 0);
});

test("describeStep", () => {
  const s = compilePrint(DEFAULT_PLAN);
  assert.equal(describeStep(s[0]), "home all");
  assert.equal(describeStep(s[4]), "feed → 145 mm");
  assert.equal(describeStep(null), "—");
});
