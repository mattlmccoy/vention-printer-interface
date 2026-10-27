"""Automatic calibration on a certified chessboard (api/autocal_routes.py, board kind
"checkerboard"). Same harness as test_api_autocal.py: a rendered board, cropped as the camera
sweeps (10 px/mm). The plate here is 10 x 10 squares of 4.5 mm (45 mm), so it fills the 900 px
photo near the capture pose and runs off it at the ends of a +-30 mm sweep, as the real
DEvision plate does.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.test_api_autocal import CAPTURE, FRAME, PX_PER_MM, _app, _set_capture_pose

PLATE = {"kind": "checkerboard", "cols": 9, "rows": 9, "square_size_mm": 4.5}
SQ = int(4.5 * PX_PER_MM)  # 45 px


def _canvas() -> np.ndarray:
    board = np.full((10 * SQ, 10 * SQ), 255, np.uint8)
    for r in range(10):
        for c in range(10):
            if (r + c) % 2 == 0:
                board[r * SQ:(r + 1) * SQ, c * SQ:(c + 1) * SQ] = 0
    canvas = np.full((FRAME[1] + 400, 10 * SQ + 2 * 800), 255, np.uint8)
    y = (canvas.shape[0] - 10 * SQ) // 2
    canvas[y:y + 10 * SQ, 800:800 + 10 * SQ] = board
    return canvas


_CANVAS = _canvas()


def _photo(offset_mm: float) -> bytes:
    cx = 800 + 5 * SQ + int(round(offset_mm * PX_PER_MM))
    x0, y0 = cx - FRAME[0] // 2, (_CANVAS.shape[0] - FRAME[1]) // 2
    crop = _CANVAS[y0:y0 + FRAME[1], x0:x0 + FRAME[0]]
    ok, buf = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR))
    assert ok
    return bytes(buf.tobytes())


def _moved_photo() -> bytes:
    img = cv2.imdecode(np.frombuffer(_photo(0.0), np.uint8), cv2.IMREAD_GRAYSCALE)
    m = cv2.getRotationMatrix2D((FRAME[0] / 2, FRAME[1] / 2), 15.0, 1.0)
    m[:, 2] += (30.0, 10.0)
    out = cv2.warpAffine(img, m, FRAME, flags=cv2.INTER_CUBIC, borderValue=255)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(out, cv2.COLOR_GRAY2BGR))
    assert ok
    return bytes(buf.tobytes())


def _start(c: TestClient):  # type: ignore[no-untyped-def]
    return c.post("/api/vision/autocal/session", json={
        "spec": PLATE, "window_min_mm": 0.0, "window_max_mm": 523.0, "step_mm": 5.0,
        "max_offset_mm": 30.0, "placement": "substrate", "board_thickness_mm": 1.0})


def _solved(c: TestClient, app) -> dict:  # type: ignore[no-untyped-def,type-arg]
    _set_capture_pose(app, CAPTURE)
    start = _start(c)
    assert start.status_code == 200, start.text
    for p in start.json()["poses"]:
        r = c.post(f"/api/vision/autocal/sample?recoater_mm={p}", content=_photo(p - CAPTURE))
        assert r.status_code == 200, r.text
    res = c.post("/api/vision/autocal/solve")
    assert res.status_code == 200, res.text
    return res.json()  # type: ignore[no-any-return]


def test_a_plate_run_solves_on_the_plates_own_mm(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        res = _solved(c, app)
        assert res["passed"] is True, res["reasons"]
        assert res["scale_reference"] == "board"
        assert res["scale_ratio"] == pytest.approx(1.0, abs=0.01)
        assert res["dropped_views"] == []
        assert min(v["points"] for v in res["views"]) < 81 <= max(v["points"] for v in res["views"])


def test_a_plate_run_self_checks_and_saves_with_its_board(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        sc = c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).json()
        assert sc["passed"] is True, sc["reasons"]
        assert sc["scale_bias"] == pytest.approx(1.0, abs=0.005)
        assert c.post("/api/vision/autocal/save").status_code == 200
        prov = json.loads((tmp_path / ".vision_calibration.json").read_text())["provenance"]
        assert prov["board"]["kind"] == "checkerboard" and prov["scale_reference"] == "board"
        assert prov["board_thickness_mm"] == 1.0


def test_a_plate_run_draws_its_overlay(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        r = c.get("/api/vision/autocal/overlay.png?view=raw")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_a_plate_session_refuses_a_board_without_its_size(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        r = c.post("/api/vision/autocal/session", json={
            "spec": {"kind": "checkerboard", "cols": 9, "rows": 9, "square_size_mm": 0},
            "window_min_mm": 0.0, "window_max_mm": 523.0, "placement": "substrate"})
        assert r.status_code == 400 and "square" in r.json()["detail"]
