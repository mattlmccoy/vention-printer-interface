import { test } from "node:test";
import assert from "node:assert/strict";
import { operatorBehind, detectOs, updateCommand, inPlaceUpdateCommand, mismatchAdvice, osFromPlatform, type Os } from "./update.ts";

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

// ---- console ≠ operator: which side is behind, and the in-place update command ------------------

test("the operator's OS comes from its own platform string (it may not be the browser's machine)", () => {
  assert.equal(osFromPlatform("macOS-27.0-arm64-arm-64bit-Mach-O"), "mac"); // captured from /api/health
  assert.equal(osFromPlatform("Windows-11-10.0.26100-SP0"), "windows");
  assert.equal(osFromPlatform("Linux-6.8.0-x86_64-with-glibc2.39"), "linux");
  assert.equal(osFromPlatform(null), null);
  assert.equal(osFromPlatform("Plan9"), null);
});

test("the in-place update switches to main, pulls, syncs WITH the plots extra, and restarts the service", () => {
  const mac = inPlaceUpdateCommand("mac").command;
  assert.match(mac, /git checkout main && git pull --ff-only/);
  assert.match(mac, /uv sync --inexact --extra plots/);
  assert.match(mac, /launchctl kickstart -k gui\/\$\(id -u\)\/com\.binderjet\.operator/);
  assert.doesNotMatch(mac, /install\.sh/); // re-installing regenerates the plist and drops its flags
  const win = inPlaceUpdateCommand("windows").command;
  assert.match(win, /git checkout main; git pull --ff-only/);
  assert.match(win, /Stop-ScheduledTask -TaskName "Binder Jet Console operator"; Start-ScheduledTask -TaskName "Binder Jet Console operator"/);
  assert.match(inPlaceUpdateCommand("linux").command, /systemctl --user restart vpi-operator\.service/);
});

test("operator older than the console: update the operator", () => {
  const a = mismatchAdvice({ siteVersion: "0.12.0", opVersion: "0.11.1" });
  assert.equal(a.behind, "operator");
  assert.equal(a.showCommand, true);
});

test("console older than the operator: reload the page, no operator command", () => {
  const a = mismatchAdvice({ siteVersion: "0.11.1", opVersion: "0.12.0" });
  assert.equal(a.behind, "console");
  assert.equal(a.showCommand, false);
  assert.match(a.text, /reload/i);
});

test("same version, different commit: reload first, then update the operator if it still differs", () => {
  const a = mismatchAdvice({ siteVersion: "0.12.0", opVersion: "0.12.0" });
  assert.equal(a.behind, "unknown");
  assert.equal(a.showCommand, true);
  assert.match(a.text, /reload/i);
});
