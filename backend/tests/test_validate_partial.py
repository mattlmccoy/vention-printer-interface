"""Certified-chessboard validation with a PARTLY visible board, scored inside the calibrated area.

Spec docs/superpowers/specs/2026-10-21-charuco-full-calibration-design.md §3. The certified board
(17x17 inner corners, 81 mm) does not fit the science camera's ~74 mm field of view, so the classic
fixed-count ``findChessboardCorners((17, 17))`` never finds it and every validation 400'd.
``findChessboardCornersSBWithMeta`` with ``CALIB_CB_LARGER`` accepts the visible part. Only corners
inside the calibration's ``valid_region_mm`` are scored. Boards are cv2-free renders of exact
squares (ground truth by construction).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.registration import (
    Calibration,
    detect_chessboard_partial,
    save_calibration,
)

SQ_PX = 30  # 15 mm pitch at the calibration's 0.5 mm/px
PITCH_MM = 15.0
FRAME = (400, 300)
H = np.array([[0.5, 0.0, 500.0], [0.0, 0.5, 300.0], [0.0, 0.0, 1.0]])  # bed = 500 + px/2, ...


def _board(n_squares: int = 18, sq: int = SQ_PX, margin: int = 40) -> np.ndarray:
    side = n_squares * sq + 2 * margin
    img = np.full((side, side), 255, np.uint8)
    for r in range(n_squares):
        for c in range(n_squares):
            if (r + c) % 2 == 0:
                y, x = margin + r * sq, margin + c * sq
                img[y:y + sq, x:x + sq] = 0
    return img


def _crop() -> np.ndarray:
    return _board()[150:150 + FRAME[1], 120:120 + FRAME[0]]  # well inside: a partial view


def _png(gray: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    assert ok
    return bytes(buf.tobytes())


def _save_calib(root: Path, region: list[tuple[float, float]] | None) -> None:
    prov = {"method": "auto-sweep"} if region is None else {
        "method": "auto-sweep", "valid_region_mm": [list(p) for p in region]}
    save_calibration(root / ".vision_calibration.json", Calibration(
        H=H, mm_per_px=0.5, bed_extent_mm=(500.0, 300.0, 700.0, 450.0), version="cal-partial",
        reprojection_error=0.0,
        camera_matrix=np.array([[1000.0, 0, FRAME[0] / 2], [0, 1000.0, FRAME[1] / 2], [0, 0, 1]]),
        dist_coeffs=np.zeros(5), distortion_model="opencv-5", image_size=FRAME,
        provenance=prov))


def _client(root: Path) -> TestClient:
    return TestClient(create_app(backend="none", experiments_root=root, poll_interval_s=0.05,
                                 print_min_wait_s=0.1, print_step_timeout_s=5.0))


Q = {"square_size_mm": PITCH_MM, "certified_mm": PITCH_MM}
WHOLE = [(490.0, 290.0), (710.0, 290.0), (710.0, 460.0), (490.0, 460.0)]


def test_partial_chessboard_is_found_where_the_classic_detector_fails() -> None:
    crop = _board(sq=20)[100:300, 30:330]
    assert not cv2.findChessboardCorners(crop, (17, 17))[0]
    found = detect_chessboard_partial(crop)
    assert found is not None
    pts, grid = found
    assert len(pts) >= 100 and grid.shape == pts.shape
    # neighbouring grid cells are one square apart in the photo (20 px)
    i = int(np.flatnonzero((grid[:, 0] == 0) & (grid[:, 1] == 0))[0])
    j = int(np.flatnonzero((grid[:, 0] == 1) & (grid[:, 1] == 0))[0])
    assert abs(float(np.linalg.norm(pts[j] - pts[i])) - 20.0) < 0.2


def test_validation_scores_a_partly_visible_board(tmp_path: Path) -> None:
    _save_calib(tmp_path, WHOLE)
    with _client(tmp_path) as c:
        r = c.post("/api/vision/validate/scale-upload", params=Q, content=_png(_crop()))
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["n_points"] >= 60 and out["n_outside"] == 0 and out["area_known"] is True
        assert out["rms_mm"] < 0.02 and abs(out["scale_bias"] - 1.0) < 0.002


def test_points_outside_the_calibrated_area_are_not_scored(tmp_path: Path) -> None:
    left_half = [(490.0, 290.0), (600.0, 290.0), (600.0, 460.0), (490.0, 460.0)]
    _save_calib(tmp_path, left_half)
    with _client(tmp_path) as c:
        out = c.post("/api/vision/validate/scale-upload", params=Q, content=_png(_crop())).json()
        assert out["n_outside"] > 0 and out["n_points"] > 0
        assert len(out["per_point"]) == out["n_points"]


def test_validation_with_no_points_in_area_is_refused(tmp_path: Path) -> None:
    # Review Focus 3: never a pass on 0 points.
    far = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    _save_calib(tmp_path, far)
    with _client(tmp_path) as c:
        r = c.post("/api/vision/validate/scale-upload", params=Q, content=_png(_crop()))
        assert r.status_code == 400
        assert "no chessboard corners inside the calibrated area" in r.json()["detail"]


def test_legacy_calibration_scores_without_area_filter(tmp_path: Path) -> None:
    # Review Focus 4: an older calibration has no valid_region_mm.
    _save_calib(tmp_path, None)
    with _client(tmp_path) as c:
        r = c.post("/api/vision/validate/scale-upload", params=Q, content=_png(_crop()))
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["area_known"] is False and out["n_outside"] == 0
        assert "calibrated area unknown (older calibration)" in out["area_note"]


def test_a_mirrored_grid_numbering_still_scores(tmp_path: Path) -> None:
    # A calibration whose bed frame is mirrored relative to the photo (H with det < 0): the
    # detector's grid numbering must be matched in handedness before the rigid fit.
    mirror = np.array([[-0.5, 0.0, 700.0], [0.0, 0.5, 300.0], [0.0, 0.0, 1.0]])
    save_calibration(tmp_path / ".vision_calibration.json", Calibration(
        H=mirror, mm_per_px=0.5, bed_extent_mm=(500.0, 300.0, 700.0, 450.0), version="cal-mirror",
        reprojection_error=0.0,
        camera_matrix=np.array([[1000.0, 0, FRAME[0] / 2], [0, 1000.0, FRAME[1] / 2], [0, 0, 1]]),
        dist_coeffs=np.zeros(5), distortion_model="opencv-5", image_size=FRAME,
        provenance={"valid_region_mm": [list(p) for p in WHOLE]}))
    with _client(tmp_path) as c:
        out = c.post("/api/vision/validate/scale-upload", params=Q, content=_png(_crop())).json()
        assert out["rms_mm"] < 0.02, out
