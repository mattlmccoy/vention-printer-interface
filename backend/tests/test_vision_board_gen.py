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
# Each contiguous filled area is ONE <path> (outer loop + hole loops, fill-rule even-odd); the
# board used to be one <rect> per cell, which Trotec Ruby traced as a grid of outlines.
_REGION_RE = re.compile(
    r'<path class="(?P<cls>sq|bit|mg|scale)" d="(?P<d>[^"]+)" fill="#000000" '
    r'fill-rule="evenodd"/>'
)
_SVG_OPEN_RE = re.compile(
    r'<svg[^>]*\bwidth="(?P<w>[^"]+)"[^>]*\bheight="(?P<h>[^"]+)"[^>]*\bviewBox="(?P<vb>[^"]+)"'
)


def _regions(svg: str) -> list[dict[str, Any]]:
    """Every filled region: ``{"cls", "loops": [[(x, y), ...], ...]}`` parsed from its path."""
    out: list[dict[str, Any]] = []
    for m in _REGION_RE.finditer(svg):
        loops = []
        for sub in m.group("d").split("M")[1:]:
            nums = [float(v) for v in re.findall(r"[-\d.]+", sub)]
            loops.append(list(zip(nums[0::2], nums[1::2], strict=True)))
        out.append({"cls": m.group("cls"), "loops": loops})
    return out


def _in_region(region: dict[str, Any], px: float, py: float) -> bool:
    inside = False
    for loop in region["loops"]:
        for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1], strict=True):
            if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def _covered(regions: list[dict[str, Any]], px: float, py: float) -> bool:
    return any(_in_region(r, px, py) for r in regions)


def _bbox(region: dict[str, Any]) -> tuple[float, float, float, float]:
    pts = [p for loop in region["loops"] for p in loop]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


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
def test_filled_checker_region_count_matches_black_squares() -> None:
    svg = generate_charuco_svg(_SPEC, label=False)
    sq = [r for r in _regions(svg) if r["cls"] == "sq"]
    # checker squares touch only at corners, so each stays its own region (never a pinched
    # outline joining two squares at a point).
    assert len(sq) == _n_black_squares(_SPEC)
    for r in sq:
        assert len(r["loops"]) == 1 and len(r["loops"][0]) == 4
        x0, y0, x1, y1 = _bbox(r)
        assert x1 - x0 == pytest.approx(_SPEC.square_length_mm)
        assert y1 - y0 == pytest.approx(_SPEC.square_length_mm)


def test_board_has_no_per_cell_rectangles_only_evenodd_regions() -> None:
    svg = generate_charuco_svg(_SPEC, label=False)
    assert "<rect" not in svg
    assert _regions(svg), "no filled regions parsed"
    assert svg.count("<path") == len(_regions(svg)) + 1  # + the red cut outline


def test_each_markers_black_bits_merge_into_its_4_connected_areas() -> None:
    """Region count is read from reality: cv2's own bit image for every marker, split into
    4-connected black areas by cv2.connectedComponents. One area -> one engraved shape."""
    import cv2
    import cv2.aruco as aruco

    d = aruco.getPredefinedDictionary(getattr(aruco, _SPEC.aruco_dict))
    grid = int(d.markerSize) + 2
    expected = 0
    for marker_id in _marker_squares(_SPEC).values():
        black = (d.generateImageMarker(marker_id, grid, borderBits=1) == 0).astype(np.uint8)
        n_labels, _ = cv2.connectedComponents(black, connectivity=4)
        expected += n_labels - 1  # minus the background label
    bits = [r for r in _regions(generate_charuco_svg(_SPEC, label=False)) if r["cls"] == "bit"]
    assert len(bits) == expected
    n_cells = sum(
        int((d.generateImageMarker(i, grid, borderBits=1) == 0).sum())
        for i in _marker_squares(_SPEC).values()
    )
    assert len(bits) < n_cells / 5  # was one shape per black cell


# --- marker bits match generateImageMarker for a sampled id ----------------------------------
def test_marker_bit_rects_match_cv2_for_sampled_id() -> None:
    import cv2.aruco as aruco

    svg = generate_charuco_svg(_SPEC, label=False)
    bits = [r for r in _regions(svg) if r["cls"] == "bit"]
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

    # every bit cell centre is filled exactly when cv2 says the bit is black.
    got_black = {
        (c, r)
        for r in range(grid)
        for c in range(grid)
        if _covered(bits, marker_x0 + (c + 0.5) * cell, marker_y0 + (r + 0.5) * cell)
    }
    assert got_black == expected_black
    assert len(got_black) > 0


# --- engrave polarity inversion --------------------------------------------------------------
def test_engrave_black_false_is_exact_complement_within_pattern() -> None:
    svg_t = generate_charuco_svg(_SPEC, engrave_black=True, label=False)
    svg_f = generate_charuco_svg(_SPEC, engrave_black=False, label=False)
    rects_t = _regions(svg_t)
    rects_f = _regions(svg_f)

    # checker (solid-square) regions only appear on the black-fill polarity.
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


# --- cut outline (laser CUT path, distinct from the engrave fills) ---------------------------
def test_svg_has_cut_outline_at_board_perimeter_by_default() -> None:
    svg = generate_charuco_svg(_SPEC, label=False)
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None
    total_w, total_h = (float(v) for v in m.group("vb").split()[2:4])
    # The cut is a stroked path (not a fill) so a laser treats it as CUT, not ENGRAVE.
    cut = re.search(
        r'<path class="cut" d="(?P<d>[^"]+)"[^>]*fill="none"[^>]*stroke="(?P<s>[^"]+)"', svg
    )
    assert cut is not None, "no cut-outline path in the SVG"
    assert cut.group("s").lower() in ("#ff0000", "red")
    # the path traces the board's outer rectangle (0,0)->(total_w,total_h)
    assert f"{total_w:g}" in cut.group("d") and f"{total_h:g}" in cut.group("d")


def test_svg_cut_outline_can_be_disabled() -> None:
    assert 'class="cut"' not in generate_charuco_svg(_SPEC, label=False, cut_outline=False)


def test_dxf_cut_outline_is_a_closed_polyline_on_its_own_cut_layer() -> None:
    import io

    import ezdxf

    dxf = generate_charuco_dxf(_SPEC, label=False)
    doc = ezdxf.read(io.StringIO(dxf.decode("utf-8")))
    msp = doc.modelspace()
    cut = msp.query('LWPOLYLINE[layer=="CUT"]')
    assert len(cut) == 1, "expected exactly one CUT-layer perimeter polyline"
    assert cut[0].closed
    assert "CUT" in doc.layers


# --- DXF round-trip + entity count -----------------------------------------------------------
def test_dxf_roundtrips_and_entity_count_matches_svg_regions() -> None:
    import io

    import ezdxf
    from ezdxf import units

    for engrave_black in (True, False):
        svg = generate_charuco_svg(_SPEC, engrave_black=engrave_black, label=False)
        regions = _regions(svg)
        n_loops = sum(len(r["loops"]) for r in regions)
        dxf = generate_charuco_dxf(_SPEC, engrave_black=engrave_black, label=False)
        assert isinstance(dxf, bytes)
        doc = ezdxf.read(io.StringIO(dxf.decode("utf-8")))
        assert int(doc.units) == int(units.MM)
        msp = doc.modelspace()
        # engrave geometry lives on the ENGRAVE layer: each loop as an outline AND each region
        # as a SOLID hatch (DXF has no fill otherwise — outlines alone engraved as a grid of
        # empty boxes on Trotec Ruby). The CUT-layer perimeter is separate.
        assert len(msp.query('LWPOLYLINE[layer=="ENGRAVE"]')) == n_loops
        hatches = msp.query('HATCH[layer=="ENGRAVE"]')
        assert len(hatches) == len(regions)
        assert all(h.dxf.solid_fill == 1 for h in hatches)
        assert sum(len(h.paths) for h in hatches) == n_loops
        assert len(msp.query('LWPOLYLINE[layer=="CUT"]')) == 1


# --- M-3: generate -> detect round trip (strengthens the "detectable" guarantee) -------------
def _rasterize_black_polarity(spec: BoardSpec, *, px_per_mm: float) -> np.ndarray:
    """Draw the generated (engrave_black=True) board geometry to a numpy image.

    White background, the generated regions filled black with the even-odd rule the SVG
    declares (in that polarity the filled regions ARE exactly the black areas of a normal
    printed board), scaled from the SVG's own mm coordinates -- no SVG rasterization dependency,
    no rendering path other than the one this test is verifying. Exact for rectilinear loops:
    every vertical edge toggles the pixels to its right (pixel centres), then XOR along x.
    """
    svg = generate_charuco_svg(spec, engrave_black=True, label=False)
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None
    total_w, total_h = (float(v) for v in m.group("vb").split()[2:4])
    w_px = int(round(total_w * px_per_mm))
    h_px = int(round(total_h * px_per_mm))
    toggles = np.zeros((h_px, w_px + 1), dtype=np.uint8)
    for region in _regions(svg):
        for loop in region["loops"]:
            for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1], strict=True):
                if x1 != x2:
                    continue  # horizontal edge
                ya, yb = sorted((y1, y2))
                r0 = max(0, int(np.ceil(ya * px_per_mm - 0.5)))
                r1 = min(h_px, int(np.ceil(yb * px_per_mm - 0.5)))
                c = min(w_px, max(0, int(np.floor(x1 * px_per_mm - 0.5)) + 1))
                toggles[r0:r1, c] ^= 1
    filled = np.bitwise_xor.accumulate(toggles, axis=1)[:, :w_px].astype(bool)
    return np.where(filled, 0, 255).astype(np.uint8)


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


@pytest.mark.parametrize("preset_name", sorted(BOARD_PRESETS))
def test_every_shipped_preset_is_detected_by_charuco_detector(preset_name: str) -> None:
    """Confirm every SHIPPED preset actually works: rasterize its generated geometry and run the
    real cv2 ChArUco detector — all interior corners must be found with the exact expected ids."""
    from vention_printer_interface.vision.registration import detect_board

    spec = resolve_preset(preset_name)
    image = _rasterize_black_polarity(spec, px_per_mm=10.0)

    detection = detect_board(image, spec)

    assert detection is not None, f"{preset_name}: generated board was not detected"
    n_inner = (spec.squares_x - 1) * (spec.squares_y - 1)
    got_ids = {int(i) for i in detection.ids.ravel()}
    missing = set(range(n_inner)) - got_ids
    assert got_ids == set(range(n_inner)), f"{preset_name}: missing corners {missing}"
    assert len(detection.image_points) == n_inner


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


# ---- dictionary sizing + spec validation (fix/charuco-board-calibrate) ----------------------
# Capacities below are the REAL cv2 values (``getPredefinedDictionary(..).bytesList.shape[0]``,
# probed on OpenCV 5.0.0): 4X4_50=50, 4X4_100=100, 4X4_250=250, 4X4_1000=1000, 5X5_100=100.
def _charuco_spec(sx: int, sy: int, dict_name: str = "DICT_4X4_50", sq: float = 10.0,
                  mk: float = 7.0) -> BoardSpec:
    return BoardSpec(kind="charuco", squares_x=sx, squares_y=sy, square_length_mm=sq,
                     marker_length_mm=mk, aruco_dict=dict_name)


def test_markers_needed_is_half_the_squares_rounded_down() -> None:
    from vention_printer_interface.vision.board_gen import markers_needed

    assert markers_needed(9, 12) == 54
    assert markers_needed(4, 4) == 8
    assert markers_needed(5, 7) == 17
    # Cross-check against the real cv2 board's own marker count.
    assert markers_needed(5, 7) == len(_charuco(_charuco_spec(5, 7)).getIds())


def test_dict_capacity_reads_the_real_cv2_dictionary_size() -> None:
    from vention_printer_interface.vision.board_gen import BoardSpecError, dict_capacity

    assert dict_capacity("DICT_4X4_50") == 50
    assert dict_capacity("DICT_4X4_1000") == 1000
    assert dict_capacity("DICT_5X5_100") == 100
    with pytest.raises(BoardSpecError):
        dict_capacity("CharucoBoard")  # a real cv2.aruco attribute, but not a dictionary


@pytest.mark.parametrize(
    ("sx", "sy", "expected"),
    [(4, 4, "DICT_4X4_50"), (10, 10, "DICT_4X4_50"), (11, 10, "DICT_4X4_100"),
     (9, 12, "DICT_4X4_100"), (20, 20, "DICT_4X4_250"), (40, 40, "DICT_4X4_1000")],
)
def test_pick_aruco_dict_is_the_smallest_adequate_4x4(sx: int, sy: int, expected: str) -> None:
    from vention_printer_interface.vision.board_gen import pick_aruco_dict

    assert pick_aruco_dict(sx, sy) == expected


def test_shipped_presets_keep_their_dictionary_under_auto_pick() -> None:
    from vention_printer_interface.vision.board_gen import pick_aruco_dict

    for spec in BOARD_PRESETS.values():
        assert pick_aruco_dict(spec.squares_x, spec.squares_y) == spec.aruco_dict


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        (_charuco_spec(1, 12), "at least 2"),
        (_charuco_spec(12, 1), "at least 2"),
        (_charuco_spec(41, 5), "40"),
        (_charuco_spec(9, 12, "DICT_4X4_50"), "54"),
        (_charuco_spec(5, 5, "DICT_NOPE"), "unknown"),
        (_charuco_spec(5, 5, sq=10.0, mk=10.0), "marker"),
        (_charuco_spec(5, 5, sq=0.0, mk=0.0), "marker"),
    ],
)
def test_validate_charuco_spec_rejects_bad_boards(spec: BoardSpec, fragment: str) -> None:
    from vention_printer_interface.vision.board_gen import BoardSpecError, validate_charuco_spec

    with pytest.raises(BoardSpecError, match=fragment):
        validate_charuco_spec(spec)


def test_validate_charuco_spec_accepts_good_boards() -> None:
    from vention_printer_interface.vision.board_gen import validate_charuco_spec

    validate_charuco_spec(_charuco_spec(9, 12, "DICT_4X4_100"))
    validate_charuco_spec(_charuco_spec(7, 5, "DICT_5X5_100"))
    validate_charuco_spec(_charuco_spec(2, 2))


def test_generation_refuses_a_one_wide_board_before_touching_cv2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 1-wide CharucoBoard raises SystemError in cv2 and can leave the process unstable
    (observed: a later cv2 call dies with SIGTRAP). Generation must never construct one."""
    import cv2.aruco as aruco

    from vention_printer_interface.vision.board_gen import BoardSpecError

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("CharucoBoard must not be constructed for an invalid spec")

    monkeypatch.setattr(aruco, "CharucoBoard", _boom)
    with pytest.raises(BoardSpecError):
        generate_charuco_svg(_charuco_spec(1, 12))
    with pytest.raises(BoardSpecError):
        generate_charuco_dxf(_charuco_spec(12, 1))


def test_board_generation_runs_one_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent requests queue behind one generation slot instead of piling up memory."""
    import threading
    import time

    from vention_printer_interface.vision import board_gen

    active = 0
    peak = 0
    guard = threading.Lock()
    real = board_gen._filled_cells

    def _slow_cells(spec: BoardSpec, *, engrave_black: bool) -> Any:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        try:
            return real(spec, engrave_black=engrave_black)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(board_gen, "_filled_cells", _slow_cells)
    spec = _charuco_spec(4, 4)
    threads = [threading.Thread(target=generate_charuco_svg, args=(spec,)) for _ in range(3)]
    threads += [threading.Thread(target=generate_charuco_dxf, args=(spec,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1


# ---- caliper scale bar: every board carries a known length so its size can be checked -------
def _margin(svg: str, spec: BoardSpec) -> float:
    m = _SVG_OPEN_RE.search(svg)
    assert m is not None
    return (float(m.group("vb").split()[2]) - spec.squares_x * spec.square_length_mm) / 2


@pytest.mark.parametrize(
    ("preset_name", "length_mm"),
    [("medium_5x7", 100.0), ("large_6x9", 100.0), ("small_cylinder", 50.0)],
)
def test_scale_bar_is_a_round_length_that_fits_the_pattern_width(
    preset_name: str, length_mm: float
) -> None:
    spec = resolve_preset(preset_name)
    svg = generate_charuco_svg(spec, label=False)
    scale = [r for r in _regions(svg) if r["cls"] == "scale"]
    assert len(scale) == 1, "the bar and its ticks must be ONE engraved shape"
    x0, y0, x1, y1 = _bbox(scale[0])
    margin = _margin(svg, spec)
    assert x1 - x0 == pytest.approx(length_mm, abs=1e-6)  # outer edge to outer edge
    assert x0 == pytest.approx(margin)
    assert y1 < margin * 0.75  # in the top quiet zone, clear of the pattern
    assert f">{length_mm:g} mm</text>" in svg


def test_scale_bar_can_be_disabled() -> None:
    svg = generate_charuco_svg(_SPEC, label=False, scale_bar=False)
    assert not [r for r in _regions(svg) if r["cls"] == "scale"]
    assert " mm</text>" not in svg


def test_scale_bar_is_engraved_in_both_polarities_and_in_the_dxf() -> None:
    import io

    import ezdxf

    for engrave_black in (True, False):
        svg = generate_charuco_svg(_SPEC, engrave_black=engrave_black, label=False)
        assert len([r for r in _regions(svg) if r["cls"] == "scale"]) == 1
    dxf = generate_charuco_dxf(_SPEC, label=False)
    texts = [t.dxf.text for t in ezdxf.read(io.StringIO(dxf.decode())).modelspace().query("TEXT")]
    assert "100 mm" in texts
