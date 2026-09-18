import { test } from "node:test";
import assert from "node:assert/strict";
import { humanStamp, recordingFilename, snapshotFilename, snapshotOverlay, snapshotStamp } from "./camera_export.ts";

// Built from LOCAL parts, so formatting (also local) is timezone-stable across environments.
const D = new Date(2026, 8, 17, 2, 13, 5); // 2026-09-17 02:13:05 local

test("snapshotStamp is filename-safe local time", () => {
  assert.equal(snapshotStamp(D), "2026-09-17_02-13-05");
});

test("humanStamp is a readable local timestamp", () => {
  assert.equal(humanStamp(D), "2026-09-17 02:13:05");
});

test("filenames embed the role and timestamp with the right extension", () => {
  assert.equal(snapshotFilename("overview", D), "vpi-overview-2026-09-17_02-13-05.png");
  assert.equal(recordingFilename("science", D), "vpi-science-2026-09-17_02-13-05.webm");
});

test("overlay carries role, timestamp, resolution, and an optional run", () => {
  assert.equal(snapshotOverlay("science", 1920, 1080, D), "science · 2026-09-17 02:13:05 · 1920×1080");
  assert.equal(snapshotOverlay("overview", 3840, 2160, D, "run_0007"), "overview · 2026-09-17 02:13:05 · 3840×2160 · run run_0007");
});

test("single-digit month/day/time components are zero-padded", () => {
  const d = new Date(2026, 0, 3, 9, 4, 7); // 2026-01-03 09:04:07
  assert.equal(snapshotStamp(d), "2026-01-03_09-04-07");
});
