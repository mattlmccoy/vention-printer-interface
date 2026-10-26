"""ChArUco self-check: score a PENDING calibration on photos of the board after it has been moved.

After the sweep's solve passes, the operator moves or rotates the board and takes one or more
photos. Every identified point (chessboard and marker corners, vision/charuco_points.py) is mapped
through the pending calibration, and the distance between every pair of points in a photo is
compared with their true distance on the board. Pairwise distances do not depend on where the
board now sits, so its new pose never has to be known. Only points inside the calibrated area
count; the report says how many were used and how many were outside.

This is reused-board evidence: it gates Save but never clears ``calibration_validation_warning``
(only the certified chessboard does). Thresholds are first guesses, to tune after the first run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from vention_printer_interface.vision.charuco_points import BoardPoints

SELF_RMS_MM = 0.1
SELF_WORST_MM = 0.2
# Chessboard corners only since 2026-10-26 (a 4x4 board has 9 per photo); was 12 with marker
# corners. 6 X-corners give 15 independent pair distances.
SELF_MIN_POINTS = 6
# A self-check photo whose every point is within this of a sweep photo's points is the same pose.
UNMOVED_PX = 2.0


@dataclass(frozen=True)
class SelfCheck:
    rms_mm: float
    worst_mm: float
    scale_bias: float  # sum of mapped pair distances / sum of true pair distances
    n_used: int
    n_outside: int
    moved: bool
    passed: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "rms_mm": self.rms_mm, "worst_mm": self.worst_mm, "scale_bias": self.scale_bias,
            "n_used": self.n_used, "n_outside": self.n_outside, "moved": self.moved,
            "passed": self.passed, "reasons": list(self.reasons),
        }


def _inside(pts: np.ndarray, region: Sequence[tuple[float, float]]) -> np.ndarray:
    import cv2

    poly = np.asarray(region, np.float32).reshape(-1, 1, 2)
    return np.array([cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0
                     for x, y in pts], bool)


def _same_pose(pts: np.ndarray, sweep: Sequence[np.ndarray]) -> bool:
    for ref in sweep:
        ref = np.asarray(ref, float).reshape(-1, 2)
        if len(ref) == 0 or len(pts) == 0:
            continue
        d = np.linalg.norm(pts[:, None, :] - ref[None, :, :], axis=2).min(axis=1)
        if float(d.max()) <= UNMOVED_PX:
            return True
    return False


def score_self_check(
    views: list[BoardPoints],
    to_bed: Callable[[np.ndarray], np.ndarray],
    region_mm: Sequence[tuple[float, float]] | None,
    sweep_poses_px: Sequence[np.ndarray] = (),
) -> SelfCheck:
    """Score ``views`` through ``to_bed`` (image px -> bed mm: undistort + H).

    ``region_mm`` is the calibrated area (bed mm polygon); ``None`` (an older calibration) counts
    every point. ``sweep_poses_px`` are the sweep photos' points: when every view matches one of
    them the board was not moved, which is reported (the score still stands). With no sweep photos
    to compare against, ``moved`` is True.
    """
    errs: list[np.ndarray] = []
    sum_mapped = sum_true = 0.0
    n_used = n_outside = 0
    unmoved = bool(views) and bool(sweep_poses_px)
    for v in views:
        px = np.asarray(v.image_points, float).reshape(-1, 2)
        obj = np.asarray(v.object_points, float).reshape(-1, 3)[:, :2]
        if unmoved and not _same_pose(px, sweep_poses_px):
            unmoved = False
        if len(px) == 0:
            continue
        bed = np.asarray(to_bed(px), float).reshape(-1, 2)
        keep = _inside(bed, region_mm) if region_mm else np.ones(len(bed), bool)
        n_used += int(keep.sum())
        n_outside += int((~keep).sum())
        bed, obj = bed[keep], obj[keep]
        if len(bed) < 2:
            continue
        i, j = np.triu_indices(len(bed), k=1)
        mapped = np.linalg.norm(bed[i] - bed[j], axis=1)
        true = np.linalg.norm(obj[i] - obj[j], axis=1)
        errs.append(mapped - true)
        sum_mapped += float(mapped.sum())
        sum_true += float(true.sum())

    e = np.concatenate(errs) if errs else np.zeros(0)
    rms = float(np.sqrt((e ** 2).mean())) if len(e) else float("nan")
    worst = float(np.abs(e).max()) if len(e) else float("nan")
    bias = sum_mapped / sum_true if sum_true > 0 else float("nan")
    reasons: list[str] = []
    if n_used < SELF_MIN_POINTS:
        reasons.append(f"only {n_used} board points inside the calibrated area "
                       f"(need {SELF_MIN_POINTS}) — move the board into the calibrated area")
    else:
        if not rms <= SELF_RMS_MM:
            reasons.append(f"distance RMS {rms:.3f} mm > {SELF_RMS_MM} mm "
                           f"(scale bias {bias:.4f})")
        if not worst <= SELF_WORST_MM:
            reasons.append(f"worst distance error {worst:.3f} mm > {SELF_WORST_MM} mm")
    if unmoved:
        reasons.append("the board did not move since the sweep — move or rotate it and retake; "
                       "a self-check on the sweep pose only re-scores the fit")
    passed = n_used >= SELF_MIN_POINTS and rms <= SELF_RMS_MM and worst <= SELF_WORST_MM
    return SelfCheck(rms_mm=rms, worst_mm=worst, scale_bias=bias, n_used=n_used,
                     n_outside=n_outside, moved=not unmoved, passed=passed, reasons=reasons)
