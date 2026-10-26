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


def test_a_large_scale_disagreement_fails_instead_of_being_corrected() -> None:
    # Board vs recoater 2% apart is not an engraving tolerance: refuse, never absorb it.
    from vention_printer_interface.vision.autocal_solve import judge

    views, truth = synth_views(spec=SPEC, encoder_scale=1.02)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert res.scale_ratio == pytest.approx(1 / 1.02, abs=0.002)
    passed, reasons = judge(res)
    assert not passed and any("scale" in r and "calipers" in r for r in reasons)


def test_a_small_board_scale_error_is_corrected_to_the_recoater_encoder() -> None:
    # 2026-10-26 real run: encoder said the board's mm were 0.20% off (1.0020) and the certified
    # chessboard said 0.27%: the engraved ChArUco board is ~0.2% small. The calibration must give
    # TRUE (encoder) mm, and the shift check must not count the board's scale as a misfit.
    from vention_printer_interface.vision.autocal_solve import judge

    views, truth = synth_views(spec=SPEC, with_markers=True, board_scale=0.998)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert res.scale_ratio == pytest.approx(1 / 0.998, abs=0.0005)
    cap = _capture_view(views, truth.capture_mm)
    err = np.abs(_map(res, cap.image_points) - truth.bed_xy(cap.object_points)).max()
    assert err < 0.02  # uncorrected: up to 0.2% x ~45 mm = 0.09 mm
    assert res.shift_rms_mm < 0.03
    assert judge(res)[0]


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


# ---- verdict + saved calibration ------------------------------------------------------------
def test_judge_passes_a_good_synthetic_run() -> None:
    from vention_printer_interface.vision.autocal_solve import judge

    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert judge(res) == (True, [])


def test_judge_names_each_failed_limit() -> None:
    import dataclasses

    from vention_printer_interface.vision.autocal_solve import judge

    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    bad = dataclasses.replace(res, n_views=3, reprojection_rms_px=0.9, px_mm=0.1,
                              shift_rms_mm=0.3)
    passed, reasons = judge(bad)
    assert passed is False and len(reasons) == 3
    text = " ".join(reasons)
    for value, limit in (("3", "5"), ("0.09 mm", "0.05 mm"), ("0.3", "0.1")):
        assert value in text and limit in text


def test_lens_fit_is_judged_in_mm_on_the_bed_not_pixels() -> None:
    # 2026-10-21 real run: 5120x3840 photos, 1.40 px lens fit at ~0.0258 mm/px = 0.036 mm, all mm
    # checks passing, yet it failed the old 0.5 px limit (0.013 mm at that resolution).
    import dataclasses

    from vention_printer_interface.vision.autocal_solve import MAX_REPROJ_MM, judge

    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert MAX_REPROJ_MM == 0.05
    ok = dataclasses.replace(res, reprojection_rms_px=1.40, px_mm=0.0258)
    assert judge(ok) == (True, [])
    assert ok.reprojection_rms_mm == pytest.approx(0.0361, abs=1e-4)
    bad = dataclasses.replace(res, reprojection_rms_px=2.5, px_mm=0.0258)
    passed, reasons = judge(bad)
    assert not passed and "0.065 mm" in reasons[0] and "2.5 px" in reasons[0]


def test_solve_reports_the_true_mm_per_pixel() -> None:
    # synthetic camera: f = 1400 px at 120 mm -> 0.0857 mm/px at the centre
    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert res.px_mm == pytest.approx(120.0 / 1400.0, rel=0.02)


def test_residuals_are_broken_down_by_point_type_and_image_region() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    r = res.residuals
    total = sum(len(v.image_points) for v in views)
    assert r["corner"]["n"] + r["marker"]["n"] == total
    assert r["centre"]["n"] + r["middle"]["n"] + r["edge"]["n"] == total
    assert r["marker"]["n"] > 0 and r["marker"]["rms_px"] < 0.2


def test_to_calibration_carries_the_mapping_and_provenance() -> None:
    from vention_printer_interface.vision.autocal_solve import to_calibration

    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    prov = {"method": "auto-sweep", "placement": "substrate", "board_thickness_mm": 3.175}
    cal = to_calibration(res, version="cal-test", provenance=prov)
    assert cal.version == "cal-test" and cal.image_size == SIZE
    assert np.array_equal(cal.H, res.H) and cal.mm_per_px == res.mm_per_px
    assert cal.bed_extent_mm == res.bed_extent_mm
    assert cal.provenance == prov


# ---- marker corners (2026-10-21): use the whole board, not just its 9 interior corners -------
def _region_span(res, axis: int) -> float:  # type: ignore[no-untyped-def]
    pts = np.asarray(res.valid_region_mm, float)
    return float(pts[:, axis].max() - pts[:, axis].min())


def test_marker_points_widen_the_calibrated_area() -> None:
    plain, t1 = synth_views(spec=SPEC)
    full, t2 = synth_views(spec=SPEC, with_markers=True)
    r1 = solve_autocal(plain, capture_recoater_mm=t1.capture_mm, image_size=SIZE)
    r2 = solve_autocal(full, capture_recoater_mm=t2.capture_mm, image_size=SIZE)
    assert _region_span(r1, 1) == pytest.approx(32.0, abs=1.0)  # chessboard corners: 16–48 mm
    assert _region_span(r2, 1) >= 55.0  # marker corners reach 2–62 mm across the recoater


def test_marker_points_keep_mapping_accuracy() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    errs = []
    for v in views:
        expected = truth.bed_xy(v.object_points) - np.array([v.recoater_mm - truth.capture_mm, 0])
        errs.append(_map(res, v.image_points) - expected)
    e = np.vstack(errs)
    assert float(np.sqrt((e ** 2).sum(axis=1).mean())) <= 0.02


def test_noisier_marker_corners_still_map_within_30_microns() -> None:
    # Pessimistic 3x marker-corner noise (0.15 px): well inside the 0.1 mm encoder-check limit.
    views, truth = synth_views(spec=SPEC, with_markers=True, marker_noise_px=0.15)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    e = np.vstack([
        _map(res, v.image_points)
        - (truth.bed_xy(v.object_points) - np.array([v.recoater_mm - truth.capture_mm, 0]))
        for v in views])
    assert float(np.sqrt((e ** 2).sum(axis=1).mean())) <= 0.03


def test_point_residuals_match_the_fit() -> None:
    # Per-point lens-fit residual arrows (projected - detected, px), one array per usable view, for
    # the run report's direction-and-magnitude map. Their RMS IS the reported lens fit.
    views, truth = synth_views(spec=SPEC, with_markers=True)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert len(res.point_residuals) == len(views)
    for r, v in zip(res.point_residuals, views, strict=True):
        assert r.shape == (len(v.image_points), 2)
    allr = np.vstack(res.point_residuals)
    assert float(np.sqrt((np.linalg.norm(allr, axis=1) ** 2).mean())) == pytest.approx(
        res.reprojection_rms_px, rel=1e-3)


# ---- several board placements (2026-10-26: the board only ever covered a band of the frame, so
# the lens model was extrapolated over the rest) -------------------------------------------------
# A lens the constrained fit cannot represent exactly (k3 != 0, optical centre 70/50 px off) seen
# from 200 mm: the board covers ~41% of the frame height, like the real board's ~47% of the width.
# One placement then leaves ~29 um at the far region (real photo, 2026-10-26: 31 um in-band).
REAL_LIKE = {"dist": (-0.25, 0.08, 0.0, 0.0, 0.25), "pp": (1030.0, 590.0), "height_mm": 200.0}


def _grid_residual_mm(res, view) -> float:  # type: ignore[no-untyped-def]
    """How far one photo's points sit from a perfect board grid after the calibration (rotation,
    translation and one scale removed): the lens error left at those image positions."""
    from vention_printer_interface.vision.validation_view import similarity_residuals

    bed = _map(res, view.image_points)
    r = similarity_residuals(bed, np.asarray(view.object_points, float)[:, :2])
    return float(np.sqrt((np.linalg.norm(r, axis=1) ** 2).mean()))


def test_a_second_placement_calibrates_the_part_of_the_frame_the_first_never_saw() -> None:
    a, truth = synth_views(spec=SPEC, with_markers=True, **REAL_LIKE)  # type: ignore[arg-type]
    b, _ = synth_views(spec=SPEC, with_markers=True, board_offset_mm=(0.0, 50.0),
                       board_rotation_deg=4.0, placement=1, seed=3, **REAL_LIKE)  # type: ignore[arg-type]
    b_cap = _capture_view(b, truth.capture_mm)  # B's board sits where A never reached
    one = solve_autocal(a, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    both = solve_autocal(a + b, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert _grid_residual_mm(one, b_cap) > 0.02  # the fixture really extrapolates badly
    assert _grid_residual_mm(both, b_cap) < 0.5 * _grid_residual_mm(one, b_cap)
    span = lambda r: np.ptp(np.asarray(r.valid_region_mm), axis=0)  # noqa: E731
    assert span(both)[1] > span(one)[1] + 20  # the calibrated area grows across the frame
    assert both.shift_rms_mm < 0.05 and abs(both.scale_ratio - 1.0) < 0.002


def test_the_bed_frame_stays_on_the_first_placement() -> None:
    a, truth = synth_views(spec=SPEC, with_markers=True)
    b, _ = synth_views(spec=SPEC, with_markers=True, board_offset_mm=(0.0, 30.0), placement=1)
    one = solve_autocal(a, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    both = solve_autocal(a + b, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = _capture_view(a, truth.capture_mm)
    assert np.abs(_map(both, cap.image_points) - _map(one, cap.image_points)).max() < 0.02


def test_a_placement_with_one_photo_is_refused() -> None:
    a, truth = synth_views(spec=SPEC)
    b, _ = synth_views(spec=SPEC, board_offset_mm=(0.0, 30.0), placement=1, shifts_mm=(0.0,))
    with pytest.raises(ValueError, match="placement 2"):
        solve_autocal(a + b, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
