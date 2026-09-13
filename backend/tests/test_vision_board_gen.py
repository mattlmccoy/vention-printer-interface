"""TDD tests for vision/board_gen.py — TRUE-VECTOR ChArUco board generation (A8).

Hardware-free: no camera. cv2.aruco is used only to build the *canonical* board object
(the same one the detector in registration.py uses) and to read marker bits via the
1px-per-bit ``generateImageMarker`` trick, so a generated board is guaranteed detectable
and dimensionally correct. Fixtures are captured from the real cv2 board object, never
invented (data-contract-verification discipline).
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pytest

from vention_printer_interface.vision.board_gen import (
    BOARD_PRESETS,
    generate_charuco_dxf,
    generate_charuco_svg,
    resolve_preset,
)
from vention_printer_interface.vision.registration import BoardSpec

# --- regex parsers over the generated SVG (attribute order is fixed by the writer) -----------
_RECT_RE = re.compile(
    r'<rect class="(?P<cls>[a-z]+)" x="(?P<x>[-\d.]+)" y="(?P<y>[-\d.]+)" '
    r'width="(?P<w>[-\d.]+)" height="(?P<h>[-\d.]+)"'
)
_SVG_OPEN_RE = re.compile(
    r'<svg[^>]*\bwidth="(?P<w>[^"]+)"[^>]*\bheight="(?P<h>[^"]+)"[^>]*\bviewBox="(?P<vb>[^"]+)"'
)


def _rects(svg: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _RECT_RE.finditer(svg):
        out.append(
            {
                "cls": m.group("cls"),
                "x": float(m.group("x")),
                "y": float(m.group("y")),
                "w": float(m.group("w")),
                "h": float(m.group("h")),
            }
        )
    return out


def _covered(rects: list[dict[str, Any]], px: float, py: float) -> bool:
    for r in rects:
        if r["x"] <= px <= r["x"] + r["w"] and r["y"] <= py <= r["y"] + r["h"]:
            return True
    return False


# --- canonical-board helpers, captured from the real cv2.aruco object ------------------------
def _charuco(spec: BoardSpec) -> Any:
    import cv2.aruco as aruco

    d = aruco.getPredefinedDictionary(getattr(aruco, spec.aruco_dict))
    return aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y), spec.square_length_mm, spec.marker_length_mm, d
    )


def _marker_squares(spec: BoardSpec) -> dict[tuple[int, int], int]:
    """Real map {(col,row): marker_id} read off the cv2 CharucoBoard's object points."""
    board = _charuco(spec)
    op = np.asarray(board.getObjPoints())
    ids = np.asarray(board.getIds()).ravel()
    out: dict[tuple[int, int], int] = {}
    for k in range(len(op)):
        cx = float(op[k][:, 0].mean())
        cy = float(op[k][:, 1].mean())
        col = int(cx // spec.square_length_mm)
        row = int(cy // spec.square_length_mm)
        out[(col, row)] = int(ids[k])
    return out


def _n_black_squares(spec: BoardSpec) -> int:
    total = spec.squares_x * spec.squares_y
    return total - len(_marker_squares(spec))


_SPEC = BoardSpec(
    kind="charuco",
    squares_x=5,
    squares_y=7,
    square_length_mm=20.0,
    marker_length_mm=15.0,
    aruco_dict="DICT_4X4_50",
)


# --- SVG dimensions --------------------------------------------------------------------------
def test_svg_width_height_viewbox_exact_mm() -> None:
    svg = generate_charuco_svg(_SPEC, label=False)
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None, "svg root with width/height/viewBox not found"
    board_w = _SPEC.squares_x * _SPEC.square_length_mm
    board_h = _SPEC.squares_y * _SPEC.square_length_mm
    # width/height carry a quiet-zone margin on both sides; parse it back from viewBox.
    vb = [float(v) for v in m.group("vb").split()]
    assert vb[0] == 0.0 and vb[1] == 0.0
    total_w, total_h = vb[2], vb[3]
    margin = (total_w - board_w) / 2
    assert margin > 0
    assert total_h == pytest.approx(board_h + 2 * margin)
    # width/height attributes are in mm and equal the viewBox extents.
    assert m.group("w") == f"{total_w:g}mm"
    assert m.group("h") == f"{total_h:g}mm"


# --- checker rect count == black-square count ------------------------------------------------
def test_filled_checker_rect_count_matches_black_squares() -> None:
    svg = generate_charuco_svg(_SPEC, label=False)
    sq_rects = [r for r in _rects(svg) if r["cls"] == "sq"]
    assert len(sq_rects) == _n_black_squares(_SPEC)
    # every checker rect is exactly one square in size, at exact mm.
    for r in sq_rects:
        assert r["w"] == pytest.approx(_SPEC.square_length_mm)
        assert r["h"] == pytest.approx(_SPEC.square_length_mm)


# --- marker bits match generateImageMarker for a sampled id ----------------------------------
def test_marker_bit_rects_match_cv2_for_sampled_id() -> None:
    import cv2.aruco as aruco

    svg = generate_charuco_svg(_SPEC, label=False)
    rects = _rects(svg)
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None
    board_w = _SPEC.squares_x * _SPEC.square_length_mm
    total_w = float(m.group("vb").split()[2])
    margin = (total_w - board_w) / 2

    msquares = _marker_squares(_SPEC)
    (col, row), marker_id = sorted(msquares.items(), key=lambda kv: kv[1])[0]

    d = aruco.getPredefinedDictionary(getattr(aruco, _SPEC.aruco_dict))
    marker_size = int(d.markerSize)
    grid = marker_size + 2  # borderBits=1 each side
    expected_img = d.generateImageMarker(marker_id, grid, borderBits=1)
    expected_black = {
        (c, r)
        for r in range(grid)
        for c in range(grid)
        if int(expected_img[r, c]) == 0
    }

    inset = (_SPEC.square_length_mm - _SPEC.marker_length_mm) / 2
    cell = _SPEC.marker_length_mm / grid
    marker_x0 = margin + col * _SPEC.square_length_mm + inset
    marker_y0 = margin + row * _SPEC.square_length_mm + inset

    got_black: set[tuple[int, int]] = set()
    for rc in rects:
        if rc["cls"] != "bit":
            continue
        # keep only bit rects inside this marker's footprint
        if not (marker_x0 - 1e-6 <= rc["x"] < marker_x0 + _SPEC.marker_length_mm - 1e-6):
            continue
        if not (marker_y0 - 1e-6 <= rc["y"] < marker_y0 + _SPEC.marker_length_mm - 1e-6):
            continue
        c = int(round((rc["x"] - marker_x0) / cell))
        r = int(round((rc["y"] - marker_y0) / cell))
        got_black.add((c, r))
        assert rc["w"] == pytest.approx(cell)
        assert rc["h"] == pytest.approx(cell)

    assert got_black == expected_black
    assert len(got_black) > 0


# --- engrave polarity inversion --------------------------------------------------------------
def test_engrave_black_false_is_exact_complement_within_pattern() -> None:
    svg_t = generate_charuco_svg(_SPEC, engrave_black=True, label=False)
    svg_f = generate_charuco_svg(_SPEC, engrave_black=False, label=False)
    rects_t = _rects(svg_t)
    rects_f = _rects(svg_f)

    # checker (solid-square) rects only appear on the black-fill polarity.
    assert len([r for r in rects_t if r["cls"] == "sq"]) == _n_black_squares(_SPEC)
    assert len([r for r in rects_f if r["cls"] == "sq"]) == 0

    m = _SVG_OPEN_RE.search(svg_t)
    assert m is not None
    board_w = _SPEC.squares_x * _SPEC.square_length_mm
    board_h = _SPEC.squares_y * _SPEC.square_length_mm
    total_w = float(m.group("vb").split()[2])
    margin = (total_w - board_w) / 2

    # Sample a grid strictly inside pattern cells (avoid exact cell boundaries): the two
    # polarities must be exact complements over the board pattern area.
    rng = np.random.default_rng(0)
    step = _SPEC.marker_length_mm / (int(_charuco(_SPEC).getDictionary().markerSize) + 2) / 3
    x = margin + step * 1.5
    checked = 0
    while x < margin + board_w - step:
        y = margin + step * 1.5
        while y < margin + board_h - step:
            px = x + rng.uniform(-step * 0.1, step * 0.1)
            py = y + rng.uniform(-step * 0.1, step * 0.1)
            # exact complement over the pattern area: exactly one polarity fills each point.
            assert _covered(rects_t, px, py) != _covered(rects_f, px, py), (px, py)
            checked += 1
            y += step
        x += step
    assert checked > 100


# --- presets ---------------------------------------------------------------------------------
def test_small_cylinder_preset_fits_101p6_circle() -> None:
    spec = resolve_preset("small_cylinder")
    diag = math.hypot(
        spec.squares_x * spec.square_length_mm, spec.squares_y * spec.square_length_mm
    )
    assert diag <= 101.6


def test_presets_exist_and_are_charuco() -> None:
    assert set(BOARD_PRESETS) == {"small_cylinder", "medium_5x7", "large_6x9"}
    assert resolve_preset("medium_5x7").squares_x == 5
    assert resolve_preset("medium_5x7").squares_y == 7
    assert resolve_preset("large_6x9").squares_x == 6
    assert resolve_preset("large_6x9").squares_y == 9
    for name in BOARD_PRESETS:
        assert resolve_preset(name).kind == "charuco"


def test_resolve_preset_overrides_fields() -> None:
    spec = resolve_preset("medium_5x7", square_length_mm=12.0, aruco_dict="DICT_5X5_100")
    assert spec.square_length_mm == 12.0
    assert spec.aruco_dict == "DICT_5X5_100"
    assert spec.squares_x == 5  # untouched


def test_resolve_preset_bad_name_raises() -> None:
    with pytest.raises(KeyError):
        resolve_preset("nope")


# --- DXF round-trip + entity count -----------------------------------------------------------
def test_dxf_roundtrips_and_entity_count_matches_svg_filled_cells() -> None:
    import io

    import ezdxf
    from ezdxf import units

    for engrave_black in (True, False):
        svg = generate_charuco_svg(_SPEC, engrave_black=engrave_black, label=False)
        n_filled = len(_rects(svg))
        dxf = generate_charuco_dxf(_SPEC, engrave_black=engrave_black, label=False)
        assert isinstance(dxf, bytes)
        doc = ezdxf.read(io.StringIO(dxf.decode("utf-8")))
        assert int(doc.units) == int(units.MM)
        msp = doc.modelspace()
        assert len(msp.query("LWPOLYLINE")) == n_filled


# --- M-3: generate -> detect round trip (strengthens the "detectable" guarantee) -------------
def _rasterize_black_polarity(spec: BoardSpec, *, px_per_mm: float) -> np.ndarray:
    """Draw the generated (engrave_black=True) board geometry to a numpy image.

    White background, black filled rectangles for every generated ``sq``/``bit`` cell (in that
    polarity the filled cells ARE exactly the black regions of a normal printed board), scaled
    from the SVG's own mm coordinates -- no SVG rasterization dependency, no rendering path
    other than the one this test is verifying (data-contract-verification: reality, not belief).
    """
    import cv2

    svg = generate_charuco_svg(spec, engrave_black=True, label=False)
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None
    total_w, total_h = (float(v) for v in m.group("vb").split()[2:4])
    w_px = int(round(total_w * px_per_mm))
    h_px = int(round(total_h * px_per_mm))
    img = np.full((h_px, w_px), 255, dtype=np.uint8)
    for r in _rects(svg):
        x0 = int(round(r["x"] * px_per_mm))
        y0 = int(round(r["y"] * px_per_mm))
        x1 = int(round((r["x"] + r["w"]) * px_per_mm))
        y1 = int(round((r["y"] + r["h"]) * px_per_mm))
        cv2.rectangle(img, (x0, y0), (x1, y1), color=0, thickness=-1)
    return img


def test_generated_board_rasterized_is_detected_by_charuco_detector() -> None:
    from vention_printer_interface.vision.registration import detect_board

    image = _rasterize_black_polarity(_SPEC, px_per_mm=8.0)

    detection = detect_board(image, _SPEC)

    assert detection is not None, "generated board was not detected at all"
    n_inner_corners = (_SPEC.squares_x - 1) * (_SPEC.squares_y - 1)
    expected_ids = set(range(n_inner_corners))
    got_ids = set(int(i) for i in detection.ids.ravel())
    assert got_ids == expected_ids
    assert len(detection.image_points) == n_inner_corners
    assert len(detection.object_points) == n_inner_corners


def test_dxf_and_svg_include_label_when_requested() -> None:
    import io

    import ezdxf

    svg = generate_charuco_svg(_SPEC, label=True)
    assert "<text" in svg
    assert _SPEC.aruco_dict in svg
    assert f"{_SPEC.squares_x}x{_SPEC.squares_y}" in svg

    dxf = generate_charuco_dxf(_SPEC, label=True)
    doc = ezdxf.read(io.StringIO(dxf.decode("utf-8")))
    texts = doc.modelspace().query("TEXT")
    assert len(texts) >= 1
