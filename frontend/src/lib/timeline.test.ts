import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PLAN, type Step } from "./print_settings.ts";
import { phrase, currentTimelineIndex, currentStage, PHASE_LABEL, TIMELINE_NOISE } from "./timeline.ts";

const plan = { ...DEFAULT_PLAN, recoater_end_mm: 950, printhead_end_mm: 800, heater_end_mm: 425 };
const S = (index: number, phase: string, layer: number, kind: Step["kind"], axis: number | null, value: number | null): Step =>
  ({ index, phase, layer, kind, axis, value, label: "", part_height_mm: 0 });

test("phrase names the meaningful moves in plain language", () => {
  assert.equal(phrase(S(1, "printing", 3, "move_rel", 1, 0.2), plan), "build piston down 0.2 mm");
  assert.equal(phrase(S(2, "printing", 3, "move_abs", 4, 950), plan), "spreading powder");
  assert.equal(phrase(S(3, "printing", 3, "move_abs", 3, 800), plan), "printhead pass");
  assert.equal(phrase(S(4, "printing", 3, "dwell", null, null), plan), "settling");
});

test("currentTimelineIndex returns the last row at/before the active step", () => {
  const rows = [S(2, "printing", 3, "move_rel", 1, 0.2), S(5, "printing", 3, "move_abs", 4, 950), S(9, "printing", 4, "move_abs", 3, 800)];
  assert.equal(currentTimelineIndex(rows, 7), 5); // step 7 is between rows 5 and 9 -> row 5 is active
  assert.equal(currentTimelineIndex(rows, 5), 5); // exact
  assert.equal(currentTimelineIndex(rows, 1), -1); // before the first row
  assert.equal(currentTimelineIndex(rows, 100), 9); // past the last row
});

test("currentStage summarizes the active step: friendly group + action + index", () => {
  const rows = [S(2, "thin_precoat", 1, "move_rel", 1, 0.2), S(5, "printing", 3, "move_abs", 4, 950), S(9, "printing", 4, "move_abs", 3, 800)];
  const cur = currentStage(rows, 6, plan);
  assert.deepEqual(cur, { group: "printing · layer 3", action: "spreading powder", stepIndex: 5 });
  // precoat phase uses the friendly label, no "layer" suffix when layer is 0
  assert.equal(currentStage([S(2, "thin_precoat", 0, "move_abs", 4, 950)], 2, plan)?.group, PHASE_LABEL.thin_precoat);
});

test("currentStage is null before any timeline row is active", () => {
  const rows = [S(5, "printing", 3, "move_abs", 4, 950)];
  assert.equal(currentStage(rows, 1, plan), null);
  assert.equal(currentStage([], 10, plan), null);
});

test("TIMELINE_NOISE hides bookkeeping steps", () => {
  assert.ok(TIMELINE_NOISE.has("set_speed") && TIMELINE_NOISE.has("set_accel") && TIMELINE_NOISE.has("wait"));
  assert.ok(!TIMELINE_NOISE.has("move_abs") && !TIMELINE_NOISE.has("dwell"));
});
