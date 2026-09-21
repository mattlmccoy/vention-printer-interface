import { test } from "node:test";
import assert from "node:assert/strict";
import { pistonMaxPatch } from "./pistons.ts";

test("pistonMaxPatch snaps the current position to the 0.1 mm readout and clamps to travel", () => {
  assert.deepEqual(pistonMaxPatch("build_piston_max_mm", 63.24), { build_piston_max_mm: 63.2 });
  assert.deepEqual(pistonMaxPatch("feed_piston_max_mm", 71.96), { feed_piston_max_mm: 72.0 });
  assert.deepEqual(pistonMaxPatch("build_piston_max_mm", 200), { build_piston_max_mm: 145 }); // hard cap
  assert.deepEqual(pistonMaxPatch("build_piston_max_mm", -3), { build_piston_max_mm: 0 });
});
