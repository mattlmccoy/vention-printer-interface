"""Camera-center-sweep pose selection (pure, hardware-free).

The science cam rides the recoater gantry. To be overhead the build piston, sweep the recoater
over a tight range, at each pose measure the piston-center offset (px), and pick the
pose that minimizes it. This core just selects the best pose from the measured samples (with a
3-point parabola refine below the step size); the motion + circle detection live in the API. No IO.
"""

from __future__ import annotations

from dataclasses import dataclass

_EPS = 1e-6


@dataclass(frozen=True)
class CenterResult:
    pose_mm: float
    offset_px: float
    improved: bool


def best_center_pose(
    samples: list[tuple[float, float]],
    start_pose_mm: float,
) -> CenterResult:
    """``samples`` = [(recoater_mm, offset_px)]. Returns the offset-minimizing pose. When the min
    sample has both neighbours, refine the pose with a parabola vertex (sub-step). ``improved`` is
    True only if the best offset beats the offset at the pose nearest ``start_pose_mm``."""
    if not samples:
        return CenterResult(pose_mm=start_pose_mm, offset_px=float("inf"), improved=False)
    ordered = sorted(samples, key=lambda s: s[0])
    k = min(range(len(ordered)), key=lambda i: ordered[i][1])
    pose, offset = ordered[k]
    if 0 < k < len(ordered) - 1:
        x0, y0 = ordered[k - 1]
        x1, y1 = ordered[k]
        x2, y2 = ordered[k + 1]
        denom = y0 - 2 * y1 + y2
        if abs(denom) > _EPS and x2 != x0:  # concave-up parabola: refine the vertex
            h = (x2 - x0) / 2.0
            pose = x1 + 0.5 * h * (y0 - y2) / denom
    nearest = min(ordered, key=lambda s: abs(s[0] - start_pose_mm))
    improved = offset < nearest[1] - _EPS
    return CenterResult(pose_mm=pose, offset_px=offset, improved=improved)
