"""Calibration capture coverage (pure, hardware-free).

A good intrinsics calibration needs the board across the whole frame AND at several tilts. It
turns the accumulated view descriptors into a coverage grid (N×N cells × a few tilt bins) so
the wizard can guide the operator ("need a view top-left / more tilt") and gate finalize until the
capture set is diverse enough. No IO.

A view descriptor is a dict ``{"centroid_px": (cx,cy), "tilt_deg": t, "image_size": (w,h)}``
(the API builds it from a ``BoardDetection``: image-point centroid + the out-of-plane angle).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Out-of-plane tilt bin edges (deg): bin 0 = near fronto-parallel, then increasing tilt.
_TILT_EDGES = (10.0, 25.0)


def _tilt_bin(tilt_deg: float, n_bins: int) -> int:
    for i, edge in enumerate(_TILT_EDGES[: max(1, n_bins) - 1]):
        if tilt_deg < edge:
            return i
    return max(1, n_bins) - 1


@dataclass(frozen=True)
class CoverageState:
    cells_filled: int
    tilt_bins_filled: int
    enough: bool
    gaps: list[str]
    total_views: int


def coverage(
    detections: list[dict[str, Any]],
    grid: tuple[int, int] = (3, 3),
    tilt_bins: int = 3,
    min_views: int = 6,
) -> CoverageState:
    """Summarize capture coverage. ``grid`` is (cols, rows) of frame cells; ``tilt_bins`` is how
    out-of-plane tilt buckets to require. ``enough`` needs every cell hit, tilt diversity, and at
    least ``min_views`` views. ``gaps`` names empty cells ``r{row}c{col}`` (1-indexed) plus
    ``"tilt"`` when the tilt spread is short."""
    gx_count, gy_count = grid
    hits = [[0] * gx_count for _ in range(gy_count)]
    tilts: set[int] = set()
    for d in detections:
        cx, cy = d["centroid_px"]
        w, h = d["image_size"]
        gx = min(gx_count - 1, max(0, int(cx / w * gx_count)))
        gy = min(gy_count - 1, max(0, int(cy / h * gy_count)))
        hits[gy][gx] += 1
        tilts.add(_tilt_bin(float(d["tilt_deg"]), tilt_bins))

    cells_filled = sum(1 for row in hits for c in row if c > 0)
    tilt_bins_filled = len(tilts)
    total = len(detections)
    gaps = [
        f"r{gy + 1}c{gx + 1}"
        for gy in range(gy_count)
        for gx in range(gx_count)
        if hits[gy][gx] == 0
    ]
    want_tilts = min(tilt_bins, 3)
    if tilt_bins_filled < want_tilts:
        gaps.append("tilt")
    enough = (
        cells_filled == gx_count * gy_count
        and tilt_bins_filled >= want_tilts
        and total >= min_views
    )
    return CoverageState(
        cells_filled=cells_filled,
        tilt_bins_filled=tilt_bins_filled,
        enough=enough,
        gaps=gaps,
        total_views=total,
    )
