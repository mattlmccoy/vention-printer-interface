"""Per-run choice of which detected points the automatic calibration is fitted on.

Three methods, each scored by leave-one-photo-out error on the SAME held-out points (every point
identified in the held-out photo), and the run keeps the lowest ("best on held-out photos"):

* ``all`` - every chessboard corner and marker corner;
* ``drop_outliers`` - the same, minus points the all-points lens fit misses by more than 3 px;
* ``chessboard`` - chessboard corners only (sub-pixel saddle points; markers only define ids).

Real 2026-10-26 sweep (14 photos, 5120x3840), every method scored on all points: all 32.8 um mean /
98 um worst held-out, 3 px outliers dropped (8 points) 32.8 / 100 um, chessboard-only 84.8 / 716 um
(it extrapolates to the frame edges from 76 points). Scored on its OWN points chessboard-only read
28.4 / 62 um, which is why the scoring set is fixed across methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vention_printer_interface.vision.autocal_heldout import heldout_scores
from vention_printer_interface.vision.autocal_solve import (
    MIN_CORNERS,
    AutocalResult,
    AutocalView,
    judge,
    solve_autocal,
)
from vention_printer_interface.vision.charuco_points import MARKER_ID_BASE

__all__ = ["METHODS", "OUTLIER_PX", "BestSolve", "MIN_GAIN_MM", "heldout_scores", "method_views",
           "pick_method", "solve_best"]

METHODS: tuple[tuple[str, str], ...] = (
    ("all", "every identified point"),
    ("drop_outliers", "every point except lens-fit misses over 3 px"),
    ("chessboard", "chessboard corners only"),
)
OUTLIER_PX = 3.0
# A later method must lower the mean held-out error by at least this to replace an earlier one:
# smaller gains are noise (real 2026-10-26 sweep: per-photo held-out SD 3.1 um; drop_outliers beat
# all by 0.05 um).
MIN_GAIN_MM = 0.001


@dataclass(frozen=True)
class BestSolve:
    result: AutocalResult
    method: str
    # The photos the chosen result was fitted on (>= MIN_CORNERS points each), in the order of
    # ``result.point_residuals``.
    views: list[AutocalView]
    methods: list[dict[str, Any]] = field(default_factory=list)


def _subset(v: AutocalView, keep: np.ndarray) -> AutocalView:
    return AutocalView(v.recoater_mm, np.asarray(v.image_points, float)[keep],
                       np.asarray(v.object_points, float)[keep], np.asarray(v.ids)[keep],
                       placement=v.placement)


def _n(v: AutocalView) -> int:
    return len(np.asarray(v.image_points).reshape(-1, 2))


def method_views(
    views: list[AutocalView], method: str, residuals: list[np.ndarray] | None = None,
) -> list[AutocalView]:
    """The points ``method`` fits on, one entry per photo (index-aligned with ``views``).
    ``drop_outliers`` needs the all-points fit's ``point_residuals`` for these same views."""
    if method == "all":
        return list(views)
    if method == "chessboard":
        return [_subset(v, np.asarray(v.ids).ravel() < MARKER_ID_BASE) for v in views]
    if method == "drop_outliers":
        if residuals is None or len(residuals) != len(views):
            raise ValueError("drop_outliers needs the all-points residuals for every photo")
        return [_subset(v, np.linalg.norm(np.asarray(r).reshape(-1, 2), axis=1) <= OUTLIER_PX)
                for v, r in zip(views, residuals, strict=True)]
    raise ValueError(f"unknown point method {method!r}")


def solve_best(
    views: list[AutocalView], *, capture_recoater_mm: float, image_size: tuple[int, int],
) -> BestSolve:
    """Solve with every method and keep the lowest mean held-out error among those that pass
    ``judge`` (or, when none passes, among those that solved). Raises ``ValueError`` when even the
    all-points solve fails, with the solver's own reason."""
    usable = [v for v in views if _n(v) >= MIN_CORNERS]
    base = solve_autocal(usable, capture_recoater_mm=capture_recoater_mm, image_size=image_size)
    rows: list[dict[str, Any]] = []
    solved: dict[str, tuple[AutocalResult, list[AutocalView]]] = {}
    for key, label in METHODS:
        train = method_views(usable, key, base.point_residuals)
        fitted = [v for v in train if _n(v) >= MIN_CORNERS]
        row: dict[str, Any] = {"method": key, "label": label, "n_photos": len(fitted),
                               "n_points": sum(_n(v) for v in fitted), "chosen": False}
        try:
            res = base if key == "all" else solve_autocal(
                fitted, capture_recoater_mm=capture_recoater_mm, image_size=image_size)
            held = heldout_scores(train, usable, capture_recoater_mm=capture_recoater_mm,
                                  image_size=image_size)
        except ValueError as exc:
            rows.append({**row, "error": str(exc), "passed": False})
            continue
        rms = np.array([h["rms_mm"] for h in held])
        row.update({
            "passed": judge(res)[0], "lens_mm": res.reprojection_rms_mm,
            "shift_rms_mm": res.shift_rms_mm, "n_heldout": len(held),
            "heldout_mean_mm": float(rms.mean()) if len(rms) else None,
            "heldout_worst_mm": max((h["max_mm"] for h in held), default=None),
        })
        rows.append(row)
        solved[key] = (res, fitted)
    chosen = pick_method(rows)
    for r in rows:
        r["chosen"] = r["method"] == chosen
    res, fitted = solved[chosen]
    return BestSolve(result=res, method=chosen, views=fitted, methods=rows)


def pick_method(rows: list[dict[str, Any]]) -> str:
    """The method to keep: lowest ``heldout_mean_mm`` among rows that passed, else among rows
    that solved (no ``error``). A later method must beat the current pick by ``MIN_GAIN_MM``;
    rows without held-out photos keep the earlier method (``all`` first). Rows must include at
    least one that solved."""
    solved = [r for r in rows if not r.get("error")]
    pool = [r for r in solved if r["passed"]] or solved
    scored = [r for r in pool if r["heldout_mean_mm"] is not None]
    if not scored:
        return str(pool[0]["method"])
    pick = scored[0]
    for r in scored[1:]:
        if r["heldout_mean_mm"] < pick["heldout_mean_mm"] - MIN_GAIN_MM:
            pick = r
    return str(pick["method"])
