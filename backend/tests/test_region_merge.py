"""Merging a board's filled cells into contiguous regions (vision/region_merge.py).

Why: the engraved board came out as a grid of tiny outlined squares — every marker bit was its
own rectangle (489 on the 5x7 board), so Trotec Ruby traced each one. A region is one outer loop
plus hole loops (even-odd); cells that touch only at a corner stay in separate regions, so no
loop ever passes through the same vertex twice (a pinched outline some laser software misfills).
"""

from __future__ import annotations

import itertools

import pytest

from vention_printer_interface.vision.region_merge import Region, merge_rects

Rect = tuple[float, float, float, float]


def _cells(*xy: tuple[int, int], size: float = 1.0) -> list[Rect]:
    return [(x * size, y * size, size, size) for x, y in xy]


def _inside(loops: list[list[tuple[float, float]]], px: float, py: float) -> bool:
    """Even-odd point-in-polygon over all loops (the SVG ``fill-rule="evenodd"`` rule)."""
    inside = False
    for loop in loops:
        for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1], strict=True):
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _covered_by_rects(rects: list[Rect], px: float, py: float) -> bool:
    return any(x <= px < x + w and y <= py < y + h for x, y, w, h in rects)


def _assert_same_coverage(regions: list[Region], rects: list[Rect], step: float = 0.25) -> None:
    xs = [x for x, _, w, _ in rects] + [x + w for x, _, w, _ in rects]
    ys = [y for _, y, _, h in rects] + [y + h for _, y, _, h in rects]
    loops = [loop for r in regions for loop in r.loops]
    x = min(xs) - step / 2
    while x < max(xs) + step:
        y = min(ys) - step / 2
        while y < max(ys) + step:
            assert _inside(loops, x, y) == _covered_by_rects(rects, x, y), (x, y)
            y += step
        x += step


def _assert_simple(regions: list[Region]) -> None:
    for r in regions:
        for loop in r.loops:
            assert len(loop) == len(set(loop)), f"loop revisits a vertex: {loop}"


def test_two_edge_touching_cells_become_one_rectangle() -> None:
    regions = merge_rects(_cells((0, 0), (1, 0)))
    assert len(regions) == 1
    assert len(regions[0].loops) == 1
    assert sorted(regions[0].loops[0]) == [(0, 0), (0, 1), (2, 0), (2, 1)]  # no collinear points


def test_ring_of_cells_is_one_region_with_a_hole() -> None:
    ring = [(x, y) for x in range(3) for y in range(3) if (x, y) != (1, 1)]
    rects = _cells(*ring)
    regions = merge_rects(rects)
    assert len(regions) == 1
    assert len(regions[0].loops) == 2  # outer + hole
    _assert_same_coverage(regions, rects)
    _assert_simple(regions)


def test_corner_touching_cells_stay_separate_regions() -> None:
    regions = merge_rects(_cells((0, 0), (1, 1)))
    assert len(regions) == 2
    _assert_simple(regions)


def test_pinch_inside_one_region_never_revisits_a_vertex() -> None:
    # (0,1) and (1,0) meet only at the corner (1,1), but the ring joins them into ONE region:
    # the hole at (1,1) touches the outside at that corner. Loops must still be simple.
    filled = [(1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2), (0, 1)]
    rects = _cells(*filled)
    regions = merge_rects(rects)
    assert len(regions) == 1
    _assert_simple(regions)
    _assert_same_coverage(regions, rects)


def test_non_unit_grid_and_offsets_are_exact() -> None:
    # marker bits are 3 mm cells at a 28.5 mm offset — float coordinates must merge exactly.
    rects = [(28.5 + 3.0 * i, 53.5, 3.0, 3.0) for i in range(6)]
    regions = merge_rects(rects)
    assert len(regions) == 1
    xs = sorted({x for x, _ in regions[0].loops[0]})
    assert xs == [pytest.approx(28.5), pytest.approx(46.5)]


def test_random_cell_patterns_keep_coverage_and_simple_loops() -> None:
    import random

    rng = random.Random(7)
    for _ in range(40):
        filled = [
            (x, y) for x, y in itertools.product(range(6), range(6)) if rng.random() < 0.55
        ]
        rects = _cells(*filled, size=3.0)
        regions = merge_rects(rects)
        _assert_simple(regions)
        _assert_same_coverage(regions, rects, step=0.75)


def test_no_rects_no_regions() -> None:
    assert merge_rects([]) == []
