import { test } from "node:test";
import assert from "node:assert/strict";
import { primingSteps } from "./priming.ts";

test("plain-language priming sequence: up, down, load, thick precoats", () => {
  const s = { part_top_mm: 0, feed_cavity_mm: 30, level_recoat_end_mm: 925, level_recoat_start_mm: 350, n_thick_precoats: 2, thick_feed_mm: 7 };
  const lines = primingSteps(s);
  assert.match(lines[0], /build.*piston.*up/i);
  assert.match(lines[1], /feed.*piston.*down/i);
  assert.ok(lines.some((l) => /load powder/i.test(l)));
  const thick = lines.filter((l) => /thick precoat/i.test(l));
  assert.equal(thick.length, 2); // one line per thick precoat
  assert.ok(/925/.test(thick[0]) && /feed up 7/i.test(thick[0]));
});
