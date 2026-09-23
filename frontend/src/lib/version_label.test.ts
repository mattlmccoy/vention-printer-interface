import { test } from "node:test";
import assert from "node:assert/strict";
import { versionLabel } from "./version_label.ts";

test("always shows the operator's version AND commit, even when the semver matches", () => {
  const v = versionLabel({ siteVersion: "0.11.0", siteBuild: "66b787c", opVersion: "0.11.0", opBuild: "a1b2c3d" });
  assert.equal(v.text, "console v0.11.0·66b787c · op v0.11.0·a1b2c3d");
  assert.equal(v.buildsDiffer, true);
});

test("same commit on both sides is not flagged", () => {
  const v = versionLabel({ siteVersion: "0.11.0", siteBuild: "66b787c", opVersion: "0.11.0", opBuild: "66b787c" });
  assert.equal(v.buildsDiffer, false);
});

test("unknown operator build (not a git checkout) shows the version only and never flags", () => {
  const v = versionLabel({ siteVersion: "0.11.0", siteBuild: "66b787c", opVersion: "0.11.0", opBuild: null });
  assert.equal(v.text, "console v0.11.0·66b787c · op v0.11.0");
  assert.equal(v.buildsDiffer, false);
});

test("operator not reported yet -> console only", () => {
  assert.equal(versionLabel({ siteVersion: "0.11.0", siteBuild: "", opVersion: null, opBuild: null }).text, "console v0.11.0");
});
