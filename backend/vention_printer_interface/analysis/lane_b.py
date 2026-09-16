"""Lane B — arbitrary-part CAD-vs-real deviation.

Given a printed layer's outline and its CAD-slice outline (both in bed millimetres), compute a
signed per-point deviation field — the raw material for a deviation heatmap. Sign convention:
POSITIVE deviation = the printed edge sits OUTSIDE the CAD outline (part larger / over-deposited);
NEGATIVE = inside the CAD outline (part smaller / under-deposited). Summary stats (mean|·|, RMS,
max) are in millimetres; area_ratio is printed area ÷ CAD area.

This is the pure, hardware-independent core. Extracting the printed contour from a registered
science capture and the CAD contour from a slice, and rendering the heatmap overlay, are the
integration layer built on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class DeviationField:
    points_mm: list[tuple[float, float]]  # printed contour points, bed mm
    deviations_mm: list[float]            # signed distance to the CAD outline, per point (mm)
    mean_abs_mm: float
    rms_mm: float
    max_abs_mm: float
    max_at_mm: tuple[float, float]        # the printed point of worst |deviation|
    area_ratio: float                     # printed area / CAD area (1.0 = same size)
    n: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "points_mm": self.points_mm,
            "deviations_mm": self.deviations_mm,
            "mean_abs_mm": self.mean_abs_mm,
            "rms_mm": self.rms_mm,
            "max_abs_mm": self.max_abs_mm,
            "max_at_mm": list(self.max_at_mm),
            "area_ratio": self.area_ratio,
            "n": self.n,
        }


def deviation_field(printed_mm: np.ndarray, cad_mm: np.ndarray) -> DeviationField:
    """Signed distance from each printed-contour point to the CAD outline (mm), + summary stats.

    ``printed_mm`` / ``cad_mm`` are (N, 2) arrays of contour points in bed millimetres.
    """
    printed = np.asarray(printed_mm, dtype=np.float32).reshape(-1, 2)
    cad = np.asarray(cad_mm, dtype=np.float32).reshape(-1, 1, 2)
    if len(printed) == 0 or len(cad) < 3:
        return DeviationField([], [], 0.0, 0.0, 0.0, (0.0, 0.0), 0.0, 0)

    # cv2.pointPolygonTest returns +dist when the point is INSIDE the polygon, -dist when OUTSIDE.
    # Flip the sign so POSITIVE = outside the CAD outline (over-deposited / part too big).
    devs = np.array(
        [-cv2.pointPolygonTest(cad, (float(x), float(y)), True) for x, y in printed],
        dtype=float,
    )
    abs_d = np.abs(devs)
    i_max = int(np.argmax(abs_d))
    a_printed = abs(cv2.contourArea(printed.reshape(-1, 1, 2))) if len(printed) >= 3 else 0.0
    a_cad = abs(cv2.contourArea(cad))
    return DeviationField(
        points_mm=[(float(x), float(y)) for x, y in printed],
        deviations_mm=[float(v) for v in devs],
        mean_abs_mm=float(abs_d.mean()),
        rms_mm=float(np.sqrt((devs ** 2).mean())),
        max_abs_mm=float(abs_d[i_max]),
        max_at_mm=(float(printed[i_max][0]), float(printed[i_max][1])),
        area_ratio=float(a_printed / a_cad) if a_cad > 0 else 0.0,
        n=len(printed),
    )
