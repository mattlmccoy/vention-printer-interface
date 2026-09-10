import { test } from "node:test";
import assert from "node:assert/strict";
import { WALKTHROUGH_STEPS, stepHeading } from "./walkthrough.ts";

test("the walkthrough has the six operator-facing steps in order", () => {
  assert.equal(WALKTHROUGH_STEPS.length, 6);
  assert.deepEqual(
    WALKTHROUGH_STEPS.map((s) => s.id),
    ["amount", "build-up", "open-feed", "load", "level", "finish"],
  );
  // Titles are plain-language; the example the operator sees for step 3.
  assert.match(WALKTHROUGH_STEPS[2].title, /open feed cavity/i);
});

test("heading is the walkthrough's own 1-based step, never the compiled macro count", () => {
  assert.equal(stepHeading(0), "Step 1 of 6 — Amount");
  assert.equal(stepHeading(2), "Step 3 of 6 — Open feed cavity");
  assert.equal(stepHeading(5), "Step 6 of 6 — Finish");
});

test("heading clamps out-of-range indices into the valid step range", () => {
  assert.equal(stepHeading(-3), "Step 1 of 6 — Amount");
  assert.equal(stepHeading(99), "Step 6 of 6 — Finish");
});
