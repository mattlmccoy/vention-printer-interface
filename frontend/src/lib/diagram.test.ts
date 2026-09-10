import { test } from "node:test";
import assert from "node:assert/strict";
import { markerClass, pistonArrow } from "./diagram.ts";
test("live vs model marker classes", () => {
  assert.equal(markerClass("live", false), "mk-live");
  assert.equal(markerClass("live", true), "mk-live mk-moving");
  assert.equal(markerClass("model", false), "mk-model");
  assert.equal(markerClass("model", true), "mk-model mk-moving");
});
test("piston arrow direction from position delta", () => {
  assert.equal(pistonArrow(10, 12), "down");  // position grows -> piston descends -> down
  assert.equal(pistonArrow(12, 10), "up");    // position shrinks -> piston rises -> up
  assert.equal(pistonArrow(10, 10), null);    // no movement
  assert.equal(pistonArrow(null, 10), null);  // unknown prev -> no arrow
});
