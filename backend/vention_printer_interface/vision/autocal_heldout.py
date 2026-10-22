"""Leave-one-photo-out accuracy for the automatic calibration.

A fit always looks good on its own points; what matters is where it puts points it never saw.
Each non-capture photo is held out in turn, the calibration refit on the rest, and the held-out
photo's points mapped through it. Truth = the board as it lay at the capture pose (rigid
board->bed fit through the refit's own capture view), moved by -(recoater - capture) along bed X
(the camera moved +Delta, so the board appears at -Delta). Used to compare detection methods on
real sweep photos (2026-10-21 analysis).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from vention_printer_interface.vision.autocal_solve import (
    CAPTURE_POSE_TOL_MM,
    AutocalView,
    solve_autocal,
)
from vention_printer_interface.vision.overlay import fit_board_to_bed
from vention_printer_interface.vision.registration import apply_homography, undistort_points


def heldout_errors(
    views: list[AutocalView], *, capture_recoater_mm: float, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Per held-out photo: ``{"recoater_mm", "rms_mm", "max_mm", "n"}``."""
    cap = min(views, key=lambda v: abs(v.recoater_mm - capture_recoater_mm))
    rows: list[dict[str, Any]] = []
    for v in views:
        if v is cap or abs(v.recoater_mm - capture_recoater_mm) <= CAPTURE_POSE_TOL_MM:
            continue
        res = solve_autocal([u for u in views if u is not v],
                            capture_recoater_mm=capture_recoater_mm, image_size=image_size)
        to_bed = fit_board_to_bed(cap.image_points, cap.object_points, res)
        mapped = apply_homography(res.H, undistort_points(
            np.asarray(v.image_points, float), res.camera_matrix, res.dist_coeffs))
        board_xy = np.asarray(v.object_points, float).reshape(-1, 3)[:, :2]
        truth = to_bed(board_xy) - (v.recoater_mm - cap.recoater_mm) * np.array([1.0, 0.0])
        e = np.linalg.norm(mapped - truth, axis=1)
        rows.append({"recoater_mm": float(v.recoater_mm), "rms_mm": float(np.sqrt((e ** 2).mean())),
                     "max_mm": float(e.max()), "n": int(len(e))})
    return rows
