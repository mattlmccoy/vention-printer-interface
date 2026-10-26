"""Fine-pitch ChArUco preset for the 20 MP science stills (plan Task 15).

The 4x4 board has only 9 chessboard corners - the accurate kind (OpenCV ChArUco tutorial: marker
corners are less accurate). At ~0.026 mm/px a 5 mm square is ~190 px, so a 12x12 board of 5 mm
squares in the same ~60 mm footprint gives 121 chessboard corners and still fits the 98.5 mm
round cut for the build cylinder.
"""

from __future__ import annotations

import cv2
import cv2.aruco as aruco
import numpy as np
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.board_gen import PRESET_CUT_DIAMETER_MM, resolve_preset
from vention_printer_interface.vision.charuco_points import detect_board_points


def test_fine_preset_geometry() -> None:
    s = resolve_preset("fine_20mp")
    assert (s.squares_x, s.squares_y, s.square_length_mm, s.marker_length_mm) == (12, 12, 5.0, 3.75)
    assert s.aruco_dict == "DICT_4X4_100"  # 72 markers: more than DICT_4X4_50 holds
    assert PRESET_CUT_DIAMETER_MM["fine_20mp"] == 98.5


def test_fine_board_generates_with_the_round_cut(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        r = c.get("/api/vision/board", params={"format": "svg", "preset": "fine_20mp"})
        assert r.status_code == 200, r.text
        assert 'width="98.5mm"' in r.text


def test_fine_board_finds_every_chessboard_corner_in_view() -> None:
    s = resolve_preset("fine_20mp")
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_100)
    board = aruco.CharucoBoard((12, 12), 5.0, 3.75, dictionary)
    img = board.generateImage((1200, 1200), marginSize=40)  # 20 px/mm incl. margin
    crop = img[:1000, :]  # bottom rows out of view: 9 full rows of 11 inner corners remain
    pts = detect_board_points(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR), s)
    assert pts is not None
    assert int((pts.kinds == "corner").sum()) == 9 * 11  # vs 9 on the whole 4x4 board
    assert np.isfinite(pts.image_points).all()


# ---- frame-sized board (2026-10-26: at the zoomed setting the view is ~126 x 95 mm; the 64 mm
# board covered ~47% of the width, so one placement left the edges uncalibrated) -------------
def test_frame_preset_fills_the_zoomed_view() -> None:
    s = resolve_preset("frame_zoom")
    assert (s.squares_x, s.squares_y, s.square_length_mm, s.marker_length_mm) == (10, 7, 12.0, 9.0)
    assert s.aruco_dict == "DICT_4X4_50"  # 35 markers
    assert "frame_zoom" not in PRESET_CUT_DIAMETER_MM  # 120 x 84 mm: a square cut, on the substrate
    assert 10 * 12.0 <= 126 and 7 * 12.0 <= 95


def test_frame_board_is_fully_detected() -> None:
    s = resolve_preset("frame_zoom")
    board = aruco.CharucoBoard((10, 7), 12.0, 9.0, aruco.getPredefinedDictionary(aruco.DICT_4X4_50))
    img = board.generateImage((1240, 880), marginSize=20)  # ~10 px/mm
    pts = detect_board_points(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), s)
    assert pts is not None
    assert int((pts.kinds == "corner").sum()) == 9 * 6 and len(pts.markers_px) == 35
