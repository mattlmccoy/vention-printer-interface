import { test } from "node:test";
import assert from "node:assert/strict";
import { warningsKey, showWarnings } from "./alerts.ts";

test("warnings show until dismissed, and come back when the warning text changes", () => {
  const w = ["heater near limit", "drives slow"];
  assert.equal(showWarnings(w, null), true);                 // nothing dismissed yet
  assert.equal(showWarnings(w, warningsKey(w)), false);      // dismissed this exact set
  assert.equal(showWarnings(["drives slow", "heater near limit"], warningsKey(w)), false); // order-insensitive
  assert.equal(showWarnings([...w, "e-stop released"], warningsKey(w)), true); // new warning -> back
});

test("no warnings -> nothing to show", () => {
  assert.equal(showWarnings([], null), false);
  assert.equal(showWarnings(undefined, null), false);
});
