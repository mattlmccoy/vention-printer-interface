import { test } from "node:test";
import assert from "node:assert/strict";
import { primingSteps } from "./priming.ts";

test("plain-language priming sequence: up, down, load, level", () => {
  const s = { part_top_mm: 0, feed_cavity_mm: 30, level_recoat_end_mm: 925, level_recoat_start_mm: 350, n_level_passes: 1 };
  const lines = primingSteps(s);
  assert.match(lines[0], /build.*piston.*up/i);
  assert.match(lines[1], /feed.*piston.*down/i);
  assert.ok(lines.some((l) => /load powder/i.test(l)));
  assert.ok(lines.some((l) => /level/i.test(l) && /925/.test(l)));
});
