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
import threading
from dataclasses import replace
from typing import Any

from vention_printer_interface.vision.registration import BoardSpec

# Grid bounds for a ChArUco board. cv2 raises SystemError for a board 1 square wide, and the
# process can die later (SIGTRAP on the next cv2 call, observed on OpenCV 5.0.0), so a 1-wide
# grid must be rejected BEFORE cv2 ever sees it. The upper bound caps generation cost.
MIN_SQUARES = 2
MAX_SQUARES = 40
# Auto-pick order: the smallest 4x4 dictionary that holds the board's markers wins.
ARUCO_4X4_FAMILY: tuple[str, ...] = (
    "DICT_4X4_50",
    "DICT_4X4_100",
    "DICT_4X4_250",
    "DICT_4X4_1000",
)
# One generation at a time: concurrent requests (e.g. a preview per keystroke) queue here
# instead of building several boards in parallel and piling up memory.
_GENERATION_LOCK = threading.Lock()


class BoardSpecError(ValueError):
    """A ChArUco board spec that cannot be generated or detected (message is user-facing)."""


def markers_needed(squares_x: int, squares_y: int) -> int:
    """Number of ArUco markers a ``squares_x`` x ``squares_y`` ChArUco board uses (the white
    squares): ``floor(sx * sy / 2)``, matching ``len(cv2.aruco.CharucoBoard(..).getIds())``."""
    return (squares_x * squares_y) // 2


def dict_capacity(dict_name: str) -> int:
    """Marker count of a predefined ``cv2.aruco`` dictionary, read from cv2 itself.

    Raises ``BoardSpecError`` for a name that is not a predefined ``DICT_*`` dictionary.
    """
    import cv2.aruco as aruco

    if not dict_name.startswith("DICT_") or not hasattr(aruco, dict_name):
        raise BoardSpecError(f"unknown aruco dictionary: {dict_name!r}")
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, dict_name))
    return int(dictionary.bytesList.shape[0])


def pick_aruco_dict(squares_x: int, squares_y: int) -> str:
    """Smallest dictionary in :data:`ARUCO_4X4_FAMILY` with enough markers for the grid."""
    needed = markers_needed(squares_x, squares_y)
    for name in ARUCO_4X4_FAMILY:
        if dict_capacity(name) >= needed:
            return name
    raise BoardSpecError(
        f"a {squares_x}x{squares_y} board needs {needed} markers; the largest 4x4 "
        f"dictionary ({ARUCO_4X4_FAMILY[-1]}) has {dict_capacity(ARUCO_4X4_FAMILY[-1])}"
    )


def with_auto_dict(spec: BoardSpec) -> BoardSpec:
    """``spec`` with :func:`pick_aruco_dict`'s dictionary for its grid. A grid outside the
    allowed bounds is returned unchanged, for :func:`validate_charuco_spec` to reject."""
    in_bounds = all(MIN_SQUARES <= n <= MAX_SQUARES for n in (spec.squares_x, spec.squares_y))
    if not in_bounds:
        return spec
    return replace(spec, aruco_dict=pick_aruco_dict(spec.squares_x, spec.squares_y))


def validate_charuco_spec(spec: BoardSpec) -> None:
    """Reject a ChArUco spec that cv2 cannot build or detect. Pure checks, run before any
    cv2 board construction; raises ``BoardSpecError`` with a user-facing message."""
    if spec.kind != "charuco":
        raise BoardSpecError(f"only charuco boards are supported here, got {spec.kind!r}")
    for axis, n in (("squares_x", spec.squares_x), ("squares_y", spec.squares_y)):
        if not (MIN_SQUARES <= n <= MAX_SQUARES):
            raise BoardSpecError(
                f"{axis} must be at least {MIN_SQUARES} and at most {MAX_SQUARES} (got {n})"
            )
    if not (0 < spec.marker_length_mm < spec.square_length_mm):
        raise BoardSpecError("marker size must be > 0 and smaller than the square size")
    capacity = dict_capacity(spec.aruco_dict)
    needed = markers_needed(spec.squares_x, spec.squares_y)
    if capacity < needed:
        raise BoardSpecError(
            f"a {spec.squares_x}x{spec.squares_y} board needs {needed} markers but "
            f"{spec.aruco_dict} has only {capacity}; use "
            f"{pick_aruco_dict(spec.squares_x, spec.squares_y)} or leave the dictionary unset"
        )


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


def _render_charuco_svg(
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


def _render_charuco_dxf(
    spec: BoardSpec, *, engrave_black: bool = True, label: bool = True, cut_outline: bool = True
) -> bytes:
    """Render the ChArUco board as a DXF byte string (units = mm) via ``ezdxf``.

    Each filled cell is one closed ``LWPOLYLINE`` on the ``ENGRAVE`` layer; the optional spec
    label is a ``TEXT`` entity. Geometry is identical to :func:`_render_charuco_svg`, so the
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


def generate_charuco_svg(
    spec: BoardSpec, *, engrave_black: bool = True, label: bool = True, cut_outline: bool = True
) -> str:
    """Validate ``spec`` (see :func:`validate_charuco_spec`), then render it as a true-vector
    SVG (see :func:`_render_charuco_svg`). Generations run one at a time."""
    validate_charuco_spec(spec)
    with _GENERATION_LOCK:
        return _render_charuco_svg(
            spec, engrave_black=engrave_black, label=label, cut_outline=cut_outline
        )


def generate_charuco_dxf(
    spec: BoardSpec, *, engrave_black: bool = True, label: bool = True, cut_outline: bool = True
) -> bytes:
    """Validate ``spec`` (see :func:`validate_charuco_spec`), then render it as a DXF (see
    :func:`_render_charuco_dxf`). Generations run one at a time."""
    validate_charuco_spec(spec)
    with _GENERATION_LOCK:
        return _render_charuco_dxf(
            spec, engrave_black=engrave_black, label=label, cut_outline=cut_outline
        )
