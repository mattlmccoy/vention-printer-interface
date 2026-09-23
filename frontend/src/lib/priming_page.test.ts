import { test } from "node:test";
import assert from "node:assert/strict";
import { primingBudget, primingStatusLine, stepMoves } from "./priming_page.ts";

// The defaults of control/priming.py PrimingSettings.
const S = { part_top_mm: 0, feed_cavity_mm: 30, level_recoat_start_mm: 950, level_recoat_end_mm: 350, n_thick_precoats: 3, thick_feed_mm: 7 };

// ---- step moves: exactly the motor moves each walkthrough step issues -------------------------

test("build up: the build piston goes to the part-top target", () => {
  assert.deepEqual(stepMoves("build-up", S, null), [
    { n: 1, label: "Build piston to the top", axis: 1, mode: "abs", value: 0, key: "part_top_mm" },
  ]);
});

test("open feed: the feed piston drops to the cavity depth", () => {
  assert.deepEqual(stepMoves("open-feed", S, null).map((m) => [m.axis, m.mode, m.value, m.key]),
    [[2, "abs", 30, "feed_cavity_mm"]]);
});

test("thick precoat: recoater past the feed, feed UP (a negative relative move), spread", () => {
  const m = stepMoves("level", S, null);
  assert.deepEqual(m.map((x) => [x.n, x.axis, x.mode, x.value]), [[1, 4, "abs", 950], [2, 2, "rel", -7], [3, 4, "abs", 350]]);
  // an operator-edited feed amount replaces the saved one for this coat
  assert.equal(stepMoves("level", S, 4.5)[1].value, -4.5);
});

test("steps with no motor move have none; a missing target leaves the move unrunnable", () => {
  assert.deepEqual(stepMoves("amount", S, null), []);
  assert.deepEqual(stepMoves("load", S, null), []);
  assert.deepEqual(stepMoves("finish", S, null), []);
  assert.equal(stepMoves("build-up", null, null)[0].value, null);
});

// ---- powder budget bar -------------------------------------------------------------------------

test("before the thick precoats the need includes their feed and the margin", () => {
  const b = primingBudget({ feedDemandMm: 74.4, thickFeedMm: 21, marginMm: 5, feedPosMm: 100.4, feedReferenced: true, afterPrecoats: false });
  assert.equal(b.needMm, 100.4);
  assert.equal(b.tone, "bad"); // the run-out guard needs STRICTLY more than the need
  const ok = primingBudget({ feedDemandMm: 74.4, thickFeedMm: 21, marginMm: 5, feedPosMm: 101, feedReferenced: true, afterPrecoats: false });
  assert.equal(ok.tone, "ok");
});

test("after the thick precoats only the print's own feed is still needed", () => {
  const b = primingBudget({ feedDemandMm: 74.4, thickFeedMm: 21, marginMm: 5, feedPosMm: 80, feedReferenced: true, afterPrecoats: true });
  assert.equal(b.needMm, 74.4);
  assert.equal(b.tone, "ok");
});

test("an unhomed feed is unknown — never shown as enough", () => {
  const b = primingBudget({ feedDemandMm: 10, thickFeedMm: 21, marginMm: 5, feedPosMm: 0, feedReferenced: false, afterPrecoats: false });
  assert.equal(b.haveMm, null);
  assert.equal(b.tone, "warn");
  assert.match(b.text, /homed/);
});

test("no plan demand yet is unknown too", () => {
  assert.equal(primingBudget({ feedDemandMm: null, thickFeedMm: 21, marginMm: 5, feedPosMm: 50, feedReferenced: true, afterPrecoats: false }).tone, "warn");
});

// ---- one fixed status line ---------------------------------------------------------------------

test("a paused priming macro asks for the powder load with Resume + Abort", () => {
  const l = primingStatusLine({ state: "paused", macro: "priming", reason: "Load powder into the feed cavity, then Resume", step_index: 9, n_steps: 40 }, true);
  assert.equal(l.tone, "warn");
  assert.match(l.text, /Load powder/);
  assert.deepEqual(l.actions, ["resume", "abort"]);
});

test("a running macro shows its progress; a finished one offers capture", () => {
  assert.match(primingStatusLine({ state: "running", macro: "priming", reason: "", step_index: 10, n_steps: 40 }, true).text, /25%/);
  assert.deepEqual(primingStatusLine({ state: "done", macro: "priming", reason: "", step_index: 40, n_steps: 40 }, true).actions, ["capture"]);
});

test("idle / another macro / disconnected read plainly with no actions", () => {
  assert.equal(primingStatusLine(null, false).text, "not connected — connect to run priming moves");
  assert.deepEqual(primingStatusLine({ state: "idle", macro: null, reason: "", step_index: 0, n_steps: 0 }, true).actions, []);
  assert.match(primingStatusLine({ state: "running", macro: null, reason: "", step_index: 3, n_steps: 90 }, true).text, /print is running/);
});
