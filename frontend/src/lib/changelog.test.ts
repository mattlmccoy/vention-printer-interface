import { test } from "node:test";
import assert from "node:assert/strict";
import { CHANGELOG, CHANGELOG_VERSION } from "./changelog.ts";
import { operatorBehind } from "./update.ts";

test("CHANGELOG_VERSION is the newest changelog entry", () => {
  assert.equal(CHANGELOG_VERSION, CHANGELOG[0].version);
});

test("every changelog entry is well-formed (semver, ISO date, >=1 change)", () => {
  for (const r of CHANGELOG) {
    assert.match(r.version, /^\d+\.\d+\.\d+$/);
    assert.match(r.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(r.changes.length >= 1);
  }
});

test("an operator older than the newest console version is flagged behind (via lib/update)", () => {
  // Ties the changelog to the real update path: operator on the prior release is 'behind' the top.
  assert.equal(operatorBehind(CHANGELOG[1].version, CHANGELOG_VERSION), true);
  assert.equal(operatorBehind(CHANGELOG_VERSION, CHANGELOG_VERSION), false);
});
