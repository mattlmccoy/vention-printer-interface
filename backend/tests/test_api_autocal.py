"""Automatic calibration session routes (api/autocal_routes.py), end to end with real detection.

Photos are crops of ONE cv2-rendered ChArUco board (``CharucoBoard.generateImage``): a camera
translating parallel to a flat board at fixed height sees the image translate exactly, so a crop
offset of Δ mm × px/mm models a recoater move of Δ with zero lens distortion. Spec
docs/superpowers/specs/2026-10-20-auto-calibration-design.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.frame_source import SimulatedFrameSource

PX_PER_MM = 10.0
CAPTURE = 463.3
BOARD = {"kind": "charuco", "squares_x": 4, "squares_y": 4, "square_length_mm": 16.0,
         "marker_length_mm": 12.0, "aruco_dict": "DICT_4X4_50"}
FRAME = (900, 700)


def _canvas() -> np.ndarray:
    import cv2.aruco as aruco

    d = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    board = aruco.CharucoBoard((4, 4), 16.0, 12.0, d)
    img: np.ndarray = board.generateImage((640, 640), marginSize=0)  # 64 mm at 10 px/mm
    canvas = np.full((FRAME[1], 640 + 2 * 600), 255, np.uint8)
    y = (FRAME[1] - 640) // 2
    canvas[y:y + 640, 600:1240] = img
    return canvas


_CANVAS = _canvas()


def _photo(offset_mm: float, size: tuple[int, int] = FRAME) -> bytes:
    # Camera at +offset along the recoater -> the board appears shifted -offset in the photo.
    cx = 600 + 320 + int(round(offset_mm * PX_PER_MM))
    x0 = cx - size[0] // 2
    crop = _CANVAS[(FRAME[1] - size[1]) // 2:(FRAME[1] - size[1]) // 2 + size[1], x0:x0 + size[0]]
    ok, buf = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR))
    assert ok
    return bytes(buf.tobytes())


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0,
                     vision_source=SimulatedFrameSource(width=32, height=24))
    return app


def _set_capture_pose(app, mm: float) -> None:  # type: ignore[no-untyped-def]
    import dataclasses

    app.state.print_settings = dataclasses.replace(app.state.print_settings,
                                                   capture_recoater_mm=mm)


def _start(c: TestClient, **kw: object):  # type: ignore[no-untyped-def]
    body = {"spec": BOARD, "window_min_mm": 0.0, "window_max_mm": 523.0, "step_mm": 5.0,
            "max_offset_mm": 20.0, "placement": "substrate", "board_thickness_mm": 3.175, **kw}
    return c.post("/api/vision/autocal/session", json=body)


def _sweep(c: TestClient, poses: list[float]) -> None:
    for p in poses:
        r = c.post(f"/api/vision/autocal/sample?recoater_mm={p}", content=_photo(p - CAPTURE))
        assert r.status_code == 200, r.text


def test_full_run_passes_and_saves_a_calibration_with_provenance(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        plan = _start(c).json()
        assert plan["poses"][0] > plan["poses"][-1] and CAPTURE in plan["poses"]
        _sweep(c, plan["poses"])
        res = c.post("/api/vision/autocal/solve").json()
        assert res["passed"] is True, res["reasons"]
        assert res["scale_ratio"] == pytest.approx(1.0, abs=0.01)
        assert res["image_size"] == list(FRAME)
        saved = c.post("/api/vision/autocal/save")
        assert saved.status_code == 200, saved.text
        version = saved.json()["calibration_version"]
        assert c.get("/api/vision/status").json()["calibration"] == version
        prov = json.loads((tmp_path / ".vision_calibration.json").read_text())["provenance"]
        assert prov["method"] == "auto-sweep" and prov["placement"] == "substrate"
        assert prov["board_thickness_mm"] == 3.175
        assert "print plane" in prov["plane_note"]
        assert prov["approach"] == "from above (descending mm)"


def test_save_before_a_passing_solve_is_409(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        assert c.post("/api/vision/autocal/save").status_code == 409


def test_sample_rejects_non_finite_position(tmp_path: Path) -> None:  # Review Focus 2
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        r = c.post("/api/vision/autocal/sample?recoater_mm=nan", content=_photo(0.0))
        assert r.status_code == 400


def test_sample_of_another_size_is_refused(tmp_path: Path) -> None:  # Review Focus 4
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        assert c.post(f"/api/vision/autocal/sample?recoater_mm={CAPTURE}",
                      content=_photo(0.0)).json()["usable"] is True
        r = c.post(f"/api/vision/autocal/sample?recoater_mm={CAPTURE - 5}",
                   content=_photo(-5.0, size=(800, 600)))
        # A resolution change FAILS the run (409 + reason), never a silent "board not found".
        assert r.status_code == 409 and "size" in r.json()["detail"]
        assert len(c.get("/api/vision/autocal/session").json()["samples"]) == 1


def test_window_defaults_to_0_523_and_is_remembered(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/vision/autocal/window").json() == {"min_mm": 0.0, "max_mm": 523.0}
        _set_capture_pose(app, 300.0)
        assert _start(c, window_min_mm=100.0, window_max_mm=500.0).status_code == 200
        assert c.get("/api/vision/autocal/window").json() == {"min_mm": 100.0, "max_mm": 500.0}


def test_session_refuses_a_capture_pose_outside_the_window(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, 600.0)
        r = _start(c)
        assert r.status_code == 400 and "capture pose" in r.json()["detail"]


def test_session_refuses_with_no_capture_pose_saved(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, 0.0)
        r = _start(c)
        assert r.status_code == 400 and "capture pose" in r.json()["detail"]
