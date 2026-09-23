import { test } from "node:test";
import assert from "node:assert/strict";
import { feedBudgetLine, isFeedBudgetRefusal } from "./feed_budget.ts";

const base = { demand_mm: 74.4, layers_total: 186, unknown_reason: null };

test("enough powder reads ok with the margin left over", () => {
  const l = feedBudgetLine({ ...base, available_mm: 100, sufficient: true, layers_supported: 186 });
  assert.equal(l.tone, "ok");
  assert.match(l.text, /74\.4 mm needed · 100 mm in the feed/);
});

test("a short feed says where the print would stop (the 2026-09-22 pyramid run)", () => {
  const l = feedBudgetLine({ ...base, available_mm: 20, sufficient: false, layers_supported: 49 });
  assert.equal(l.tone, "bad");
  assert.match(l.text, /stops after layer 49 of 186/);
});

test("an unverifiable feed is a warning with the reason, never ok", () => {
  const l = feedBudgetLine({ ...base, available_mm: null, sufficient: null, layers_supported: null, unknown_reason: "the feed piston hasn't been homed since power-on" });
  assert.equal(l.tone, "warn");
  assert.match(l.text, /74\.4 mm needed/);
  assert.match(l.text, /homed/);
});

test("no budget yet (not loaded / fetch failed) is unknown, never ok", () => {
  assert.equal(feedBudgetLine(null).tone, "warn");
});

test("recognises the start endpoint's powder refusals (and nothing else)", () => {
  assert.equal(isFeedBudgetRefusal(new Error("409 Not enough powder in the feed: this print needs 74.4 mm")), true);
  assert.equal(isFeedBudgetRefusal(new Error("409 Can't check the powder in the feed: the feed piston hasn't been homed")), true);
  assert.equal(isFeedBudgetRefusal(new Error("409 not armed — press ARM")), false);
  assert.equal(isFeedBudgetRefusal("nope"), false);
});
