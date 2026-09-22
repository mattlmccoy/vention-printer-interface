"""Piston-bore circle detection (used by the camera-center sweep)."""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vention_printer_interface.vision.circle_detect import (  # noqa: E402
    center_offset_px,
    detect_piston_circle,
)


def _synth(w: int, h: int, cx: int, cy: int, r: int) -> np.ndarray:
    """A bright filled disc (the bore) on a darker textured bed — like the overhead science view."""
    rng = np.random.default_rng(0)
    img = (rng.integers(20, 60, size=(h, w, 3))).astype(np.uint8)  # textured dark bed
    cv2.circle(img, (cx, cy), r, (205, 205, 205), -1)
    return img


def test_detects_a_centered_circle() -> None:
    c = detect_piston_circle(_synth(640, 480, 320, 240, 120))
    assert c is not None
    cx, cy, r = c
    assert abs(cx - 320) < 10 and abs(cy - 240) < 10 and abs(r - 120) < 18


def test_offset_tracks_an_off_centre_circle() -> None:
    # circle 60 px right of the frame centre -> radial offset ~60 px
    off = center_offset_px(_synth(640, 480, 380, 240, 120))
    assert off is not None
    assert abs(off - 60) < 12


def test_none_when_no_circle() -> None:
    flat = np.full((480, 640, 3), 40, np.uint8)
    assert detect_piston_circle(flat) is None
    assert center_offset_px(flat) is None
