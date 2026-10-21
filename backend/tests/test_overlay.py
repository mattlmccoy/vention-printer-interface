"""Overlays drawn on the calibration photo (vision/overlay.py), checked against synthetic truth.

The raw overlay projects bed-mm points back INTO the distorted photo (inverse homography, then the
lens model forward). Correct when the board's own corners, at their solved bed positions, land back
on the pixels where they were detected.
"""

from __future__ import annotations

import numpy as np

from tests.autocal_synth import synth_views
from vention_printer_interface.vision.autocal_solve import solve_autocal
from vention_printer_interface.vision.board_gen import resolve_preset
from vention_printer_interface.vision.overlay import MAX_OVERLAY_PX, bed_to_raw_px, fit_width
from vention_printer_interface.vision.registration import apply_homography, undistort_points

SPEC = resolve_preset("small_cylinder")
SIZE = (1920, 1080)


def test_bed_points_project_back_onto_the_detected_pixels() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = min(views, key=lambda v: abs(v.recoater_mm - truth.capture_mm))
    bed = apply_homography(res.H, undistort_points(cap.image_points, res.camera_matrix,
                                                   res.dist_coeffs))
    back = bed_to_raw_px(bed, res.camera_matrix, res.dist_coeffs, res.H)
    assert float(np.abs(back - cap.image_points).max()) < 0.5


def test_overlays_are_scaled_down_for_display_only_when_wide() -> None:
    assert fit_width((900, 700)) == (900, 700)
    w, h = fit_width((5120, 3840))
    assert w == MAX_OVERLAY_PX and h == round(3840 * MAX_OVERLAY_PX / 5120)


def test_board_grid_drawn_from_the_solve_lands_on_the_detected_corners() -> None:
    # The overlay draws the board's own square grid where the solved calibration predicts it; its
    # line crossings must sit on the detected chessboard corners (else the fit is visibly wrong).
    from vention_printer_interface.vision.overlay import board_grid_mm, fit_board_to_bed

    views, truth = synth_views(spec=SPEC)
    res = solve_autocal(views, capture_recoater_mm=truth.capture_mm, image_size=SIZE)
    cap = min(views, key=lambda v: abs(v.recoater_mm - truth.capture_mm))
    to_bed = fit_board_to_bed(cap.image_points, cap.object_points, res)
    lines = board_grid_mm(SPEC.squares_x, SPEC.squares_y, SPEC.square_length_mm, to_bed)
    assert len(lines) == (SPEC.squares_x + 1) + (SPEC.squares_y + 1)
    crossings = to_bed(np.asarray(cap.object_points, float)[:, :2])
    back = bed_to_raw_px(crossings, res.camera_matrix, res.dist_coeffs, res.H)
    assert float(np.abs(back - cap.image_points).max()) < 0.5
