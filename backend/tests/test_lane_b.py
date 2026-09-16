import cv2
import numpy as np
import pytest

from vention_printer_interface.analysis.lane_b import (
    analyze_lane_b,
    deviation_field,
    largest_contour,
)


def _filled_square_img(side_px: int, canvas: int = 200) -> np.ndarray:
    """A white filled square (the 'part') centred on a black canvas."""
    img = np.zeros((canvas, canvas), dtype=np.uint8)
    c = canvas // 2
    h = side_px // 2
    cv2.rectangle(img, (c - h, c - h), (c + h, c + h), 255, -1)
    return img


def _square(cx: float, cy: float, half: float, n: int = 80) -> np.ndarray:
    """A square outline centred at (cx, cy) with side 2*half, as ~n points around the perimeter."""
    corners = [(cx - half, cy - half), (cx + half, cy - half),
               (cx + half, cy + half), (cx - half, cy + half)]
    per_edge = max(1, n // 4)
    pts: list[tuple[float, float]] = []
    for i in range(4):
        x0, y0 = corners[i]
        x1, y1 = corners[(i + 1) % 4]
        for k in range(per_edge):
            f = k / per_edge
            pts.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return np.asarray(pts, dtype=float)


def test_identical_outlines_have_zero_deviation() -> None:
    cad = _square(50, 50, 10)
    printed = _square(50, 50, 10)
    f = deviation_field(printed, cad)
    assert f.max_abs_mm == pytest.approx(0.0, abs=0.2)
    assert f.mean_abs_mm == pytest.approx(0.0, abs=0.1)
    assert f.area_ratio == pytest.approx(1.0, abs=0.02)


def test_printed_larger_than_cad_reads_positive_over() -> None:
    # A printed square 1 mm bigger on each side than the CAD square: every printed edge point sits
    # ~1 mm OUTSIDE the CAD outline -> positive deviation, area ratio > 1.
    cad = _square(50, 50, 10)
    printed = _square(50, 50, 11)
    f = deviation_field(printed, cad)
    assert min(f.deviations_mm) > 0.5          # all points outside CAD (edges ~1 mm out)
    assert f.mean_abs_mm == pytest.approx(1.0, abs=0.3)   # edge points dominate at ~1 mm
    assert f.max_abs_mm > 0.9                  # corners reach ~√2 mm from the CAD outline
    assert f.area_ratio > 1.1


def test_printed_smaller_than_cad_reads_negative_under() -> None:
    cad = _square(50, 50, 10)
    printed = _square(50, 50, 9)
    f = deviation_field(printed, cad)
    assert max(f.deviations_mm) < -0.5         # all points inside CAD (under-deposited)
    assert f.area_ratio < 0.9


def test_localized_bulge_is_flagged_at_its_location() -> None:
    # CAD square; printed identical except one point pushed +3 mm outward in +x — the max deviation
    # should be ~3 mm and located near that pushed point.
    cad = _square(50, 50, 10)
    printed = _square(50, 50, 10)
    # find a point on the right edge (x≈60) and push it out
    idx = int(np.argmax(printed[:, 0]))
    printed[idx] = (printed[idx][0] + 3.0, printed[idx][1])
    f = deviation_field(printed, cad)
    assert f.max_abs_mm == pytest.approx(3.0, abs=0.5)
    assert f.max_at_mm[0] > 60.0               # near the bulged right edge


def test_largest_contour_finds_the_square() -> None:
    img = _filled_square_img(100)
    c = largest_contour(img)
    assert c is not None
    xs, ys = c[:, 0], c[:, 1]
    assert (xs.max() - xs.min()) == pytest.approx(100, abs=3)   # ~100 px wide
    assert (ys.max() - ys.min()) == pytest.approx(100, abs=3)


def test_analyze_lane_b_flags_oversized_part() -> None:
    # Printed square 100 px (10 mm at 0.1 mm/px); CAD square 90 px (9 mm). Printed is ~1 mm bigger
    # per side -> positive deviation (over), area ratio > 1.
    printed = _filled_square_img(100)
    cad = _filled_square_img(90)
    r = analyze_lane_b(printed, cad, printed_mm_per_px=0.1, cad_mm_per_px=0.1)
    assert r["status"] == "ok"
    assert r["mean_abs_mm"] == pytest.approx(0.5, abs=0.25)   # ~0.5 mm edge deviation
    assert r["area_ratio"] > 1.1
    assert len(r["points_px"]) == r["n"] and r["n"] > 0


def test_analyze_lane_b_no_contour_status() -> None:
    blank = np.zeros((200, 200), dtype=np.uint8)
    r = analyze_lane_b(blank, _filled_square_img(80), 0.1, 0.1)
    assert r["status"] == "no_contour"
