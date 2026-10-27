"""Per-run point-method choice for the automatic calibration (vision/autocal_methods.py).

Three ways to pick the points the calibration is fitted on: every identified point, every point
minus lens-fit outliers (> 3 px), or chessboard corners only. Each is scored by leave-one-photo-out
error on the SAME held-out points (every identified point of the held-out photo), and the run keeps
the lowest. On the real 2026-10-26 sweep, scoring each method on its own points flattered
chessboard-only (fewer, cleaner test points), so the scoring set is fixed across methods.
"""

from __future__ import annotations

import numpy as np

from tests.autocal_synth import synth_views
from vention_printer_interface.vision.autocal_heldout import heldout_errors
from vention_printer_interface.vision.autocal_methods import (
    heldout_scores,
    method_views,
    pick_method,
    solve_best,
)
from vention_printer_interface.vision.autocal_solve import AutocalView, solve_autocal
from vention_printer_interface.vision.board_gen import resolve_preset
from vention_printer_interface.vision.charuco_points import MARKER_ID_BASE

SPEC = resolve_preset("small_cylinder")
SIZE = (1920, 1080)


def _only(v: AutocalView, keep: np.ndarray) -> AutocalView:
    return AutocalView(v.recoater_mm, v.image_points[keep], v.object_points[keep], v.ids[keep],
                       placement=v.placement)


def test_chessboard_method_keeps_only_chessboard_corners() -> None:
    views, _ = synth_views(spec=SPEC, with_markers=True)
    out = method_views(views, "chessboard")
    assert len(out) == len(views)  # index-aligned with the photos
    assert all((np.asarray(v.ids).ravel() < MARKER_ID_BASE).all() for v in out)
    assert sum(len(v.ids) for v in out) < sum(len(v.ids) for v in views)


def test_drop_outliers_removes_points_the_lens_fit_misses_by_more_than_3px() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    bad = views[3]
    pts = bad.image_points.copy()
    pts[5] += (7.0, -5.0)
    views[3] = AutocalView(bad.recoater_mm, pts, bad.object_points, bad.ids)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    out = method_views(views, "drop_outliers", res.point_residuals)
    dropped = sum(len(a.ids) - len(b.ids) for a, b in zip(views, out, strict=True))
    assert int(np.asarray(bad.ids).ravel()[5]) not in np.asarray(out[3].ids).ravel()
    assert 1 <= dropped <= 2


def test_heldout_scores_matches_heldout_errors_when_training_on_every_point() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    a = heldout_scores(views, views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    b = heldout_errors(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert [r["recoater_mm"] for r in a] == [r["recoater_mm"] for r in b]
    assert np.allclose([r["rms_mm"] for r in a], [r["rms_mm"] for r in b], atol=1e-9)


def test_heldout_scores_every_method_on_the_full_points_of_each_photo() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    chess = method_views(views, "chessboard")
    rows = heldout_scores(chess, views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    full = {v.recoater_mm: len(v.ids) for v in views}
    assert rows and all(r["n"] == full[r["recoater_mm"]] for r in rows)


def test_heldout_scores_a_photo_too_sparse_to_train_on_without_crashing() -> None:
    # Real 2026-10-26 sweep: the edge photos hold 0-3 chessboard corners (markers only).
    views, truth = synth_views(spec=SPEC, with_markers=True)
    chess = method_views(views, "chessboard")
    chess[0] = _only(chess[0], np.zeros(len(chess[0].ids), bool))
    rows = heldout_scores(chess, views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert views[0].recoater_mm in {r["recoater_mm"] for r in rows}


def test_solve_best_keeps_the_method_with_the_lowest_heldout_error() -> None:
    # Noisy marker corners: fitting on chessboard corners only must win.
    views, truth = synth_views(spec=SPEC, with_markers=True, marker_noise_px=1.5)
    best = solve_best(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    assert best.method == "chessboard"
    rows = {r["method"]: r for r in best.methods}
    assert set(rows) == {"all", "drop_outliers", "chessboard"}
    assert rows["chessboard"]["chosen"] and not rows["all"]["chosen"]
    assert rows["chessboard"]["heldout_mean_mm"] < rows["all"]["heldout_mean_mm"]
    assert all(len(v.ids) >= 4 for v in best.views)
    assert len(best.result.point_residuals) == len(best.views)


def test_solve_best_records_a_method_that_cannot_solve_and_uses_another() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    cap = min(range(len(views)), key=lambda i: abs(views[i].recoater_mm - truth.capture_mm))
    views[cap] = _only(views[cap], np.asarray(views[cap].ids).ravel() >= MARKER_ID_BASE)
    best = solve_best(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    rows = {r["method"]: r for r in best.methods}
    assert rows["chessboard"]["error"] and best.method != "chessboard"


def _row(method: str, mean: float | None, passed: bool, error: str | None = None) -> dict:
    return {"method": method, "heldout_mean_mm": mean, "passed": passed, "error": error}


def test_pick_method_prefers_a_passing_method_over_a_lower_error_failing_one() -> None:
    # e.g. chessboard-only keeps too few photos to pass (< MIN_VIEWS) yet scores lowest
    rows = [_row("all", 0.040, True), _row("drop_outliers", 0.038, True),
            _row("chessboard", 0.020, False)]
    assert pick_method(rows) == "drop_outliers"


def test_pick_method_takes_the_lowest_error_when_none_passes() -> None:
    rows = [_row("all", 0.09, False), _row("drop_outliers", None, False, "cannot solve"),
            _row("chessboard", 0.07, False)]
    assert pick_method(rows) == "chessboard"


def test_pick_method_keeps_all_points_on_a_tie_or_without_held_out_photos() -> None:
    assert pick_method([_row("all", 0.03, True), _row("chessboard", 0.03, True)]) == "all"
    assert pick_method([_row("all", None, True), _row("chessboard", None, True)]) == "all"


def test_pick_method_needs_a_1um_gain_to_leave_an_earlier_method() -> None:
    # Real 2026-10-26 sweep: drop_outliers beat all by 0.05 um (noise; per-photo SD was 3.1 um).
    rows = [_row("all", 0.03283, True), _row("drop_outliers", 0.03278, True)]
    assert pick_method(rows) == "all"
    rows = [_row("all", 0.03283, True), _row("drop_outliers", 0.03170, True)]
    assert pick_method(rows) == "drop_outliers"
