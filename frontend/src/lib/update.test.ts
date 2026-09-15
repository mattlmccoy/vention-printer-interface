import { test } from "node:test";
import assert from "node:assert/strict";
import { operatorBehind, detectOs, updateCommand, type Os } from "./update.ts";

test("operatorBehind is true only when the operator version is older than the site's", () => {
  assert.equal(operatorBehind("0.1.9", "0.2.0"), true);    // behind
  assert.equal(operatorBehind("0.2.0", "0.2.0"), false);   // same
  assert.equal(operatorBehind("0.3.0", "0.2.0"), false);   // operator ahead (site not yet deployed)
  assert.equal(operatorBehind("0.4.9", "0.4.10"), true);   // numeric, not lexical (9 < 10)
  assert.equal(operatorBehind("1.0.0", "0.9.9"), false);   // major dominates
});

test("operatorBehind is false when a version is missing or unparseable (never nag on unknown)", () => {
  assert.equal(operatorBehind(null, "0.2.0"), false);
  assert.equal(operatorBehind("", "0.2.0"), false);
  assert.equal(operatorBehind("dev", "0.2.0"), false);
  assert.equal(operatorBehind("0.1.9", ""), false);
});

test("detectOs maps user-agent strings to a platform", () => {
  assert.equal(detectOs("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"), "mac");
  assert.equal(detectOs("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"), "windows");
  assert.equal(detectOs("Mozilla/5.0 (X11; Linux x86_64)"), "linux");
  assert.equal(detectOs("something weird"), "other");
});

test("updateCommand gives the right install one-liner per OS", () => {
  const oses: Os[] = ["mac", "linux", "windows", "other"];
  for (const os of oses) assert.ok(updateCommand(os).command.length > 0);
  assert.match(updateCommand("mac").command, /install\.sh \| bash/);
  assert.match(updateCommand("linux").command, /install\.sh \| bash/);
  assert.match(updateCommand("windows").command, /install\.ps1 \| iex/);
  assert.match(updateCommand("other").command, /install\.sh/);
  // points at the vention repo, not FLIR
  assert.match(updateCommand("mac").command, /vention-printer-interface/);
});
