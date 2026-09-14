"""Per-run dimensional analysis + persistence (Lane A, Task 3).

Covers the three plan-required behaviors plus the manual-ROI happy path:
  (a) ROI-from-layout math (pure transform),
  (b) honest ``no_capture`` status (no false-green zeros) when a run has no capture,
  (c) report schema round-trip (write -> read analysis/dimensional.json),
  (d) manual-ROI "ok" path against the real dot fixture,
  (e) ``roi_failed`` when auto-location cannot find the anchor circle.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from vention_printer_interface.analysis.dimensional import (
    DimensionalReport,
    analyze_run,
    load_report,
    mm_box_to_px_rect,
)

FX = Path(__file__).parent / "fixtures" / "first-good-test"
FIXTURE_PX_PER_MM = 125.98425196850394
FIXTURE_MM_PER_PX = 1.0 / FIXTURE_PX_PER_MM


def _make_run(
    base: Path,
    image: np.ndarray,
    mm_per_px: float | None,
    *,
    name: str = "20260914_gold_standard",
    layer: int = 1,
    stage: str = "post_jet",
) -> Path:
    """Create a minimal recorded-run dir: registered PNG + sidecar + manifest."""
    run = base / name
    d = run / "vision" / f"layer_{layer:04d}"
    d.mkdir(parents=True)
    cv2.imwrite(str(d / f"{stage}.png"), image)
    sidecar: dict = {"layer": layer, "stage": stage}
    if mm_per_px is not None:
        sidecar["registered_space"] = {"mm_per_px": mm_per_px}
    (d / f"{stage}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    manifest = [
        {
            "run_id": name,
            "layer": layer,
            "stage": stage,
            "registered": f"vision/layer_{layer:04d}/{stage}.png",
        }
    ]
    (run / "vision" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


# ---------------------------------------------------------------------------
# (a) Pure ROI-from-layout transform
# ---------------------------------------------------------------------------
def test_mm_box_to_px_rect_center_based_y_up() -> None:
    # Circle center at (1000, 1000) px, 10 px/mm. A feature box whose top-left corner
    # is at (-9.1 mm, +22.0 mm) in center-based coords (+y up), sized 26x26 mm.
    rect = mm_box_to_px_rect((1000, 1000), px_per_mm=10.0, box_mm=(-9.1, 22.0, 26.0, 26.0))
    # x = 1000 + (-9.1 * 10) = 909 ; y = 1000 - (22.0 * 10) = 780 (down is +y in pixels)
    assert rect == (909, 780, 260, 260)


# ---------------------------------------------------------------------------
# (b) Honest no_capture (no false-green zeros)
# ---------------------------------------------------------------------------
def test_no_capture_is_not_false_green(tmp_path: Path) -> None:
    run = tmp_path / "empty_run"
    run.mkdir()
    report = analyze_run(run)
    assert report.status == "no_capture"
    assert report.features == {}  # no fabricated metrics
    assert report.compensation is None
    assert report.px_per_mm is None
    assert report.message  # explains why


# ---------------------------------------------------------------------------
# (c)+(d) Manual-ROI "ok" path + round-trip persistence
# ---------------------------------------------------------------------------
def test_manual_roi_ok_and_roundtrip(tmp_path: Path) -> None:
    dot = cv2.imread(str(FX / "dot_roi.png"))
    assert dot is not None
    h, w = dot.shape[:2]
    run = _make_run(tmp_path, dot, FIXTURE_MM_PER_PX)

    report = analyze_run(run, rois={"dot": [0, 0, w, h]})
    assert report.status == "ok"
    assert report.captured_from == {"layer": 1, "stage": "post_jet"}
    assert abs(report.px_per_mm - FIXTURE_PX_PER_MM) < 1e-6
    assert report.features["dot"]["num_blobs"] == 25.0
    assert report.compensation is not None
    # Real dot X spacing error is ~-0.44% (> deadband) -> a real scale correction.
    assert report.compensation["scale_x"] > 1.0

    # Persisted to <run>/analysis/dimensional.json and reloads identically.
    loaded = load_report(run)
    assert loaded == report.to_dict()
    assert DimensionalReport.from_dict(loaded) == report


# ---------------------------------------------------------------------------
# (e) roi_failed when auto-location cannot anchor
# ---------------------------------------------------------------------------
def test_autolocate_failure_is_roi_failed(tmp_path: Path) -> None:
    blank = np.full((400, 400, 3), 255, dtype=np.uint8)  # no circle to anchor on
    run = _make_run(tmp_path, blank, FIXTURE_MM_PER_PX)
    report = analyze_run(run)  # no manual rois -> must auto-locate
    assert report.status == "roi_failed"
    assert report.features == {}  # no fabricated metrics
    assert report.compensation is None
    assert report.message


def test_missing_calibration_is_honest(tmp_path: Path) -> None:
    dot = cv2.imread(str(FX / "dot_roi.png"))
    run = _make_run(tmp_path, dot, None)  # sidecar has no mm_per_px
    report = analyze_run(run, rois={"dot": [0, 0, 10, 10]})
    assert report.status == "no_calibration"
    assert report.features == {}
    assert report.px_per_mm is None
    assert report.message
