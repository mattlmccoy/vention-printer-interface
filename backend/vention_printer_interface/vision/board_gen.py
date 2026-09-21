"""TRUE-VECTOR ChArUco calibration-board generation for laser-engraving dual-color ABS.

The board is drawn as vector geometry at exact **millimetre** coordinates — never a raster
(``cv2.aruco...generateImage`` is a bitmap, unusable for a laser). The canonical geometry is
read straight off the ``cv2.aruco.CharucoBoard`` object that ``registration.detect_board``
uses, so a generated board is dimensionally correct and actually detectable:

* the marker ids and their squares come from ``board.getObjPoints()`` / ``board.getIds()``;
* each marker's black/white **bit** grid is read via the version-stable 1-pixel-per-bit trick
  ``dictionary.generateImageMarker(id, markerSize + 2, borderBits=1)`` — the returned image is
  exactly ``(markerSize + 2)`` cells square, one pixel per bit, ``0`` black / ``255`` white.

Fill / engrave polarity (dual-color ABS: engraving removes the top color to reveal the
second) is a true photographic negative, taken over the board **pattern** area only (never the
outer quiet zone):

* ``engrave_black=True``  fills the BLACK regions — solid non-marker squares + black bit cells.
* ``engrave_black=False`` fills the WHITE regions — white bit cells + the white margin ring
  around each marker.

Both polarities engrave to the *same* visible board; which one to use depends on which ABS
color is on top. The two fill sets are exact complements within the pattern box, so a black
non-marker square filled at ``True`` is empty at ``False`` and vice-versa.
"""

from __future__ import annotations

import io
from dataclasses import replace
from typing import Any

from vention_printer_interface.vision.registration import BoardSpec

# Preset library. Every field is overridable via ``resolve_preset(name, **overrides)``.
# ``small_cylinder`` is sized so the board's bounding circle fits a Ø101.6 mm (4 in) cylinder
# top: hypot(4*16, 4*16) = 90.5 mm <= 101.6 mm.
BOARD_PRESETS: dict[str, BoardSpec] = {
    "small_cylinder": BoardSpec(
        kind="charuco",
        squares_x=4,
        squares_y=4,
        square_length_mm=16.0,
        marker_length_mm=12.0,
        aruco_dict="DICT_4X4_50",
    ),
    "medium_5x7": BoardSpec(
        kind="charuco",
        squares_x=5,
        squares_y=7,
        square_length_mm=25.0,
        marker_length_mm=18.0,
        aruco_dict="DICT_4X4_50",
    ),
    "large_6x9": BoardSpec(
        kind="charuco",
        squares_x=6,
        squares_y=9,
        square_length_mm=30.0,
        marker_length_mm=22.0,
        aruco_dict="DICT_4X4_50",
    ),
}

# Colour every filled cell engraves in (single engrave layer). Polarity chooses which cells.
_ENGRAVE_COLOR = "#000000"
# The board outline is a CUT, not an engrave: a stroked-only red path (SVG) / a polyline on a
# dedicated "CUT" layer (DXF), the near-universal laser convention (red = cut, black = engrave),
# so the operator's laser software maps it to the cut operation and separates the board from stock.
_CUT_COLOR = "#ff0000"
_CUT_STROKE_MM = 0.1
_CUT_LAYER = "CUT"
_ENGRAVE_LAYER = "ENGRAVE"


def resolve_preset(name: str, **overrides: Any) -> BoardSpec:
    """Resolve a named preset to a ``BoardSpec``, applying any field ``overrides``.

    Raises ``KeyError`` for an unknown preset name.
    """
    if name not in BOARD_PRESETS:
        raise KeyError(f"unknown board preset: {name!r} (have {sorted(BOARD_PRESETS)})")
    if overrides:
        return replace(BOARD_PRESETS[name], **overrides)
    return BOARD_PRESETS[name]


def _quiet_zone_mm(spec: BoardSpec) -> float:
    """Small quiet-zone margin (one square) around the board pattern, in mm."""
    return spec.square_length_mm


def _marker_bit_matrix(dictionary: Any, marker_id: int, marker_size: int) -> Any:
    """Boolean ``(g, g)`` grid (``g = marker_size + 2``) — ``True`` where the bit is BLACK.

    Uses the 1-pixel-per-bit ``generateImageMarker`` trick, so the byte-packing of the
    dictionary never has to be guessed (version-stable across OpenCV 4/5).
    """
    import numpy as np

    grid = marker_size + 2  # borderBits=1 on each side
    img = dictionary.generateImageMarker(int(marker_id), grid, borderBits=1)
    return np.asarray(img) == 0


def _board_geometry(spec: BoardSpec) -> tuple[Any, dict[tuple[int, int], int], int]:
    """Build the canonical cv2 CharucoBoard and read its marker-square map + marker size.

    Returns ``(board, {(col, row): marker_id}, marker_size)``. The marker-square map is read
    from the board's own object points (captured from reality, never invented), so which
    squares are white (carry a marker) and which are solid black comes straight from cv2.
    """
    import cv2.aruco as aruco
    import numpy as np

    if spec.kind != "charuco":
        raise ValueError(f"board_gen only supports charuco boards, got {spec.kind!r}")
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, spec.aruco_dict))
    board = aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y),
        spec.square_length_mm,
        spec.marker_length_mm,
        dictionary,
    )
    object_points = np.asarray(board.getObjPoints())
    ids = np.asarray(board.getIds()).ravel()
    marker_squares: dict[tuple[int, int], int] = {}
    for k in range(len(object_points)):
        cx = float(object_points[k][:, 0].mean())
        cy = float(object_points[k][:, 1].mean())
        col = int(cx // spec.square_length_mm)
        row = int(cy // spec.square_length_mm)
        marker_squares[(col, row)] = int(ids[k])
    return board, marker_squares, int(dictionary.markerSize)


class _Cell:
    """One filled rectangle in mm: (x, y, w, h) plus a class tag for SVG/DXF layering."""

    __slots__ = ("cls", "h", "w", "x", "y")

    def __init__(self, cls: str, x: float, y: float, w: float, h: float) -> None:
        self.cls = cls
        self.x = x
        self.y = y
        self.w = w
        self.h = h


def _filled_cells(spec: BoardSpec, *, engrave_black: bool) -> list[_Cell]:
    """Compute every filled rectangle (in mm, quiet-zone offset applied) for one polarity.

    ``sq``  — solid non-marker (black) squares (only on the black-fill polarity).
    ``bit`` — marker bit cells (black bits at ``True``, white bits at ``False``).
    ``mg``  — the white margin ring around a marker (only on the white-fill polarity).
    """
    board, marker_squares, marker_size = _board_geometry(spec)
    dictionary = board.getDictionary()
    margin = _quiet_zone_mm(spec)
    sq = spec.square_length_mm
    mk = spec.marker_length_mm
    inset = (sq - mk) / 2
    grid = marker_size + 2
    cell = mk / grid

    cells: list[_Cell] = []
    for row in range(spec.squares_y):
        for col in range(spec.squares_x):
            x0 = margin + col * sq
            y0 = margin + row * sq
            marker_id = marker_squares.get((col, row))
            if marker_id is None:
                # non-marker square == solid BLACK; filled only on the black polarity.
                if engrave_black:
                    cells.append(_Cell("sq", x0, y0, sq, sq))
                continue
            # marker square: draw the bit grid; margin ring is white background.
            black_bits = _marker_bit_matrix(dictionary, marker_id, marker_size)
            mx0 = x0 + inset
            my0 = y0 + inset
            for br in range(grid):
                for bc in range(grid):
                    is_black = bool(black_bits[br, bc])
                    if is_black == engrave_black:
                        cells.append(
                            _Cell("bit", mx0 + bc * cell, my0 + br * cell, cell, cell)
                        )
            if not engrave_black and inset > 0:
                # white margin ring around the marker (4 strips): part of the white region.
                cells.append(_Cell("mg", x0, y0, sq, inset))  # top
                cells.append(_Cell("mg", x0, y0 + sq - inset, sq, inset))  # bottom
                cells.append(_Cell("mg", x0, my0, inset, mk))  # left
                cells.append(_Cell("mg", x0 + sq - inset, my0, inset, mk))  # right
    return cells


def _label_text(spec: BoardSpec) -> str:
    """Human-readable spec engraved on the board so a photographed board is self-identifying."""
    return (
        f"{spec.aruco_dict} {spec.squares_x}x{spec.squares_y} "
        f"sq={spec.square_length_mm:g}mm mk={spec.marker_length_mm:g}mm"
    )


def generate_charuco_svg(
    spec: BoardSpec, *, engrave_black: bool = True, label: bool = True, cut_outline: bool = True
) -> str:
    """Render the ChArUco board as a true-vector SVG string at exact mm scale.

    The root ``<svg>`` carries ``width``/``height`` in mm and a ``viewBox`` in mm (so 1 user
    unit == 1 mm); every filled cell is a ``<rect>`` at exact mm. See the module docstring for
    the ``engrave_black`` polarity contract. When ``cut_outline`` (default) a red, stroke-only
    ``<path>`` traces the board's outer rectangle as a CUT contour (kept out of the engrave fills
    so the laser cuts the board free without engraving that line).
    """
    board_w = spec.squares_x * spec.square_length_mm
    board_h = spec.squares_y * spec.square_length_mm
    margin = _quiet_zone_mm(spec)
    total_w = board_w + 2 * margin
    total_h = board_h + 2 * margin

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:g}mm" '
            f'height="{total_h:g}mm" viewBox="0 0 {total_w:g} {total_h:g}">'
        ),
    ]
    for c in _filled_cells(spec, engrave_black=engrave_black):
        parts.append(
            f'<rect class="{c.cls}" x="{c.x:.4f}" y="{c.y:.4f}" '
            f'width="{c.w:.4f}" height="{c.h:.4f}" fill="{_ENGRAVE_COLOR}"/>'
        )
    if label:
        font = min(margin * 0.5, board_w * 0.05) or 3.0
        ty = total_h - margin * 0.3
        parts.append(
            f'<text class="label" x="{margin:.4f}" y="{ty:.4f}" '
            f'font-family="monospace" font-size="{font:g}" fill="{_ENGRAVE_COLOR}">'
            f"{_label_text(spec)}</text>"
        )
    if cut_outline:
        parts.append(
            f'<path class="cut" d="M0 0 H{total_w:g} V{total_h:g} H0 Z" '
            f'fill="none" stroke="{_CUT_COLOR}" stroke-width="{_CUT_STROKE_MM:g}"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def generate_charuco_dxf(
    spec: BoardSpec, *, engrave_black: bool = True, label: bool = True, cut_outline: bool = True
) -> bytes:
    """Render the ChArUco board as a DXF byte string (units = mm) via ``ezdxf``.

    Each filled cell is one closed ``LWPOLYLINE`` on the ``ENGRAVE`` layer; the optional spec
    label is a ``TEXT`` entity. Geometry is identical to :func:`generate_charuco_svg`, so the
    ENGRAVE-layer LWPOLYLINE count equals that SVG's filled-cell count. When ``cut_outline``
    (default) the board's outer rectangle is added as a closed polyline on a separate ``CUT``
    layer (red), so the operator's laser software maps it to the cut operation.
    """
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new()  # type: ignore[attr-defined]  # ezdxf re-exports new() without __all__
    doc.units = units.MM
    doc.layers.add(_ENGRAVE_LAYER, color=7)  # white/black engrave fills
    doc.layers.add(_CUT_LAYER, color=1)  # ACI 1 = red = cut
    msp = doc.modelspace()

    board_w = spec.squares_x * spec.square_length_mm
    board_h = spec.squares_y * spec.square_length_mm
    margin = _quiet_zone_mm(spec)
    total_w = board_w + 2 * margin
    total_h = board_h + 2 * margin

    for c in _filled_cells(spec, engrave_black=engrave_black):
        # DXF y is up; flip so the board reads the same orientation as the SVG (y down).
        y_top = total_h - c.y
        y_bot = total_h - (c.y + c.h)
        msp.add_lwpolyline(
            [
                (c.x, y_bot),
                (c.x + c.w, y_bot),
                (c.x + c.w, y_top),
                (c.x, y_top),
            ],
            close=True,
            dxfattribs={"layer": _ENGRAVE_LAYER},
        )
    if cut_outline:
        msp.add_lwpolyline(
            [(0.0, 0.0), (total_w, 0.0), (total_w, total_h), (0.0, total_h)],
            close=True,
            dxfattribs={"layer": _CUT_LAYER},
        )
    if label:
        font = min(margin * 0.5, board_w * 0.05) or 3.0
        text = msp.add_text(_label_text(spec), height=font, dxfattribs={"layer": _ENGRAVE_LAYER})
        text.set_placement((margin, margin * 0.3))

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
