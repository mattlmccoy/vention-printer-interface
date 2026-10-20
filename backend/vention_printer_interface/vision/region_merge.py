"""Merge axis-aligned filled cells into contiguous regions (outer loop + hole loops).

A calibration board drawn as one rectangle per marker bit engraves as a grid of outlined squares
when the laser software traces contours (seen on Trotec Ruby, 2026-10-20), and abutting fills can
double-burn or gap along shared edges. Merging gives one shape per black (or white) area.

Rules:
* cells sharing an edge of positive length belong to the same region;
* cells touching only at a corner are separate regions, and within a region a loop never revisits
  a vertex (at a pinch the tracer follows the empty area on its left), so no outline is
  self-touching;
* a region's loops are meant for the even-odd fill rule: the first loop is the outer boundary,
  the rest are holes. Collinear points are dropped.
Pure Python, no cv2 — coordinates are snapped to 1e-6 mm so float grids (3 mm bits at a 28.5 mm
offset) merge exactly.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]
_DIGITS = 6  # snap to 1e-6 mm


@dataclass(frozen=True)
class Region:
    """One contiguous filled area: ``loops[0]`` is the outer boundary, the rest are holes."""

    loops: list[list[Point]]


def _components(filled: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """4-connected components of the filled compressed cells."""
    seen: set[tuple[int, int]] = set()
    out: list[set[tuple[int, int]]] = []
    for start in sorted(filled):
        if start in seen:
            continue
        comp: set[tuple[int, int]] = set()
        stack = [start]
        seen.add(start)
        while stack:
            i, j = stack.pop()
            comp.add((i, j))
            for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if n in filled and n not in seen:
                    seen.add(n)
                    stack.append(n)
        out.append(comp)
    return out


def _boundary_edges(comp: set[tuple[int, int]]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Directed boundary edges (start vertex -> end vertices), cell kept on the walker's RIGHT
    (y points down). Edges shared by two filled cells are interior and never emitted."""
    out: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a: tuple[int, int], b: tuple[int, int]) -> None:
        out.setdefault(a, []).append(b)

    for i, j in comp:
        if (i, j - 1) not in comp:
            add((i, j), (i + 1, j))  # top, heading +x
        if (i + 1, j) not in comp:
            add((i + 1, j), (i + 1, j + 1))  # right, heading +y
        if (i, j + 1) not in comp:
            add((i + 1, j + 1), (i, j + 1))  # bottom, heading -x
        if (i - 1, j) not in comp:
            add((i, j + 1), (i, j))  # left, heading -y
    return out


def _trace(edges: dict[tuple[int, int], list[tuple[int, int]]]) -> list[list[tuple[int, int]]]:
    """Walk the directed edges into closed loops. At a pinch (two outgoing edges) prefer the
    left turn: it keeps the same EMPTY area on the walker's left, so the boundary of the outside
    and the boundary of a hole that meet there split into two loops instead of crossing."""
    loops: list[list[tuple[int, int]]] = []
    remaining = {a: list(bs) for a, bs in edges.items()}
    for start in sorted(edges):
        while remaining.get(start):
            loop = [start]
            prev, cur = start, remaining[start].pop()
            while cur != start:
                loop.append(cur)
                dx, dy = cur[0] - prev[0], cur[1] - prev[1]
                options = remaining[cur]
                # left turn (y down), straight, right turn
                for tx, ty in ((dy, -dx), (dx, dy), (-dy, dx)):
                    nxt = (cur[0] + tx, cur[1] + ty)
                    if nxt in options:
                        options.remove(nxt)
                        break
                else:  # pragma: no cover - a closed edge set always continues
                    raise RuntimeError("open boundary while tracing a region")
                prev, cur = cur, nxt
            loops.append(loop)
    return loops


def _drop_collinear(loop: list[tuple[int, int]]) -> list[tuple[int, int]]:
    n = len(loop)
    keep = []
    for k in range(n):
        (ax, ay), (bx, by), (cx, cy) = loop[k - 1], loop[k], loop[(k + 1) % n]
        if not ((ax == bx == cx) or (ay == by == cy)):
            keep.append(loop[k])
    return keep


def _area2(loop: list[Point]) -> float:
    edges = zip(loop, loop[1:] + loop[:1], strict=True)
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in edges)


def merge_rects(rects: Sequence[tuple[float, float, float, float]]) -> list[Region]:
    """Merge ``(x, y, w, h)`` rectangles (y down) into regions. Overlaps are allowed (union)."""
    if not rects:
        return []
    snapped = [
        (round(x, _DIGITS), round(y, _DIGITS), round(x + w, _DIGITS), round(y + h, _DIGITS))
        for x, y, w, h in rects
    ]
    xs = sorted({v for r in snapped for v in (r[0], r[2])})
    ys = sorted({v for r in snapped for v in (r[1], r[3])})
    filled: set[tuple[int, int]] = set()
    for x0, y0, x1, y1 in snapped:
        for i in range(bisect_left(xs, x0), bisect_left(xs, x1)):
            for j in range(bisect_left(ys, y0), bisect_left(ys, y1)):
                filled.add((i, j))

    regions: list[Region] = []
    for comp in _components(filled):
        loops = [
            [(float(xs[i]), float(ys[j])) for i, j in _drop_collinear(loop)]
            for loop in _trace(_boundary_edges(comp))
        ]
        loops.sort(key=lambda lp: -abs(_area2(lp)))  # outer boundary first
        regions.append(Region(loops))
    return regions
