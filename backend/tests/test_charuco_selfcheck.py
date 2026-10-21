"""The ChArUco self-check scorer (vision/charuco_selfcheck.py) against synthetic ground truth.

Spec docs/superpowers/specs/2026-10-21-charuco-full-calibration-design.md §2: after the sweep's
solve passes, the board is moved and re-photographed; every identified point is mapped through the
PENDING calibration and the distance between every pair is compared with the true board distance.
Pairwise distances do not depend on where the board sits, so a moved/rotated board is scored
without knowing its new pose. Only points inside the calibrated area count.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from tests.autocal_synth import synth_views
from vention_printer_interface.vision.autocal_solve import AutocalResult, AutocalView, solve_autocal
from vention_printer_interface.vision.board_gen import resolve_preset
from vention_printer_interface.vision.charuco_points import MARKER_ID_BASE, BoardPoints
from vention_printer_interface.vision.charuco_selfcheck import (
    SELF_MIN_POINTS,
    score_self_check,
)
from vention_printer_interface.vision.registration import apply_homography, undistort_points

SPEC = resolve_preset("small_cylinder")
SIZE = (1920, 1080)


def _points(v: AutocalView) -> BoardPoints:
    ids = np.asarray(v.ids).reshape(-1, 1)
    kinds = np.where(ids.ravel() >= MARKER_ID_BASE, "marker", "corner")
    return BoardPoints(image_points=np.asarray(v.image_points, float).reshape(-1, 2),
                       object_points=np.asarray(v.object_points, float).reshape(-1, 3),
                       ids=ids, kinds=kinds, markers_px=[])


@pytest.fixture(scope="module")
def solved() -> tuple[AutocalResult, list[AutocalView]]:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    return solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE), views


def _to_bed(res: AutocalResult) -> Callable[[np.ndarray], np.ndarray]:
    return lambda px: apply_homography(res.H, undistort_points(px, res.camera_matrix,
                                                               res.dist_coeffs))


def _moved_board() -> list[BoardPoints]:
    # The board rotated 25 deg and 10 mm away from where it was swept, photographed at the pose.
    views, _ = synth_views(spec=SPEC, with_markers=True, board_rotation_deg=25.0,
                           shifts_mm=(10.0,), seed=11)
    return [_points(v) for v in views]


def test_good_calibration_passes(solved) -> None:  # type: ignore[no-untyped-def]
    res, sweep = solved
    sc = score_self_check(_moved_board(), _to_bed(res), res.valid_region_mm,
                          [v.image_points for v in sweep])
    assert sc.passed, sc.reasons
    assert sc.rms_mm <= 0.05
    assert abs(sc.scale_bias - 1.0) < 0.002
    assert sc.n_used >= SELF_MIN_POINTS
    assert sc.moved


def test_scale_error_fails_and_reports_bias(solved) -> None:  # type: ignore[no-untyped-def]
    res, _ = solved
    base = _to_bed(res)
    sc = score_self_check(_moved_board(), lambda px: 1.01 * base(px), res.valid_region_mm)
    assert sc.scale_bias == pytest.approx(1.01, abs=1e-3)
    assert not sc.passed
    assert any("RMS" in r for r in sc.reasons)


def test_points_outside_area_are_not_counted(solved) -> None:  # type: ignore[no-untyped-def]
    res, _ = solved
    views = _moved_board()
    to_bed = _to_bed(res)
    bed = to_bed(views[0].image_points)
    cx, cy = np.median(bed, axis=0)
    small = [(cx - 15, cy - 15), (cx + 15, cy - 15), (cx + 15, cy + 15), (cx - 15, cy + 15)]
    sc = score_self_check(views, to_bed, small)
    total = sum(len(v.image_points) for v in views)
    assert sc.n_outside > 0
    assert sc.n_used + sc.n_outside == total
    full = score_self_check(views, to_bed, res.valid_region_mm)
    assert sc.n_used < full.n_used


def test_too_few_points_fails_with_reason(solved) -> None:  # type: ignore[no-untyped-def]
    res, _ = solved
    views = _moved_board()
    to_bed = _to_bed(res)
    bed = to_bed(views[0].image_points)
    cx, cy = bed[0]
    tiny = [(cx - 1, cy - 1), (cx + 1, cy - 1), (cx + 1, cy + 1), (cx - 1, cy + 1)]
    sc = score_self_check(views, to_bed, tiny)
    assert not sc.passed
    assert sc.n_used < SELF_MIN_POINTS
    assert any(str(SELF_MIN_POINTS) in r for r in sc.reasons)


def test_self_check_flags_an_unmoved_board(solved) -> None:  # type: ignore[no-untyped-def]
    # Review Focus 2: photos identical to a sweep view still score, but say the board did not move.
    res, sweep = solved
    same = [_points(min(sweep, key=lambda v: abs(v.recoater_mm - 463.3)))]
    sc = score_self_check(same, _to_bed(res), res.valid_region_mm,
                          [v.image_points for v in sweep])
    assert sc.n_used >= SELF_MIN_POINTS
    assert not sc.moved
    assert any("did not move" in r for r in sc.reasons)
