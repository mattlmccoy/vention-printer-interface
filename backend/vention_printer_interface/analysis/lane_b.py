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


def largest_contour(image: np.ndarray) -> np.ndarray | None:
    """Extract the largest external contour from a grayscale/BGR image as (N, 2) pixel points.
    Otsu-thresholds the foreground (the printed part / CAD fill) and returns None when nothing is
    found — never a false empty shape."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    gray = gray.astype(np.uint8)
    _thr, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # If the fill is dark-on-light (most CAD/binder masks), invert so the part is the foreground.
    if mask.mean() > 127:
        mask = cv2.bitwise_not(mask)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(biggest) <= 0:
        return None
    return biggest.reshape(-1, 2).astype(float)


def analyze_lane_b(
    printed_image: np.ndarray,
    cad_image: np.ndarray,
    printed_mm_per_px: float,
    cad_mm_per_px: float,
) -> dict[str, Any]:
    """End-to-end Lane B for one layer: extract the printed part outline (from a registered capture)
    and the CAD-slice outline, put both in millimetres, centroid-align them (translation — so the
    result is the part's shape+size deviation, independent of where it landed on the bed), and
    compute the deviation field. Returns the field plus the printed contour in CAPTURE PIXELS
    (``points_px``) so the UI can draw the heatmap over the capture. ``status`` is ``no_contour``
    when either outline can't be found (never a false zero-deviation result)."""
    printed_px = largest_contour(printed_image)
    cad_px = largest_contour(cad_image)
    if printed_px is None or cad_px is None:
        which = "printed capture" if printed_px is None else "CAD slice"
        return {"status": "no_contour", "message": f"no outline found in the {which}"}

    printed_mm = printed_px * float(printed_mm_per_px)
    cad_mm = cad_px * float(cad_mm_per_px)
    cad_mm = cad_mm - cad_mm.mean(axis=0) + printed_mm.mean(axis=0)  # centroid-align (translation)
    field = deviation_field(printed_mm, cad_mm)
    return {
        "status": "ok",
        **field.to_dict(),
        "points_px": [[float(x), float(y)] for x, y in printed_px],  # capture-pixel overlay coords
        "mm_per_px": float(printed_mm_per_px),
    }


def analyze_lane_b_from_pngs(
    printed_png: bytes, cad_png: bytes, printed_mm_per_px: float, cad_mm_per_px: float
) -> dict[str, Any]:
    """``analyze_lane_b`` on encoded PNG bytes (registered capture + CAD layer). Decodes both
    to grayscale; returns ``{status: decode_failed}`` if either can't be read."""
    printed = cv2.imdecode(np.frombuffer(printed_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    cad = cv2.imdecode(np.frombuffer(cad_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if printed is None or cad is None:
        return {"status": "decode_failed", "message": "could not decode the capture or CAD image"}
    return analyze_lane_b(printed, cad, printed_mm_per_px, cad_mm_per_px)
