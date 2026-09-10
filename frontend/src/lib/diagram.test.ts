import { test } from "node:test";
import assert from "node:assert/strict";
import { markerClass } from "./diagram.ts";
test("live vs model marker classes", () => {
  assert.equal(markerClass("live", false), "mk-live");
  assert.equal(markerClass("live", true), "mk-live mk-moving");
  assert.equal(markerClass("model", false), "mk-model");
  assert.equal(markerClass("model", true), "mk-model mk-moving");
});
