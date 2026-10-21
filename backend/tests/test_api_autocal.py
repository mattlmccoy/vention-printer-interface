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


def _warped_photo(angle_deg: float, scale: float, shift_px: tuple[float, float]) -> bytes:
    # The board moved (rotated + shifted) or, with scale != 1, a board whose size is wrong.
    img = cv2.imdecode(np.frombuffer(_photo(0.0), np.uint8), cv2.IMREAD_GRAYSCALE)
    m = cv2.getRotationMatrix2D((FRAME[0] / 2, FRAME[1] / 2), angle_deg, scale)
    m[:, 2] += shift_px
    out = cv2.warpAffine(img, m, FRAME, flags=cv2.INTER_CUBIC, borderValue=255)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(out, cv2.COLOR_GRAY2BGR))
    assert ok
    return bytes(buf.tobytes())


def _moved_photo() -> bytes:
    return _warped_photo(20.0, 1.0, (40.0, 15.0))


def _solved(c: TestClient, app) -> None:  # type: ignore[no-untyped-def]
    _set_capture_pose(app, CAPTURE)
    _sweep(c, _start(c).json()["poses"])
    res = c.post("/api/vision/autocal/solve").json()
    assert res["passed"] is True, res["reasons"]


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
        assert c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).json()["passed"]
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


def test_sample_counts_corners_and_marker_points(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        r = c.post(f"/api/vision/autocal/sample?recoater_mm={CAPTURE}", content=_photo(0.0)).json()
        assert r["corners"] == 41 and r["chessboard_corners"] == 9 and r["marker_points"] == 32
        assert len(r["corners_px"]) == 41


def test_save_requires_a_passing_self_check(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        r = c.post("/api/vision/autocal/save")
        assert r.status_code == 409 and "self-check" in r.json()["detail"]
        sc = c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).json()
        assert sc["passed"] is True, sc["reasons"]
        assert sc["moved"] is True and sc["n_used"] >= 12
        assert sc["rms_mm"] <= 0.05
        assert c.post("/api/vision/autocal/save").status_code == 200


def test_failed_self_check_keeps_save_closed(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        sc = c.post("/api/vision/autocal/selfcheck",
                    content=_warped_photo(10.0, 1.03, (0.0, 0.0))).json()
        assert sc["passed"] is False and sc["scale_bias"] == pytest.approx(1.03, abs=0.005)
        assert c.post("/api/vision/autocal/save").status_code == 409


def test_new_solve_clears_the_self_check(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        assert c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).json()["passed"]
        assert c.post("/api/vision/autocal/solve").json()["passed"] is True
        assert c.post("/api/vision/autocal/save").status_code == 409


def test_self_check_is_stored_in_provenance(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        c.post("/api/vision/autocal/selfcheck", content=_moved_photo())
        assert c.post("/api/vision/autocal/save").status_code == 200
        prov = json.loads((tmp_path / ".vision_calibration.json").read_text())["provenance"]
        assert prov["self_check"]["passed"] is True and prov["self_check"]["n_used"] >= 12
        assert prov["self_check"]["moved"] is True


def test_self_check_before_a_solve_is_409(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        assert c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).status_code == 409


def test_self_check_of_another_photo_size_is_refused(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        r = c.post("/api/vision/autocal/selfcheck", content=_photo(0.0, size=(800, 600)))
        assert r.status_code == 409 and "size" in r.json()["detail"]


def test_solve_saves_the_sweep_points_for_diagnosis(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        poses = _start(c).json()["poses"]
        _sweep(c, poses)
        res = c.post("/api/vision/autocal/solve").json()
        assert res["reprojection_rms_mm"] == pytest.approx(
            res["reprojection_rms_px"] * res["px_mm"], rel=1e-6)
        assert res["reprojection_limit_mm"] == 0.05
        assert set(res["residuals"]) >= {"corner", "marker", "centre", "middle", "edge"}
        saved = json.loads((tmp_path / ".autocal_last_sweep.json").read_text())
        assert saved["image_size"] == list(FRAME) and saved["capture_mm"] == CAPTURE
        assert len(saved["views"]) == len(poses)
        v = saved["views"][0]
        assert len(v["image_points"]) == len(v["object_points"]) == len(v["ids"])
        assert saved["result"]["passed"] is True


# ---- analysis in the tool (plan Tasks 11-12): the panel shows what was diagnosed by hand --------
def test_solve_reports_limits_and_per_view_counts(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        poses = _start(c).json()["poses"]
        _sweep(c, poses)
        res = c.post("/api/vision/autocal/solve").json()
        assert res["limits"] == {"min_views": 5, "reprojection_mm": 0.05, "shift_rms_mm": 0.1}
        assert len(res["views"]) == len(poses)
        for v in res["views"]:
            assert v["points"] == v["chessboard"] + v["markers"]
        cap = min(res["views"], key=lambda v: abs(v["recoater_mm"] - CAPTURE))
        assert (cap["points"], cap["chessboard"], cap["markers"]) == (41, 9, 32)


def test_last_report_round_trips_and_is_404_before_any_solve(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/vision/autocal/last").status_code == 404
        _solved(c, app)
        r = c.get("/api/vision/autocal/last")
        assert r.status_code == 200, r.text
        last = r.json()
        assert last["result"]["passed"] is True and last["image_size"] == list(FRAME)
        assert last["views"][0]["points"] == len(last["views"][0]["image_points"])
        assert "saved_at" in last


def test_solve_includes_the_calibration_in_use(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        assert c.post("/api/vision/autocal/solve").json()["current"] is None  # none saved yet
        c.post("/api/vision/autocal/selfcheck", content=_moved_photo())
        version = c.post("/api/vision/autocal/save").json()["calibration_version"]
        _solved(c, app)  # a second run, compared against the first
        cur = c.post("/api/vision/autocal/solve").json()["current"]
        assert cur["version"] == version and cur["image_size"] == list(FRAME)
        assert cur["method"] == "auto-sweep"
        assert cur["shift_rms_mm"] < 0.1 and cur["reprojection_rms_mm"] is not None
        assert len(cur["area_mm"]) == 2


# ---- overlays on the active image (plan Tasks 7 + 9) ------------------------------------------
_BOARD_Q = {"squares_x": 4, "squares_y": 4, "square_mm": 16.0, "marker_mm": 12.0,
            "dict": "DICT_4X4_50"}


def test_preview_returns_identified_points_without_a_session(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as c:
        r = c.post("/api/vision/autocal/preview", params=_BOARD_Q, content=_photo(0.0))
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["found"] is True and out["image_size"] == list(FRAME)
        kinds = [p["kind"] for p in out["points"]]
        assert kinds.count("corner") == 9 and kinds.count("marker") == 32
        assert len(out["markers"]) == 8 and all(len(m) == 4 for m in out["markers"])


def test_preview_with_no_board_says_not_found(tmp_path: Path) -> None:
    blank = np.full((300, 400, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", blank)
    with TestClient(_app(tmp_path)) as c:
        out = c.post("/api/vision/autocal/preview", params=_BOARD_Q,
                     content=bytes(buf.tobytes())).json()
        assert out["found"] is False and out["points"] == [] and out["markers"] == []


def test_overlay_before_solve_is_409(tmp_path: Path) -> None:  # Review Focus 5
    app = _app(tmp_path)
    with TestClient(app) as c:
        _set_capture_pose(app, CAPTURE)
        _start(c)
        for view in ("raw", "corrected"):
            assert c.get(f"/api/vision/autocal/overlay.png?view={view}").status_code == 409


def test_overlay_returns_png_of_expected_size(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        res = c.post("/api/vision/autocal/solve").json()
        raw = c.get("/api/vision/autocal/overlay.png?view=raw")
        assert raw.status_code == 200 and raw.headers["content-type"] == "image/png"
        img = cv2.imdecode(np.frombuffer(raw.content, np.uint8), cv2.IMREAD_COLOR)
        assert (img.shape[1], img.shape[0]) == FRAME
        cor = c.get("/api/vision/autocal/overlay.png?view=corrected")
        assert cor.status_code == 200
        img = cv2.imdecode(np.frombuffer(cor.content, np.uint8), cv2.IMREAD_COLOR)
        x0, y0, x1, y1 = res["bed_extent_mm"]
        mpp = res["mm_per_px"]
        assert (img.shape[1], img.shape[0]) == (round((x1 - x0) / mpp), round((y1 - y0) / mpp))


# ---- residual arrows (plan Task 13) --------------------------------------------------------
def test_last_report_includes_residual_arrows(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        last = c.get("/api/vision/autocal/last").json()
        for v in last["views"]:
            assert len(v["residuals_px"]) == len(v["image_points"])
            assert all(len(r) == 2 for r in v["residuals_px"])


def test_residual_overlay_png(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        _solved(c, app)
        r = c.get("/api/vision/autocal/overlay.png?view=residuals")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        assert (img.shape[1], img.shape[0]) == FRAME
