"""Calibration capture coverage (pure, hardware-free).

A good intrinsics calibration needs the board across the whole frame AND at several tilts. It
turns the accumulated view descriptors into a coverage grid (N×N cells × a few tilt bins) so
the wizard can guide the operator ("need a view top-left / more tilt") and gate finalize until the
capture set is diverse enough. No IO.

A view descriptor is a dict ``{"centroid_px": (cx,cy), "tilt_deg": t, "image_size": (w,h)}``
plus, from 2026-10-20, ``"corners_px"`` (the detected corner pixels). A cell counts as covered when
any CORNER lands in it: a board that fills most of the frame can never put its centre in an edge
cell (a 13-view run stayed at 1/9), yet its corners cover most of the frame in one view. Old
descriptors without corners count their centroid cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Out-of-plane tilt bin edges (deg): bin 0 = near fronto-parallel, then increasing tilt.
_TILT_EDGES = (10.0, 25.0)
# Manual-capture gate: enough distinct views, most of the frame covered by corners, and at least two
# tilt ranges (the manual wizard fits full intrinsics, which needs some tilt).
_MIN_CELLS = 6
_MIN_TILT_BINS = 2


def _cell(x: float, y: float, w: float, h: float, grid: tuple[int, int]) -> tuple[int, int]:
    gx = min(grid[0] - 1, max(0, int(x / w * grid[0])))
    gy = min(grid[1] - 1, max(0, int(y / h * grid[1])))
    return gx, gy


def corner_cells(
    points_px: list[Any], image_size: tuple[int, int], grid: tuple[int, int] = (3, 3)
) -> list[list[bool]]:
    """``cells[row][col]`` is True when any corner of any view lands in that frame cell."""
    w, h = float(image_size[0]), float(image_size[1])
    cells = [[False] * grid[0] for _ in range(grid[1])]
    for pts in points_px:
        for x, y in (tuple(p) for p in pts):
            gx, gy = _cell(float(x), float(y), w, h, grid)
            cells[gy][gx] = True
    return cells


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
        w, h = d["image_size"]
        pts = d.get("corners_px") or [d["centroid_px"]]
        for gx, gy in {_cell(float(x), float(y), w, h, grid) for x, y in pts}:
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
    want_tilts = min(tilt_bins, _MIN_TILT_BINS)
    if tilt_bins_filled < want_tilts:
        gaps.append("tilt")
    enough = (
        cells_filled >= min(_MIN_CELLS, gx_count * gy_count)
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

