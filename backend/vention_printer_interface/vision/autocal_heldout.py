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
    MIN_CORNERS,
    AutocalView,
    solve_autocal,
)
from vention_printer_interface.vision.overlay import fit_board_to_bed
from vention_printer_interface.vision.registration import apply_homography, undistort_points


def heldout_errors(
    views: list[AutocalView], *, capture_recoater_mm: float, image_size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Per held-out photo: ``{"recoater_mm", "placement", "rms_mm", "max_mm", "n"}``, trained
    and scored on the same points (see ``heldout_scores``)."""
    return heldout_scores(views, views, capture_recoater_mm=capture_recoater_mm,
                          image_size=image_size)


def heldout_scores(
    train: list[AutocalView], score: list[AutocalView], *, capture_recoater_mm: float,
    image_size: tuple[int, int],
) -> list[dict[str, Any]]:
    """Leave-one-photo-out error of a calibration fitted on ``train``, measured on ``score``.

    ``train`` and ``score`` are the same photos in the same order; ``train`` may hold fewer points
    per photo (a point-selection method), ``score`` holds the points every method is judged on, so
    methods are compared on equal terms. A photo with too few points to train on is still scored.

    Each placement is judged against its OWN board pose (its photo nearest the capture pose):
    the board was moved between placements, so another placement's pose is not its truth. A
    placement's reference photo is never held out."""
    if len(train) != len(score):
        raise ValueError("train and score must list the same photos")

    def n_pts(v: AutocalView) -> int:
        return len(np.asarray(v.image_points).reshape(-1, 2))

    groups: dict[int, list[int]] = {}
    for i, v in enumerate(score):
        if n_pts(v) >= MIN_CORNERS:
            groups.setdefault(int(v.placement), []).append(i)
    refs = {p: min(ix, key=lambda i: abs(score[i].recoater_mm - capture_recoater_mm))
            for p, ix in groups.items()}
    rows: list[dict[str, Any]] = []
    for p, ix in groups.items():
        ref = score[refs[p]]
        for i in ix:
            v = score[i]
            if i == refs[p] or abs(v.recoater_mm - ref.recoater_mm) <= CAPTURE_POSE_TOL_MM:
                continue
            res = solve_autocal([u for j, u in enumerate(train) if j != i],
                                capture_recoater_mm=capture_recoater_mm, image_size=image_size)
            to_bed = fit_board_to_bed(ref.image_points, ref.object_points, res)
            mapped = apply_homography(res.H, undistort_points(
                np.asarray(v.image_points, float), res.camera_matrix, res.dist_coeffs))
            board_xy = np.asarray(v.object_points, float).reshape(-1, 3)[:, :2]
            truth = to_bed(board_xy) - (v.recoater_mm - ref.recoater_mm) * np.array([1.0, 0.0])
            e = np.linalg.norm(mapped - truth, axis=1)
            rows.append({"recoater_mm": float(v.recoater_mm), "placement": p,
                         "rms_mm": float(np.sqrt((e ** 2).mean())), "max_mm": float(e.max()),
                         "n": int(len(e))})
    return rows
