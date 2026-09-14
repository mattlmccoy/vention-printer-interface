"""Structured geometric-compensation extraction (Lane A, v1 report-only).

Turns the vendored analyzers' metric dicts into a small, typed ``Compensation``:
per-axis scale factors, a yaw angle, and a human-readable recommendation. The scale
math mirrors the RFAM tool (``recommend_compensation_for_dot``): a printed feature that
measures ``err_pct`` larger/smaller than nominal is brought back by a multiplicative
factor ``1/(1 + err_pct/100)``, with a small deadband so measurement noise does not
produce spurious corrections. Yaw comes from the checkerboard angle only (dot rotation
is a diagnostic, not a compensation source — see the tool's own note).

This module computes numbers only. It never writes them anywhere (no print_settings,
no RIP config): v1 is report-only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_DEADBAND_PCT = 0.05  # 0.05% -> 1 part in 2000 (matches the vendored tool)


@dataclass(frozen=True)
class Compensation:
    """A structured, report-only compensation recommendation.

    Attributes
    ----------
    scale_x, scale_y : float
        Multiplicative scale to apply upstream (CAD/slicer/RIP) to bring printed size
        back to nominal. ``1.0`` means "no correction" (no data, or inside the deadband).
    yaw_deg : Optional[float]
        Checkerboard-derived rotation error in degrees, or ``None`` when no usable
        checkerboard measurement exists. Positive follows the tool's angle-error sign.
    human : str
        Human-readable recommendation lines for the operator (never empty).
    notes : list[str]
        Extra diagnostics (missing inputs, deadband hits) for honest UI states.
    deadband_pct : float
        The deadband used, in percent.
    """

    scale_x: float
    scale_y: float
    yaw_deg: Optional[float]
    human: str
    notes: list[str] = field(default_factory=list)
    deadband_pct: float = DEFAULT_DEADBAND_PCT


def _finite(x: Any) -> bool:
    """True only for a real, finite number (rejects None, NaN, inf, non-numbers)."""
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _scale_from_error(err_pct: Any, deadband_pct: float) -> tuple[float, bool]:
    """Scale factor for one axis. Returns (scale, was_deadbanded_or_missing).

    Inside the deadband (or with no/NaN data) the scale is exactly 1.0.
    """
    if not _finite(err_pct):
        return 1.0, True
    e = float(err_pct)
    if abs(e) < deadband_pct:
        return 1.0, True
    return 1.0 / (1.0 + e / 100.0), False


def _yaw_from_checkerboard(checkerboard: Optional[dict[str, Any]]) -> Optional[float]:
    """Yaw error in degrees from the checkerboard, or None when unavailable.

    Prefers the wrapped ``checkerboard_angle_error_deg`` (the small nozzle/stage sliver),
    falling back to the raw ``angle_deg``. A failed detection (found == 0) or non-finite
    angle yields None.
    """
    if not checkerboard:
        return None
    found = checkerboard.get("found")
    if found is not None and not bool(found):
        return None
    for key in ("checkerboard_angle_error_deg", "angle_deg"):
        val = checkerboard.get(key)
        if _finite(val):
            return float(val)
    return None


def _human_lines(
    scale_x: float,
    scale_y: float,
    yaw_deg: Optional[float],
    deadband_pct: float,
) -> tuple[str, list[str]]:
    """Build the operator-facing recommendation text + diagnostic notes."""
    lines: list[str] = []
    notes: list[str] = []

    def _axis_line(axis: str, scale: float) -> None:
        if scale == 1.0:
            notes.append(
                f"{axis}: spacing within the {deadband_pct:.2f}% deadband — no scale correction."
            )
            return
        err_pct = (1.0 / scale - 1.0) * 100.0  # invert the scale to recover the error
        sense = "larger" if err_pct > 0 else "smaller"
        verb = "shrink" if err_pct > 0 else "enlarge"
        lines.append(
            f"Printed spacing in {axis} is {err_pct:+.3f}% {sense} than nominal. "
            f"Apply a scale factor of {scale:.4f} in {axis} "
            f"(i.e. {verb} geometry to {scale * 100:.2f}% of its current size)."
        )

    _axis_line("X", scale_x)
    _axis_line("Y", scale_y)

    if yaw_deg is None:
        notes.append("Yaw: no checkerboard measurement available.")
    elif abs(yaw_deg) < deadband_pct:
        notes.append(f"Yaw: {yaw_deg:+.3f}° within deadband — no rotation correction.")
    else:
        direction = "clockwise" if yaw_deg > 0 else "counter-clockwise"
        lines.append(
            f"Yaw (printhead/stage rotation): adjust {direction} by about "
            f"{abs(yaw_deg):.3f}° (checkerboard angle error)."
        )

    if not lines:
        lines.append(
            "No geometric compensation needed: all measured errors are within the "
            f"{deadband_pct:.2f}% deadband."
        )
    lines.append("Apply upstream in your CAD/slicer or RIP config — v1 does not auto-apply.")

    return "\n".join(lines), notes


def to_compensation(
    dot: Optional[dict[str, Any]] = None,
    checkerboard: Optional[dict[str, Any]] = None,
    *,
    deadband_pct: float = DEFAULT_DEADBAND_PCT,
) -> Compensation:
    """Derive a structured, report-only :class:`Compensation` from analyzer metrics.

    Parameters
    ----------
    dot : dict, optional
        A dot-array summary (needs ``spacing_x_error_pct`` / ``spacing_y_error_pct``).
    checkerboard : dict, optional
        A checkerboard summary (yaw from ``checkerboard_angle_error_deg`` / ``angle_deg``).
    deadband_pct : float, keyword-only
        Errors with magnitude below this (percent) are treated as noise -> scale 1.0.
    """
    dot = dot or {}
    scale_x, _dbx = _scale_from_error(dot.get("spacing_x_error_pct"), deadband_pct)
    scale_y, _dby = _scale_from_error(dot.get("spacing_y_error_pct"), deadband_pct)
    yaw_deg = _yaw_from_checkerboard(checkerboard)

    human, notes = _human_lines(scale_x, scale_y, yaw_deg, deadband_pct)

    return Compensation(
        scale_x=scale_x,
        scale_y=scale_y,
        yaw_deg=yaw_deg,
        human=human,
        notes=notes,
        deadband_pct=deadband_pct,
    )
