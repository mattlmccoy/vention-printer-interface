import { test } from "node:test";
import assert from "node:assert/strict";
import { CAPTURE_SEAT_MM, CAPTURE_STAGES, DEFAULT_PLAN, compilePrint, describeStep, multipassMismatch, toggleCaptureStage, totalLayers, totalThickness, validate } from "./print_settings.ts";

test("multipassMismatch warns only when the slicer declared a factor the print doesn't match", () => {
  assert.equal(multipassMismatch(3, 1), true);
  assert.equal(multipassMismatch(3, 3), false);
  assert.equal(multipassMismatch(null, 1), false);
  assert.equal(multipassMismatch(undefined, 2), false);
  assert.equal(multipassMismatch(0, 1), false); // 0 isn't a real multipass factor
});

test("toggleCaptureStage removes a present stage, keeping canonical order", () => {
  assert.deepEqual(toggleCaptureStage(["pre_jet", "post_jet", "post_heat"], "post_jet"), ["pre_jet", "post_heat"]);
});

test("toggleCaptureStage adds a missing stage in canonical order (not append order)", () => {
  assert.deepEqual(toggleCaptureStage(["post_heat"], "pre_jet"), ["pre_jet", "post_heat"]);
});

test("toggleCaptureStage drops unknown stages and can empty the set", () => {
  assert.deepEqual(toggleCaptureStage(["post_jet", "bogus"], "post_jet"), []);
  assert.deepEqual(toggleCaptureStage([], "nope"), []);
});

test("the default plan enables all three capture stages", () => {
  assert.deepEqual(DEFAULT_PLAN.capture_stages_enabled, [...CAPTURE_STAGES]);
  assert.equal(DEFAULT_PLAN.capture_hold_s, 2);
});

test("science stages stop at the calibrated pose and hold after each trigger", () => {
  const p = {
    ...DEFAULT_PLAN,
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 },
    postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 },
    capture_stages: true,
    capture_recoater_mm: 454.4,
    capture_settle_s: 0.5,
    capture_hold_s: 2,
  };
  const steps = compilePrint(p);
  for (const stage of CAPTURE_STAGES) {
    const i = steps.findIndex((s) => s.label === `capture:${stage}`);
    assert.ok(i >= 3);
    assert.deepEqual([steps[i - 3].kind, steps[i - 3].axis, steps[i - 3].value], ["move_abs", 4, 454.4]);
    assert.equal(steps[i - 2].kind, "wait");
    assert.equal(steps[i - 1].label, "camera settle");
    assert.equal(steps[i + 1].label, "camera capture hold");
  }
});

test("defaults match V1.py and the backend", () => {
  // thin 0.2*2 + printing 2*10 + postcoat 5*1 = 25.4 mm over 13 layers (thick precoats now prime)
  assert.ok(Math.abs(totalThickness(DEFAULT_PLAN) - 25.4) < 1e-9);
  assert.equal(totalLayers(DEFAULT_PLAN), 13);
  assert.deepEqual(validate(DEFAULT_PLAN), []);
});

test("postcoat counts as N layers, just like precoats", () => {
  // Regression: the Job page postcoat control used to hardcode n_layers:1, so multiple
  // postcoats collapsed to a single layer in the counter. totalLayers must count them all.
  const p = { ...DEFAULT_PLAN, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 3 } };
  // base 13 = thin 2 + printing 10 + postcoat 1; bumping postcoat 1->3 adds 2 => 15.
  assert.equal(totalLayers(p), 15);
  assert.equal(compilePrint(p).filter((s) => s.phase === "postcoat" && s.kind === "mark" && s.label === "layer_start").length, 3);
});

test("printability and travel reasons", () => {
  const bad = { ...DEFAULT_PLAN, printing: { ...DEFAULT_PLAN.printing, n_layers: 100 } };
  assert.match(validate(bad)[0], /thickness/);
  assert.match(validate({ ...DEFAULT_PLAN, recoater_end_mm: 5000 })[0], /recoater_end_mm/);
});

test("a build past the piston's max travel is flagged, honoring the settable per-cylinder limit", () => {
  assert.deepEqual(validate(DEFAULT_PLAN), []); // default part_max 72 = build_piston_max 72 → valid
  const deep = { ...DEFAULT_PLAN, part_max_mm: 90 }; // past the 72 mm limit
  assert.ok(validate(deep).some((r) => /max travel/.test(r)));
  const raised = { ...deep, build_piston_max_mm: 100 }; // looser cylinder set to 100 mm
  assert.ok(!validate(raised).some((r) => /max travel/.test(r)));
});

test("compile matches the backend order for one print layer (50 steps, heater on)", () => {
  const one = { ...DEFAULT_PLAN, build_backlash_mm: 0, // V1.py-faithful baseline (default is now 0.15)
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 }, heater_enabled: true };
  const steps = compilePrint(one);
  // 12 setup (gantry homes + profiles, no printhead park) + 8 phase setup + 24 layer + 6 finish = 50.
  // The layer is 24 (not 26): no end-of-layer recoater->950 reposition — it moves out to the spread
  // start only at the NEXT layer's start, after that layer's feed preload (anti-backlash bug fix).
  assert.equal(steps.length, 50);
  assert.equal(steps[20].label, "layer_start");
  assert.equal(steps[43].label, "layer_end");
  assert.equal(steps[43].part_height_mm, 2);
  assert.deepEqual(steps.map((s) => s.index), [...Array(50).keys()]);
  // part drop is the FIRST layer move (V1.py order), before the recoater reposition
  const layer = steps.slice(20).map((s) => [s.kind, s.axis, s.value] as const);
  assert.deepEqual(layer[1], ["move_rel", 1, 2]);          // part drop 2.0 (PART=1)
  assert.deepEqual(layer[3], ["move_abs", 4, one.recoater_end_mm]); // then recoater reposition (RECOATER=4)
  // setup emits no axis move (printhead never parked at 250)
  assert.equal(steps.filter((s) => s.phase === "setup" && (s.kind === "move_abs" || s.kind === "move_rel")).length, 0);
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

test("absolute_layer_seat emits absolute cumulative seat_part targets (no accumulation)", () => {
  const base = { ...DEFAULT_PLAN,
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 2, layer_thickness_mm: 0.2 },
    postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 },
    heater_enabled: true, pre_heater_drop_mm: 1.0, build_backlash_mm: 0.1 };
  // default OFF: relative move_rel, no seat_part
  assert.equal(DEFAULT_PLAN.absolute_layer_seat, false);
  assert.ok(compilePrint(base).some((s) => s.kind === "move_rel" && s.axis === 1));
  assert.ok(!compilePrint(base).some((s) => s.kind === "seat_part"));
  // ON: absolute seat targets are cumulative (layer 1 -> 0.2, layer 2 -> 0.4), not relative
  const on = { ...base, absolute_layer_seat: true };
  const seats = compilePrint(on).filter((s) => s.kind === "seat_part" && s.axis === 1)
    .map((s) => [s.layer, Number(s.value!.toFixed(4))] as const);
  assert.deepEqual(seats, [
    [1, 0.3], [1, 0.2], [1, 0.2],   // descent overshoot+return, then post-heat re-seat
    [2, 0.5], [2, 0.4], [2, 0.4],
  ]);
});

test("imaged printing layer ends the drop on an up-seat even when build backlash is 0", () => {
  const base = { ...DEFAULT_PLAN,
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, layer_thickness_mm: 0.2, n_layers: 1 },
    postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 },
    build_backlash_mm: 0 };
  const partMoves = (p: typeof base) => compilePrint(p)
    .filter((s) => s.kind === "move_rel" && s.axis === 1).map((s) => s.value);
  // captures on: drop overshoots by CAPTURE_SEAT_MM then returns up (net = layer_thickness)
  const on = { ...base, capture_stages: true, capture_stages_enabled: ["pre_jet"] };
  assert.deepEqual(partMoves(on), [0.2 + CAPTURE_SEAT_MM, -CAPTURE_SEAT_MM]);
  // captures off: unchanged single down move
  const off = { ...base, capture_stages: false };
  assert.deepEqual(partMoves(off), [0.2]);
  // backlash already above the floor wins over it
  const big = { ...on, build_backlash_mm: 0.15 };
  assert.deepEqual(partMoves(big), [0.2 + 0.15, -0.15]);
});

test("heater off: printhead returns home, then layer_end with NO end-of-layer recoater reposition", () => {
  const p = { ...DEFAULT_PLAN,
    thin_precoat: { ...DEFAULT_PLAN.thin_precoat, n_layers: 0 },
    printing: { ...DEFAULT_PLAN.printing, n_layers: 1 }, postcoat: { ...DEFAULT_PLAN.postcoat, n_layers: 0 },
    heater_enabled: false };
  const ks = compilePrint(p).filter((s) => s.phase === "printing").map((s) => [s.kind, s.axis, s.value] as const);
  const iJet = ks.findIndex((k) => k[0] === "move_abs" && k[1] === 3 && k[2] === p.printhead_end_mm);
  assert.deepEqual(ks[iJet + 1], ["wait", null, null]);
  assert.deepEqual(ks[iJet + 2], ["move_abs", 3, p.printhead_home_mm]);   // printhead home (its own wait)
  assert.deepEqual(ks[iJet + 3], ["wait", null, null]);
  assert.equal(ks[iJet + 4][0], "mark"); // layer_end right after — no recoater->950 at layer end
  // the recoater's LAST move this layer is the spread home (5), not a reposition to the far end
  const rc = ks.filter((k) => k[0] === "move_abs" && k[1] === 4);
  assert.deepEqual(rc[rc.length - 1], ["move_abs", 4, p.recoater_home_mm]);
  assert.equal(ks.filter((k) => k[0] === "move_abs" && k[1] === 4 && k[2] === p.recoater_end_mm).length, 1);
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
  assert.equal(describeStep(s[4]), "build speed 2.5 mm/s");
  assert.equal(describeStep(null), "—");
});
