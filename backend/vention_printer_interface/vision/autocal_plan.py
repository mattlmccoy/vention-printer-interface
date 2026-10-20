"""Recoater positions for an automatic calibration sweep (spec 2026-10-20-auto-calibration §5–6).

The science camera rides the recoater, so stepping the recoater slides the placed board across the
photo. Positions are centred on the capture pose and kept inside the operator's safety window
(with the square board on the substrate the blade must stay off the board: 0–523 mm by default).
They are visited in DESCENDING order after one pre-approach move above the first, so every
position is approached from the same side and backlash stays out of the encoder-shift check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SweepPlan:
    poses: list[float]  # descending mm; includes capture_mm
    pre_approach_mm: float  # first move, above poses[0], so poses[0] is also approached downward
    capture_mm: float


def plan_sweep(
    capture_mm: float,
    window_min_mm: float,
    window_max_mm: float,
    step_mm: float = 5.0,
    max_offset_mm: float = 70.0,
    approach_mm: float = 5.0,
) -> SweepPlan:
    """Plan the sweep, or raise ``ValueError`` with a user-facing reason (nothing has moved)."""
    values = (capture_mm, window_min_mm, window_max_mm, step_mm, max_offset_mm, approach_mm)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("sweep settings must be finite numbers")
    if not window_max_mm > window_min_mm:
        raise ValueError(
            f"safety window is empty or inverted ({window_min_mm:g}–{window_max_mm:g} mm)"
        )
    if not window_min_mm <= capture_mm <= window_max_mm:
        raise ValueError(
            f"capture pose {capture_mm:g} mm is outside the safety window "
            f"({window_min_mm:g}–{window_max_mm:g} mm)"
        )
    if step_mm <= 0:
        raise ValueError(f"sweep step must be > 0 mm (got {step_mm:g})")
    n = int(math.floor(max(0.0, max_offset_mm) / step_mm + 1e-9))
    poses = sorted(
        {
            round(capture_mm + k * step_mm, 3)
            for k in range(-n, n + 1)
            if window_min_mm <= capture_mm + k * step_mm <= window_max_mm
        },
        reverse=True,
    )
    pre = round(min(poses[0] + max(0.0, approach_mm), window_max_mm), 3)
    return SweepPlan(poses, pre, capture_mm)
