"""World-space scale validation (pure, hardware-free).

Independent trust check for the science-cam calibration: a chessboard of KNOWN square size is
imaged and its corners mapped to world-mm through the CURRENT calibration (undistort + bed
homography — done in the API adapter). Here we compare the measured adjacent-corner spacings to the
known square size and report the error in mm. Because it uses a *different* board than the one the
calibration was fit on, and reports real millimetres, it is a genuine independent check. No IO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleResult:
    mean: float
    max: float
    rms: float
    residuals_mm: list[float]

    def passed(self, target_mm: float) -> bool:
        return self.max <= target_mm


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def scale_residuals(
    world_pts_mm: list[tuple[float, float]],
    board_dims: tuple[int, int],
    square_mm: float,
) -> ScaleResult:
    """Adjacent-corner spacing error (mm) for an ``nx x ny`` grid of world-mm corners laid out
    row-major (``pts[j*nx + i]``). Measures every horizontal + vertical neighbour gap and returns
    the absolute residual (measured vs known) stats. Passing means the WORST gap is in tolerance."""
    nx, ny = board_dims
    resid: list[float] = []
    for j in range(ny):
        for i in range(nx):
            p = world_pts_mm[j * nx + i]
            if i + 1 < nx:  # horizontal neighbour
                resid.append(abs(_dist(p, world_pts_mm[j * nx + i + 1]) - square_mm))
            if j + 1 < ny:  # vertical neighbour
                resid.append(abs(_dist(p, world_pts_mm[(j + 1) * nx + i]) - square_mm))
    if not resid:
        return ScaleResult(mean=0.0, max=0.0, rms=0.0, residuals_mm=[])
    mean = sum(resid) / len(resid)
    rms = math.sqrt(sum(r * r for r in resid) / len(resid))
    return ScaleResult(mean=mean, max=max(resid), rms=rms, residuals_mm=resid)
