"""Parity test: the vendored RFAM metrology must reproduce the known-good tool output.

This proves the vendored copy of ``feature_analysis`` matches the real tool on a real,
captured fixture (``first-good-test``) — a data-contract check, not an invented one.

CALIBRATION NOTE (deviation from the plan, backed by evidence):
The plan/spec state the fixture was scanned at ``px_per_mm=118.11``. That is WRONG.
Reality: the fixture's own ``results.csv`` records ``effective_px_per_mm=125.98425196850394``
(= 3200 dpi / 25.4) at ``scale_used=1.0`` for the checkerboard row, and running the tool at
118.11 yields spacing_x_error_pct=+5.45 (nowhere near the CSV's -0.4379) while 125.98
reproduces every dot metric within 0.005. So the true calibration is 125.98 px/mm and that
is what pins parity here.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import cv2

from vention_printer_interface.analysis.feature_analysis import (
    analyze_checkerboard,
    analyze_dot_array,
)

FX = Path(__file__).parent / "fixtures" / "first-good-test"

# The fixture scan calibration, read from the fixture's own results.csv
# (checkerboard row: effective_px_per_mm at scale 1.0). NOT the plan's 118.11.
PX_PER_MM = 125.98425196850394


def _expected(feature: str, col: str) -> float:
    """Return one column from the ``feature`` row of the fixture's results.csv."""
    with open(FX / "results.csv") as f:
        for row in csv.DictReader(f):
            if row.get("feature") == feature:
                return float(row[col])
    raise KeyError(f"no row for feature={feature!r}")


def test_dot_array_matches_known_good_tool_output() -> None:
    roi = cv2.imread(str(FX / "dot_roi.png"))
    assert roi is not None, "dot_roi.png missing/unreadable"
    summary, _details = analyze_dot_array(
        roi, px_per_mm=PX_PER_MM, nominal_diameter_mm=2.0, nominal_spacing_mm=6.0
    )
    assert summary["num_blobs"] == _expected("dot", "num_blobs")
    assert math.isclose(
        summary["spacing_x_error_pct"], _expected("dot", "spacing_x_error_pct"), abs_tol=0.05
    )
    assert math.isclose(
        summary["spacing_y_error_pct"], _expected("dot", "spacing_y_error_pct"), abs_tol=0.05
    )
    assert math.isclose(
        summary["diameter_error_pct"], _expected("dot", "diameter_error_pct"), abs_tol=0.05
    )


def test_checkerboard_matches_known_good_tool_output() -> None:
    roi = cv2.imread(str(FX / "checkerboard_roi.png"))
    assert roi is not None, "checkerboard_roi.png missing/unreadable"
    summary = analyze_checkerboard(roi, px_per_mm=PX_PER_MM, nominal_square_mm=2.0)
    assert summary["found"] == 1
    # num_squares is an exact integer match; mean square size pins the true parity.
    assert summary["num_squares"] == int(_expected("checkerboard", "num_squares"))
    assert math.isclose(
        summary["mean_square_mm"], _expected("checkerboard", "mean_square_mm"), abs_tol=0.01
    )
    # square_error_pct is derived from mean_square (agrees to ~0.001 mm); the % amplifies
    # sub-pixel segmentation noise between numpy/opencv versions, so 0.1% is honest here.
    assert math.isclose(
        summary["square_error_pct"], _expected("checkerboard", "square_error_pct"), abs_tol=0.1
    )
    assert math.isclose(
        summary["angle_deg"], _expected("checkerboard", "angle_deg"), abs_tol=0.05
    )
