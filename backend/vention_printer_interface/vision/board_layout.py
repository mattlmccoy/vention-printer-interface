"""Where everything on an engraved calibration board goes: pattern origin, scale bar, text, cut.

Two cut shapes:

* **rectangle** (default): the pattern plus a one-square quiet zone on every side; the scale bar
  and its length sit in the top margin, the spec label in the bottom margin.
* **circle** (``cut_diameter_mm``): for a board that must drop into a round build cylinder. The
  small 4x4 board was cut as a 96 mm square (135.8 mm across the corners) and could not go into
  the Ø100 mm cylinder (2026-10-20). The pattern is centred in the circle; the scale bar goes in
  the curved gap above it and the label (which then also names the bar length) in the gap below,
  each placed only where it stays ``CLEARANCE_MM`` inside the cut.

All coordinates are mm, y down (SVG convention); the DXF writer flips y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from vention_printer_interface.vision.registration import BoardSpec

Rect = tuple[float, float, float, float]

# Everything engraved stays this far inside a circular cut (laser kerf + handling).
CLEARANCE_MM = 1.0
# Caliper check: a bar of a round length, so a finished board's true scale can be measured (a laser
# job imported at the wrong DPI comes out x0.75 or x1.33). The longest one that fits is used.
_SCALE_LENGTHS_MM = (100.0, 50.0, 20.0, 10.0)
_SCALE_TICK_MM = 10.0
_MONO_ADVANCE = 0.6  # monospace character advance, in em
_CIRCLE_FONTS_MM = (4.0, 3.5, 3.0, 2.5, 2.0, 1.5)


class BoardLayoutError(ValueError):
    """The board cannot be laid out in the requested cut (message is user-facing)."""


@dataclass(frozen=True)
class TextItem:
    cls: str
    text: str
    x: float
    baseline_y: float
    font_mm: float
    anchor: str = "start"  # "start" | "middle"


@dataclass(frozen=True)
class Layout:
    total_w: float
    total_h: float
    origin: tuple[float, float]  # top-left of the square pattern
    scale_length_mm: float | None = None
    scale_rects: list[Rect] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    circle: tuple[float, float, float] | None = None  # (cx, cy, r); None = rectangular cut


def label_text(spec: BoardSpec) -> str:
    """Human-readable spec engraved on the board so a photographed board is self-identifying."""
    return (
        f"{spec.aruco_dict} {spec.squares_x}x{spec.squares_y} "
        f"sq={spec.square_length_mm:g}mm mk={spec.marker_length_mm:g}mm"
    )


def _bar_rects(x0: float, y0: float, length: float, unit: float) -> list[Rect]:
    """Bar + end ticks (inside the outer edges, so calipers across them read ``length``) + 10 mm
    ticks. All touch, so they merge into one engraved shape. Sizes scale with ``unit`` (the
    square length): 0.04 thick, end ticks 0.24 deep, minor ticks 0.12 deep."""
    t = unit * 0.04
    rects: list[Rect] = [(x0, y0, length, t), (x0, y0, t, unit * 0.24)]
    rects.append((x0 + length - t, y0, t, unit * 0.24))
    k = 1
    while k * _SCALE_TICK_MM < length - 1e-9:
        rects.append((x0 + k * _SCALE_TICK_MM - t / 2, y0, t, unit * 0.12))
        k += 1
    return rects


def _rect_layout(spec: BoardSpec, *, scale_bar: bool, label: bool) -> Layout:
    board_w = spec.squares_x * spec.square_length_mm
    board_h = spec.squares_y * spec.square_length_mm
    margin = spec.square_length_mm  # one-square quiet zone
    total_w, total_h = board_w + 2 * margin, board_h + 2 * margin
    texts: list[TextItem] = []
    length: float | None = None
    rects: list[Rect] = []
    fits = [n for n in _SCALE_LENGTHS_MM if n <= board_w]
    if scale_bar and fits:
        length = fits[0]
        rects = _bar_rects(margin, margin * 0.3, length, margin)
        texts.append(TextItem("scale", f"{length:g} mm", margin + length + margin * 0.15,
                              margin * 0.52, margin * 0.25))
    if label:
        font = min(margin * 0.5, board_w * 0.05) or 3.0
        texts.append(TextItem("label", label_text(spec), margin, total_h - margin * 0.3, font))
    return Layout(total_w, total_h, (margin, margin), length, rects, texts)


def _circle_layout(
    spec: BoardSpec, diameter: float, *, scale_bar: bool, label: bool
) -> Layout:
    board_w = spec.squares_x * spec.square_length_mm
    board_h = spec.squares_y * spec.square_length_mm
    r = diameter / 2
    c = r
    reach = r - CLEARANCE_MM
    needed = math.hypot(board_w, board_h) + 2 * CLEARANCE_MM
    if needed > diameter + 1e-9:
        raise BoardLayoutError(
            f"a {diameter:g} mm circle is too small for the {board_w:g}x{board_h:g} mm pattern: "
            f"its corners need a {needed:.1f} mm circle (smaller squares, or a bigger circle)"
        )
    ox, oy = c - board_w / 2, c - board_h / 2
    unit = spec.square_length_mm
    gap = max(1.5, unit * 0.1)  # white space kept between the pattern and the bar / label

    length: float | None = None
    rects: list[Rect] = []
    if scale_bar:
        for n in (v for v in _SCALE_LENGTHS_MM if v <= board_w and v / 2 < reach):
            y_top = c - math.sqrt(reach**2 - (n / 2) ** 2)  # outer corners touch the clearance
            if y_top + unit * 0.24 <= oy - gap:
                length = n
                rects = _bar_rects(c - n / 2, y_top, n, unit)
                break

    texts: list[TextItem] = []
    if label:
        text = label_text(spec) + (f" bar={length:g}mm" if length is not None else "")
        for font in (f for f in _CIRCLE_FONTS_MM if f <= unit * 0.25):
            half_w = len(text) * _MONO_ADVANCE * font / 2
            baseline = oy + board_h + gap + font
            if math.hypot(half_w, baseline - c) <= reach:
                texts.append(TextItem("label", text, c, baseline, font, anchor="middle"))
                break
    return Layout(diameter, diameter, (ox, oy), length, rects, texts, circle=(c, c, r))


def board_layout(
    spec: BoardSpec,
    *,
    cut_diameter_mm: float | None = None,
    scale_bar: bool = True,
    label: bool = True,
) -> Layout:
    """Lay out ``spec``: a rectangular cut, or a circle when ``cut_diameter_mm`` is set (> 0)."""
    if cut_diameter_mm is None or cut_diameter_mm == 0:
        return _rect_layout(spec, scale_bar=scale_bar, label=label)
    if not (math.isfinite(cut_diameter_mm) and cut_diameter_mm > 0):
        raise BoardLayoutError(f"cut diameter must be a positive number (got {cut_diameter_mm:g})")
    return _circle_layout(spec, cut_diameter_mm, scale_bar=scale_bar, label=label)
