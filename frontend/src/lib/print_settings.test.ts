import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PLAN, compilePrint, describeStep, totalLayers, totalThickness, validate } from "./print_settings.ts";

test("defaults match V1.py and the backend", () => {
  // thin 0.2*2 + printing 2*10 + postcoat 5*1 = 25.4 mm over 13 layers (thick precoats now prime)
  assert.ok(Math.abs(totalThickness(DEFAULT_PLAN) - 25.4) < 1e-9);
  assert.equal(totalLayers(DEFAULT_PLAN), 13);
  assert.deepEqual(validate(DEFAULT_PLAN), []);
});

test("printability and travel reasons", () => {
  const bad = { ...DEFAULT_PLAN, printing: { ...DEFAULT_PLAN.printing, n_layers: 100 } };
  assert.match(validate(bad)[0], /thickness/);
  assert.match(validate({ ...DEFAULT_PLAN, recoater_end_mm: 5000 })[0], /recoater_end_mm/);
});

test("compile matches the backend order for one print layer (54 steps, heater on)", () => {
  const one = { ...DEFAULT_PLAN,
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 }, heater_enabled: true };
  const steps = compilePrint(one);
  // 14 setup (gantry homes + profiles + printhead-to-start) + 8 phase setup + 26 layer + 6 finish = 54
  assert.equal(steps.length, 54);
  assert.equal(steps[22].label, "layer_start");
  assert.equal(steps[47].label, "layer_end");
  assert.equal(steps[47].part_height_mm, 2);
  assert.deepEqual(steps.map((s) => s.index), [...Array(54).keys()]);
});

test("printing layer: multi-pass jetting + pre-heater drop and return-up", () => {
  const p = { ...DEFAULT_PLAN,
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

test("compile of the full default plan: 13 layers, heights, resets", () => {
  const steps = compilePrint(DEFAULT_PLAN);
  // heater disabled by default -> no 425->600 sweep and no heater toggles anywhere
  assert.equal(steps.filter((s) => s.kind === "move_abs" && s.value === 600).length, 0);
  assert.equal(steps.filter((s) => s.kind === "heater").length, 0);
  // recoater set to 100 mm/s: setup profile + three non-empty phase setups = 4 (no per-layer resets)
  assert.equal(steps.filter((s) => s.kind === "set_speed" && s.axis === 4 && s.value === 100).length, 4);
  // the print begins at the thin precoats (part drops 0.2 each, 2 layers) then printing (2.0*10) =
  // 20.4 mm; postcoat is a cover pass (no part drop) so the stack stays 20.4.
  const ends = steps.filter((s) => s.label === "layer_end").map((s) => s.part_height_mm);
  assert.ok(Math.abs(ends[0] - 0.2) < 1e-9); // first thin_precoat layer (part down 0.2 mm)
  assert.ok(Math.abs(ends[1] - 0.4) < 1e-9); // second thin_precoat layer (part down 0.2 mm)
  assert.ok(Math.abs(ends[2] - 2.4) < 1e-9); // first printing layer (+2.0 mm)
  assert.ok(Math.abs((ends.at(-1) ?? 0) - 20.4) < 1e-9); // last (postcoat) layer keeps the stack
  assert.equal(steps.filter((s) => s.label === "layer_start").length, 13);
});

test("heater-on full plan sweeps 425->600 once per printing layer", () => {
  const steps = compilePrint({ ...DEFAULT_PLAN, heater_enabled: true });
  // one 425->600 sweep per printing layer (10); heater toggles on+off each = 20 (precoats never heat)
  assert.equal(steps.filter((s) => s.kind === "move_abs" && s.value === 600).length, 10);
  assert.equal(steps.filter((s) => s.kind === "heater").length, 20);
});

test("postcoat toggle off emits no postcoat steps", () => {
  assert.ok(compilePrint(DEFAULT_PLAN).some((s) => s.phase === "postcoat"));
  assert.ok(!compilePrint({ ...DEFAULT_PLAN, postcoat_enabled: false }).some((s) => s.phase === "postcoat"));
});

test("describeStep", () => {
  const s = compilePrint(DEFAULT_PLAN);
  assert.equal(describeStep(s[0]), "home printhead"); // primed start homes the gantries only
  assert.equal(describeStep(s[4]), "part speed 2.5 mm/s");
  assert.equal(describeStep(null), "—");
});
