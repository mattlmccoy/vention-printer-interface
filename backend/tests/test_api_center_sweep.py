"""API tests for the camera-center sweep (browser-driven: server holds session + scores frames)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from fastapi.testclient import TestClient  # noqa: E402

from vention_printer_interface.api.app import create_app  # noqa: E402


def _png(cx: int, w: int = 640, h: int = 480, r: int = 120) -> bytes:
    rng = np.random.default_rng(1)
    img = rng.integers(20, 60, size=(h, w, 3)).astype(np.uint8)
    cv2.circle(img, (cx, h // 2), r, (205, 205, 205), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield c


def test_full_sweep_picks_the_centred_pose_and_applies(client: TestClient) -> None:
    # start at pose 6; the bore is centred at pose 10, so the sweep should recommend ~10.
    r = client.post("/api/vision/center-sweep/session",
                    json={"start_mm": 6.0, "span_mm": 4.0, "step_mm": 2.0},
                    headers={"X-VPI-Client": "1"})
    assert r.status_code == 200
    poses = r.json()["poses"]
    assert poses == [2.0, 4.0, 6.0, 8.0, 10.0]

    width = 640
    for pose in poses:
        offset = int(abs(pose - 10.0) * 20)  # 0 px at pose 10, grows away from it
        rr = client.post(f"/api/vision/center-sweep/sample?recoater_mm={pose}",
                         content=_png(cx=width // 2 + offset),
                         headers={"X-VPI-Client": "1", "Content-Type": "image/png"})
        assert rr.status_code == 200, rr.text
        assert rr.json()["found"] is True

    best = client.post("/api/vision/center-sweep/best", headers={"X-VPI-Client": "1"}).json()
    assert abs(best["pose_mm"] - 10.0) < 1.0
    assert best["improved"] is True

    ap = client.post("/api/vision/center-sweep/apply", json={"recoater_mm": best["pose_mm"]},
                     headers={"X-VPI-Client": "1"})
    assert ap.status_code == 200
    assert abs(ap.json()["plan"]["capture_recoater_mm"] - 10.0) < 1.0


def test_status_reports_progress_and_cancel_clears(client: TestClient) -> None:
    client.post("/api/vision/center-sweep/session", json={"start_mm": 6.0, "span_mm": 2.0,
                "step_mm": 2.0}, headers={"X-VPI-Client": "1"})
    st = client.get("/api/vision/center-sweep/session").json()
    assert st["active"] is True and len(st["poses"]) == 3 and st["samples"] == []
    client.post("/api/vision/center-sweep/sample?recoater_mm=6", content=_png(cx=320),
                headers={"X-VPI-Client": "1", "Content-Type": "image/png"})
    assert len(client.get("/api/vision/center-sweep/session").json()["samples"]) == 1
    client.post("/api/vision/center-sweep/cancel", headers={"X-VPI-Client": "1"})
    assert client.get("/api/vision/center-sweep/session").json()["active"] is False


def test_sample_without_session_is_409(client: TestClient) -> None:
    r = client.post("/api/vision/center-sweep/sample?recoater_mm=5", content=_png(cx=320),
                    headers={"X-VPI-Client": "1", "Content-Type": "image/png"})
    assert r.status_code == 409


def test_sample_reports_not_found_on_blank_frame(client: TestClient) -> None:
    client.post("/api/vision/center-sweep/session", json={"start_mm": 6.0, "span_mm": 2.0,
                "step_mm": 2.0}, headers={"X-VPI-Client": "1"})
    blank = cv2.imencode(".png", np.full((480, 640, 3), 40, np.uint8))[1].tobytes()
    r = client.post("/api/vision/center-sweep/sample?recoater_mm=6", content=blank,
                    headers={"X-VPI-Client": "1", "Content-Type": "image/png"})
    assert r.status_code == 200
    assert r.json()["found"] is False and r.json()["offset_px"] is None
