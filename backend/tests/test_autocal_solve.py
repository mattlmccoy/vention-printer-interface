"""The automatic calibration solve (vision/autocal_solve.py) against synthetic ground truth.

Spec docs/superpowers/specs/2026-10-20-auto-calibration-design.md §7: lens distortion + a bed
homography valid on the print plane at the capture pose; bed +X = increasing recoater mm, origin at
ChArUco corner 0, no mirroring; an encoder-shift scale check; an automatic bed raster.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.autocal_synth import synth_views
from vention_printer_interface.vision.autocal_solve import solve_autocal
from vention_printer_interface.vision.board_gen import resolve_preset
from vention_printer_interface.vision.registration import (
    apply_homography,
    bed_raster_error,
    undistort_points,
)

SPEC = resolve_preset("small_cylinder")
SIZE = (1920, 1080)


def _map(result, pts: np.ndarray) -> np.ndarray:  # type: ignore[no-untyped-def]
    return apply_homography(result.H, undistort_points(pts, result.camera_matrix,
                                                       result.dist_coeffs))


def _capture_view(views, capture_mm):  # type: ignore[no-untyped-def]
    return min(views, key=lambda v: abs(v.recoater_mm - capture_mm))


def test_recovers_the_plane_mapping_within_20_microns() -> None:
    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = _capture_view(views, truth.capture_mm)
    err = _map(res, cap.image_points) - truth.bed_xy(cap.object_points)
    assert float(np.sqrt((err ** 2).sum(axis=1).mean())) <= 0.02


def test_maps_every_view_consistently_across_the_frame() -> None:
    # Off-centre views put the same corners near the frame edges, where distortion is largest. Each
    # maps to its true bed position shifted by -(recoater offset) along bed X.
    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    errs = []
    for v in views:
        expected = truth.bed_xy(v.object_points) - np.array([v.recoater_mm - truth.capture_mm, 0])
        errs.append(_map(res, v.image_points) - expected)
    e = np.vstack(errs)
    assert float(np.sqrt((e ** 2).sum(axis=1).mean())) <= 0.03


@pytest.mark.parametrize("rotation", [0.0, 30.0])
def test_bed_plus_x_is_increasing_recoater_mm(rotation: float) -> None:
    views, truth = synth_views(spec=SPEC, board_rotation_deg=rotation)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = _capture_view(views, truth.capture_mm)
    plus = min(views, key=lambda v: abs(v.recoater_mm - (truth.capture_mm + 20.0)))
    cap_ids, plus_ids = cap.ids.ravel(), plus.ids.ravel()
    shared = [i for i in range(len(cap_ids)) if cap_ids[i] in set(plus_ids)]
    assert len(shared) >= 4
    j = [int(np.where(plus_ids == cap_ids[i])[0][0]) for i in shared]
    at0 = _map(res, cap.image_points[shared])
    at20 = _map(res, plus.image_points[j])
    assert np.allclose(at20[:, 0], at0[:, 0] - 20.0, atol=0.05)
    assert np.allclose(at20[:, 1], at0[:, 1], atol=0.05)
    assert np.allclose(_map(res, cap.image_points), truth.bed_xy(cap.object_points), atol=0.05)


def test_no_mirror_in_the_bed_frame() -> None:
    views, truth = synth_views(spec=SPEC, board_rotation_deg=30.0, camera_yaw_deg=90.0)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = _capture_view(views, truth.capture_mm)
    assert np.allclose(_map(res, cap.image_points), truth.bed_xy(cap.object_points), atol=0.05)
    assert float(np.linalg.det(truth.board_to_bed)) == pytest.approx(1.0)


def test_encoder_scale_error_is_caught() -> None:
    views, truth = synth_views(spec=SPEC, encoder_scale=1.02)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert res.scale_ratio == pytest.approx(1 / 1.02, abs=0.002)
    assert res.shift_rms_mm > 0.1


def test_a_good_run_has_small_shift_and_reprojection_errors() -> None:
    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert res.scale_ratio == pytest.approx(1.0, abs=0.002)
    assert res.shift_rms_mm < 0.05 and res.reprojection_rms_px < 0.2
    assert res.n_views == len(views) and res.image_size == SIZE


def test_solve_refuses_without_a_capture_pose_view() -> None:  # Review Focus 1
    views, truth = synth_views(spec=SPEC)
    far = [v for v in views if abs(v.recoater_mm - truth.capture_mm) > 1.0]
    with pytest.raises(ValueError, match="capture pose"):
        solve_autocal(far, capture_recoater_mm=truth.capture_mm, image_size=SIZE)


def test_solve_refuses_with_too_few_views() -> None:
    views, truth = synth_views(spec=SPEC, shifts_mm=(0.0,))
    with pytest.raises(ValueError, match="views"):
        solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)


def test_extent_and_mm_per_px_are_sane() -> None:
    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    x0, y0, x1, y1 = res.bed_extent_mm
    cap = _capture_view(views, truth.capture_mm)
    pts = _map(res, cap.image_points)
    assert (pts[:, 0] >= x0).all() and (pts[:, 0] <= x1).all()
    assert (pts[:, 1] >= y0).all() and (pts[:, 1] <= y1).all()
    assert bed_raster_error(res.mm_per_px, res.bed_extent_mm) is None
    assert 0.05 <= res.mm_per_px <= 0.2  # ~11.7 px/mm at 120 mm height -> ~0.09 mm/px
    assert len(res.valid_region_mm) >= 3
