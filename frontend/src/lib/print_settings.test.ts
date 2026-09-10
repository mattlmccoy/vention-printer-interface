import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PLAN, compilePrint, describeStep, totalLayers, totalThickness, validate } from "./print_settings.ts";

test("defaults match V1.py and the backend", () => {
  // thick 5*3 + thin 0.2*2 + printing 2*10 + postcoat 5*1 = 40.4 mm over 16 layers
  assert.ok(Math.abs(totalThickness(DEFAULT_PLAN) - 40.4) < 1e-9);
  assert.equal(totalLayers(DEFAULT_PLAN), 16);
  assert.deepEqual(validate(DEFAULT_PLAN), []);
});

test("printability and travel reasons", () => {
  const bad = { ...DEFAULT_PLAN, printing: { ...DEFAULT_PLAN.printing, n_layers: 100 } };
  assert.match(validate(bad)[0], /thickness/);
  assert.match(validate({ ...DEFAULT_PLAN, recoater_end_mm: 5000 })[0], /recoater_end_mm/);
});

test("compile matches the backend order for one print layer (37 steps, heater on)", () => {
  const one = { ...DEFAULT_PLAN, thick_precoat: { ...DEFAULT_PLAN.thick_precoat, n_layers: 0 },
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 }, heater_enabled: true };
  const steps = compilePrint(one);
  assert.equal(steps.length, 37);
  assert.equal(steps[14].label, "layer_start");
  assert.equal(steps[36].label, "layer_end");
  assert.equal(steps[36].part_height_mm, 2);
  assert.deepEqual(steps.map((s) => s.index), [...Array(37).keys()]);
});

test("printing layer: multi-pass jetting + pre-heater drop and return-up", () => {
  const p = { ...DEFAULT_PLAN, thick_precoat: { ...DEFAULT_PLAN.thick_precoat, n_layers: 0 },
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, layer_thickness_mm: 0.2, n_layers: 1 },
    postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 },
    n_jet_passes: 2, pre_heater_drop_mm: 0.1, heater_enabled: true };
  const ks = compilePrint(p).map((s) => [s.kind, s.axis, s.value] as const);
  const jet = ks.flatMap((k, i) =>
    k[0] === "move_abs" && k[1] === 3 && k[2] === p.printhead_end_mm ? [i] : []);
  assert.equal(jet.length, 2); // two jet passes
  const iDrop = ks.findIndex((k) => k[0] === "move_rel" && k[1] === 1 && k[2] === p.pre_heater_drop_mm);
  const iHeaterOn = ks.findIndex((k) => k[0] === "heater" && k[2] === 1);
  const iUp = ks.findIndex((k, i) =>
    k[0] === "move_rel" && k[1] === 1 && k[2] === -p.pre_heater_drop_mm && i > iHeaterOn);
  assert.ok(Math.max(...jet) < iDrop && iDrop < iHeaterOn && iHeaterOn < iUp);
});

test("compile of the full default plan: 16 layers, heights, resets", () => {
  const steps = compilePrint({ ...DEFAULT_PLAN, n_heater_passes: 3 });
  // printing 10 layers x 3 heater passes = 30 moves to heater_end (precoats never heat)
  assert.equal(steps.filter((s) => s.kind === "move_abs" && s.value === 600).length, 30);
  // four non-empty phase setups + 9 per-layer printing resets
  assert.equal(steps.filter((s) => s.kind === "set_speed" && s.axis === 4 && s.value === 100).length, 13);
  assert.equal(steps.filter((s) => s.kind === "heater").length, 0);
  // TODO Task 3: layer_end heights below reflect the INTERIM uniform-body compiler that still runs the
  // new thick_precoat/thin_precoat phases through the old per-layer body; the thick-precoat body is
  // rewritten in Task 3. Update these expectations then.
  const ends = steps.filter((s) => s.label === "layer_end").map((s) => s.part_height_mm);
  assert.equal(ends[0], 5); // first thick_precoat layer
  assert.ok(Math.abs((ends.at(-1) ?? 0) - 40.4) < 1e-9); // last postcoat layer, total stack
  assert.equal(steps.filter((s) => s.label === "layer_start").length, 16);
});

test("describeStep", () => {
  const s = compilePrint(DEFAULT_PLAN);
  assert.equal(describeStep(s[0]), "home all");
  assert.equal(describeStep(s[4]), "feed → 145 mm");
  assert.equal(describeStep(null), "—");
});
