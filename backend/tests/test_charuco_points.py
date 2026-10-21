"""Every identified ChArUco point, chessboard AND marker corners (vision/charuco_points.py).

Spec docs/superpowers/specs/2026-10-21-charuco-full-calibration-design.md §1/§3.1: the first real
run used only the 9 interior chessboard corners (16–48 mm of the 64 mm pattern); each marker's 4
corners have known board positions too (32 more, spanning 2–62 mm). Fixtures are cv2-rendered.
"""

from __future__ import annotations

import numpy as np

from vention_printer_interface.vision.charuco_points import MARKER_ID_BASE, detect_board_points
from vention_printer_interface.vision.registration import BoardSpec

SPEC = BoardSpec(kind="charuco", squares_x=4, squares_y=4, square_length_mm=16.0,
                 marker_length_mm=12.0, aruco_dict="DICT_4X4_50")
MARGIN_PX, PX_PER_MM = 40, 10.0


def _board_image() -> np.ndarray:
    import cv2.aruco as aruco

    d = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    board = aruco.CharucoBoard((4, 4), 16.0, 12.0, d)
    img: np.ndarray = board.generateImage((640 + 2 * MARGIN_PX, 640 + 2 * MARGIN_PX),
                                          marginSize=MARGIN_PX)
    return img


IMG = _board_image()


def test_full_board_gives_9_corners_and_32_marker_points() -> None:
    p = detect_board_points(IMG, SPEC)
    assert p is not None
    assert len(p.image_points) == 41
    assert len(set(p.ids.ravel().tolist())) == 41
    assert int((p.kinds == "corner").sum()) == 9 and int((p.kinds == "marker").sum()) == 32


def test_points_land_where_the_board_says() -> None:
    p = detect_board_points(IMG, SPEC)
    assert p is not None
    # cv2 reports a square's corner at the pixel-centre boundary, a constant -0.5 px offset from
    # (margin + 10 px/mm * board mm) for BOTH kinds; the marker corners must agree with the
    # chessboard corners to within 0.1 px once that common offset is removed.
    expected = MARGIN_PX + PX_PER_MM * p.object_points[:, :2] - 0.5
    assert float(np.abs(p.image_points - expected).max()) <= 0.1


def test_marker_corner_ids_encode_marker_and_corner() -> None:
    p = detect_board_points(IMG, SPEC)
    assert p is not None
    i = int(np.where(p.ids.ravel() == MARKER_ID_BASE + 4 * 0 + 0)[0][0])
    assert p.object_points[i, :2].tolist() == [18.0, 2.0]


def test_half_board_still_identified() -> None:
    full = detect_board_points(IMG, SPEC)
    half = detect_board_points(IMG[:, 360:].copy(), SPEC)
    assert full is not None and half is not None
    assert int((half.kinds == "marker").sum()) >= 16
    assert set(half.ids.ravel().tolist()) <= set(full.ids.ravel().tolist())


def test_marker_only_view_is_used() -> None:  # Review Focus 1
    # Only the top row of squares (one marker, no interior chessboard corner) is visible.
    crop = IMG[: MARGIN_PX + 15 * int(PX_PER_MM)].copy()
    p = detect_board_points(crop, SPEC)
    assert p is not None
    assert int((p.kinds == "corner").sum()) == 0 and int((p.kinds == "marker").sum()) >= 4


def test_blank_image_is_none() -> None:
    assert detect_board_points(np.full((400, 400), 255, np.uint8), SPEC) is None
