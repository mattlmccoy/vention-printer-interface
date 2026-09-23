import { test } from "node:test";
import assert from "node:assert/strict";
import { runStatusChip, runLocationLabel, runIsRestorable } from "./runs.ts";

test("runLocationLabel: local-only or unknown gets no badge", () => {
  assert.equal(runLocationLabel(undefined), null);
  assert.equal(runLocationLabel([]), null);
  assert.equal(runLocationLabel(["local"]), null);
});

test("runIsRestorable: only a drive-only run can be restored to local", () => {
  assert.equal(runIsRestorable(["FLIR SSD"]), true);          // drive-only -> restorable
  assert.equal(runIsRestorable(["local"]), false);            // already local
  assert.equal(runIsRestorable(["local", "FLIR SSD"]), false); // already local (in both)
  assert.equal(runIsRestorable([]), false);
  assert.equal(runIsRestorable(undefined), false);
});

test("runLocationLabel: drive-resident and both-locations get a badge", () => {
  assert.equal(runLocationLabel(["FLIR SSD"]), "on FLIR SSD");         // offloaded, freed locally
  assert.equal(runLocationLabel(["local", "FLIR SSD"]), "local + FLIR SSD"); // copied, in both
  assert.equal(runLocationLabel(["SSD-A", "SSD-B"]), "on SSD-A + SSD-B");
});

test("finished maps to the live (green) success token", () => {
  const c = runStatusChip("finished");
  assert.equal(c.label, "finished");
  assert.equal(c.color, "var(--live)");
});

test("aborted maps to the warn token", () => {
  assert.equal(runStatusChip("aborted").color, "var(--warn)");
});

test("fault maps to the danger token", () => {
  assert.equal(runStatusChip("fault").color, "var(--err)");
});

test("running is an in-progress accent, distinct from finished green", () => {
  const c = runStatusChip("running");
  assert.equal(c.label, "running");
  assert.notEqual(c.color, "var(--live)");
});

test("incomplete and recorded read as neutral, never as success-green", () => {
  assert.equal(runStatusChip("incomplete").color, "var(--muted)");
  assert.equal(runStatusChip("recorded").color, "var(--muted)");
  assert.notEqual(runStatusChip("incomplete").color, "var(--live)");
});

test("an unknown/absent status degrades to a neutral placeholder, not green", () => {
  const c = runStatusChip(undefined);
  assert.notEqual(c.color, "var(--live)");
  assert.ok(c.label.length > 0);
});
