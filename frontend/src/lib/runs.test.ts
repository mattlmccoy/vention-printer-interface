import { test } from "node:test";
import assert from "node:assert/strict";
import { runStatusChip } from "./runs.ts";

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
