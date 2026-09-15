import { test } from "node:test";
import assert from "node:assert/strict";
import { analysisStatusKind, analysisStatusMessage, calibrationChip, compensationRows, featureTiles, roiEditPrompt } from "./analysis.ts";
import type { DimensionalReport } from "./api.ts";

test("status kind: ok vs empty vs error", () => {
  assert.equal(analysisStatusKind("ok"), "ok");
  assert.equal(analysisStatusKind("not_run"), "empty");
  assert.equal(analysisStatusKind("no_capture"), "error");
  assert.equal(analysisStatusKind("no_calibration"), "error");
  assert.equal(analysisStatusKind("roi_failed"), "error");
});

test("status message is honest and specific (never blank for a problem)", () => {
  assert.match(analysisStatusMessage("not_run", ""), /not.*analy/i);
  assert.match(analysisStatusMessage("no_capture", ""), /capture/i);
  assert.match(analysisStatusMessage("roi_failed", "circle not found"), /circle not found/);
  assert.equal(analysisStatusMessage("ok", ""), "");
});

test("compensation rows format scale + yaw, dash when yaw missing", () => {
  const rows = compensationRows({ scale_x: 1.004428, scale_y: 0.999559, yaw_deg: 1.3, human: "", notes: [] });
  assert.deepEqual(rows.map((r) => r.label), ["scale · X", "scale · Y", "yaw"]);
  assert.equal(rows[0].value, "1.0044");
  assert.equal(rows[1].value, "0.9996");
  assert.equal(rows[2].value, "+1.30°");
  const noYaw = compensationRows({ scale_x: 1, scale_y: 1, yaw_deg: null, human: "", notes: [] });
  assert.equal(noYaw[2].value, "—");
});

test("feature tiles pull the key error metrics from the features dict", () => {
  const report: DimensionalReport = {
    run: "r", status: "ok",
    features: {
      dot: { spacing_x_error_pct: -0.44, spacing_y_error_pct: 0.05, diameter_error_pct: 4.34, num_blobs: 25 },
      checkerboard: { square_error_pct: 0.62, angle_deg: -47.11, checkerboard_angle_error_deg: -2.11 },
    },
  };
  const tiles = featureTiles(report);
  const byk = Object.fromEntries(tiles.map((t) => [t.k, t.v]));
  assert.equal(byk["dot spacing X"], "-0.44%");
  assert.equal(byk["dot Ø err"], "+4.34%");
  assert.equal(byk["checker sq"], "+0.62%");
  assert.equal(byk["checker yaw"], "-2.11°"); // yaw ERROR, not the raw grid angle
  // a report with no features yields no tiles (honest empty, not zeros)
  assert.equal(featureTiles({ run: "r", status: "no_capture", features: {} }).length, 0);
});

test("roiEditPrompt: actionable copy on roi_failed, null otherwise", () => {
  assert.equal(roiEditPrompt("roi_failed"), "Auto-location failed — mark the outer circle");
  assert.equal(roiEditPrompt("ok"), null);
  assert.equal(roiEditPrompt("no_capture"), null);
});

test("calibrationChip: warning text when present, null otherwise", () => {
  assert.equal(calibrationChip({ calibration_warning: "circle scale differs by 4.2% — using the circle" }), "circle scale differs by 4.2% — using the circle");
  assert.equal(calibrationChip({}), null);
  assert.equal(calibrationChip({ calibration_warning: null }), null);
  assert.equal(calibrationChip({ calibration_warning: "" }), null);
});
