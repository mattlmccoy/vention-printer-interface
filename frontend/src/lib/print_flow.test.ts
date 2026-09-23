import { test } from "node:test";
import assert from "node:assert/strict";
import { printFlow } from "./print_flow.ts";

const ready = { state: "ready" as const, reason: "primed for this plan" };
const states = (f: ReturnType<typeof printFlow>) => f.steps.map((s) => `${s.id}:${s.state}`);

test("saved, valid plan on a bed primed for it: all set, START goes", () => {
  const f = printFlow({ planValid: true, dirty: false, prime: ready });
  assert.deepEqual(states(f), ["configure:done", "prime:done", "start:current"]);
  assert.equal(f.startMode, "go");
});

test("never primed: the prime step is current and START is blocked", () => {
  const f = printFlow({ planValid: true, dirty: false, prime: { state: "none", reason: "the bed hasn't been primed" } });
  assert.deepEqual(states(f), ["configure:done", "prime:current", "start:todo"]);
  assert.equal(f.startMode, "blocked");
});

test("primed for another plan / used / unverified: START needs an explicit override", () => {
  for (const state of ["other_plan", "used", "unverified"] as const) {
    const f = printFlow({ planValid: true, dirty: false, prime: { state, reason: `because ${state}` } });
    assert.equal(f.steps[1].state, "current");
    assert.equal(f.startMode, "override");
    assert.match(f.startNote, new RegExp(`because ${state}`));
  }
});

test("invalid settings block everything at configure", () => {
  const f = printFlow({ planValid: false, dirty: true, prime: ready });
  assert.equal(f.steps[0].state, "current");
  assert.equal(f.startMode, "blocked");
});

test("unsaved edits: configure is current and the prime check is flagged as pending the save", () => {
  const f = printFlow({ planValid: true, dirty: true, prime: ready });
  assert.equal(f.steps[0].state, "current");
  assert.match(f.steps[1].note, /after you save/);
  assert.equal(f.startMode, "go"); // START saves first; the operator re-checks the prime
});

test("an operator that doesn't report priming status is unknown, never ready", () => {
  const f = printFlow({ planValid: true, dirty: false, prime: null });
  assert.equal(f.steps[1].state, "current");
  assert.equal(f.startMode, "override");
});
