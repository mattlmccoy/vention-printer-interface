"""API tests for /api/vision/* (Task 12/13, spec §... layerwise vision Phase 6b).

Mirrors ``test_api_priming.py``'s fixture style. A ``SimulatedFrameSource`` is injected via
``create_app(..., vision_source=...)`` so nothing here opens a real camera.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.frame_source import Frame, FrameSource, SimulatedFrameSource
from vention_printer_interface.vision.registration import (
    Calibration,
    apply_homography,
    load_calibration,
    register_frame,
    save_calibration,
)


class _FailingSource(FrameSource):
    """Stands in for a missing/broken camera: open() always raises."""

    def open(self) -> None:
        raise RuntimeError("no camera attached")

    def close(self) -> None:
        pass

    def grab(self) -> None:  # pragma: no cover - never reached
        raise RuntimeError("no camera attached")


class _CountingGrabSource(FrameSource):
    """Records how many times grab() was called; never raises.

    Used with the OverviewStreamer's background grabber thread, which runs continuously
    (unlike a per-request generator, it does not stop on its own) -- so tests that inject
    this source poll `calls` with a bounded deadline instead of driving the stream endpoint
    to exhaustion via TestClient (Starlette's in-process TestClient fully drains a streaming
    response before returning control to the test, so a never-ending generator would hang it;
    see the stream-header tests below, which stop the streamer before issuing the request).
    """

    def __init__(self) -> None:
        self.calls = 0

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        self.calls += 1
        return Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), timestamp_ns=self.calls)


class _TrackingSource(FrameSource):
    """Records open()/close()/grab() calls and reports whether it is currently open.

    The camera-on-demand fix is proven at the API level with this hardware-free double: no
    open() at startup, open only on actual use, close on release/deactivate.
    """

    def __init__(self) -> None:
        self.open_count = 0
        self.close_count = 0
        self.grab_count = 0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self.open_count += 1
        self._open = True

    def close(self) -> None:
        self.close_count += 1
        self._open = False

    def grab(self) -> Frame:
        self.grab_count += 1
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        image[:, 4:] = 255
        return Frame(image=image, timestamp_ns=self.grab_count)


def _wait_until(predicate: Any, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def app_and_client(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=SimulatedFrameSource(width=32, height=24),
    )
    with TestClient(app) as c:
        yield app, c


@pytest.fixture
def client(app_and_client: tuple[FastAPI, TestClient]) -> TestClient:
    return app_and_client[1]


def test_vision_status_active_with_injected_source(client: TestClient) -> None:
    r = client.get("/api/vision/status")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["calibration"] is None
    assert body["queue"] == {"drops": 0}
    # `cameras` now reports roles that are WIRED UP (constructed), not ones currently
    # streaming -- on-demand access means the device is only opened on use. Science is
    # injected here, so it must be listed.
    assert "science" in body["cameras"]


def test_no_camera_opened_at_startup(tmp_path: Path) -> None:
    """The core of the fix: create_app() may construct the streamer + VisionService, but
    must NOT open any FrameSource at startup (no camera light on at boot)."""
    science = _TrackingSource()
    overview = _TrackingSource()
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=science,
        overview_source=overview,
    )
    with TestClient(app):
        # Let any startup work settle, then assert neither device was ever opened.
        time.sleep(0.15)
        assert science.open_count == 0
        assert not science.is_open
        assert overview.open_count == 0
        assert not overview.is_open


def test_unresolved_roles_open_no_camera_not_the_default_index(tmp_path: Path) -> None:
    """Regression (2026-09-16): with only a NON-assignable camera present (built-in FaceTime /
    iPhone), overview + science are unresolved — and the app must NOT fall back to opening the
    default index-0/1 spec (which streamed the FaceTime into the overview panel despite "no cameras
    detected"). No source injected here, so if the fallback survived, open_overview would build a
    real UvcFrameSource and the streamer would be constructed; the fix opens nothing."""
    def only_facetime() -> list[dict[str, Any]]:
        return [{"index": 0, "stable_id": "macos-uid:facetime-uuid", "name": "FaceTime HD Camera",
                 "vid_pid": None, "assignable": False, "has_frame": None, "probed": False}]

    app = create_app(
        backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
        device_enumerator=only_facetime,
    )
    with TestClient(app) as c:
        assert c.get("/api/vision/devices").json()["devices"] == []  # nothing shown
        assert app.state.overview_streamer is None  # overview unresolved -> opened nothing
        assert app.state.vision is None  # science unresolved -> no capture service on a default cam


def test_startup_does_not_crash_with_a_failing_source_and_degrades_gracefully(
    tmp_path: Path,
) -> None:
    """A camera that fails to open must never block/crash app startup. Under on-demand access
    nothing opens at boot, so startup is trivially fine; the failure now surfaces (gracefully)
    only at use time -- a capture event must be swallowed, not crash the worker."""
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=_FailingSource(),
        overview_source=_FailingSource(),
    )
    with TestClient(app) as c:
        r = c.get("/api/vision/status")
        assert r.status_code == 200
        # Fire a capture: opening the failing source must be caught by the worker, not crash.
        c.post("/api/recording/start", json={"name": "degrade-e2e"})
        app.state.events.append("capture:post_jet", {"layer": 1})
        app.state.vision.drain(timeout=2.0)
        assert c.get("/api/vision/status").status_code == 200  # still serving
        c.post("/api/recording/stop")


def test_deactivate_releases_all_sources_and_status_reports_inactive(tmp_path: Path) -> None:
    """POST /api/vision/deactivate force-releases every camera source now and flips status to
    inactive (empty cameras)."""
    science = _TrackingSource()
    overview = _TrackingSource()
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=science,
        overview_source=overview,
    )
    with TestClient(app) as c:
        # Engage the overview camera by registering a viewer on its streamer.
        gen = app.state.overview_streamer.frames()
        next(gen)
        assert overview.is_open  # opened on demand

        r = c.post("/api/vision/deactivate")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is False
        assert body["cameras"] == []

        assert not overview.is_open  # force-released
        assert overview.close_count >= 1
        assert app.state.vision is None  # science service torn down

        gen.close()
        # status stays inactive after teardown
        assert c.get("/api/vision/status").json()["active"] is False


def test_vision_cameras_lists_roles(client: TestClient) -> None:
    r = client.get("/api/vision/cameras")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"overview", "science"}
    assert body["overview"]["role"] == "overview"
    assert body["science"]["role"] == "science"


def test_vision_captures_empty_when_no_run(client: TestClient) -> None:
    r = client.get("/api/vision/captures", params={"run": "no_such_run"})
    assert r.status_code == 200
    assert r.json() == []


def test_vision_calibrate_computes_saves_and_hot_swaps(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    app, client = app_and_client
    body = {
        "image_points": [[0, 0], [10, 0], [10, 10], [0, 10]],
        "world_points_mm": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "mm_per_px": 0.5,
        "bed_extent_mm": [0, 0, 200, 200],
    }
    r = client.post("/api/vision/calibrate", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["reprojection_error"] == pytest.approx(0.0, abs=1e-6)
    assert isinstance(out["calibration_version"], str) and out["calibration_version"]

    calib_path = tmp_path / ".vision_calibration.json"
    assert calib_path.exists()

    status = client.get("/api/vision/status").json()
    assert status["calibration"] == out["calibration_version"]  # hot-swapped onto app.state.vision


def test_vision_overview_stream_headers_when_overview_source_present(tmp_path: Path) -> None:
    """200 + multipart/x-mixed-replace headers when a dedicated overview source is active.

    The OverviewStreamer's background grabber thread runs continuously by design (I1/M6),
    so the stream's body generator never ends on its own; Starlette's in-process TestClient
    fully drains a streaming response before returning control to the test, so this stops
    the streamer (app.state.overview_streamer) *before* issuing the request -- frames()
    then returns immediately (its stop-check is the first thing the loop does), which still
    exercises the real 200 + header path since StreamingResponse sends those before it reads
    anything from the body iterator.
    """
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=SimulatedFrameSource(width=32, height=24),
        overview_source=SimulatedFrameSource(width=8, height=8),
    )
    with TestClient(app) as c:
        app.state.overview_streamer.stop()
        r = c.get("/api/vision/overview/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")


def test_vision_overview_stream_returns_503_when_no_overview_source(tmp_path: Path) -> None:
    """No dedicated overview camera -> 503, and the science capture source is never touched
    (I1: the old science-source fallback grabbed from the worker's own capture source, which
    is not safe to share; it must be gone, not merely unreachable in the happy path)."""
    science_src = _CountingGrabSource()
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=science_src,
        overview_source=_FailingSource(),
    )
    with TestClient(app) as c:
        r = c.get("/api/vision/overview/stream")
        assert r.status_code == 503
        assert science_src.calls == 0


def test_vision_overview_stream_uses_dedicated_overview_source_on_demand(tmp_path: Path) -> None:
    """The overview live view must use its own OVERVIEW camera, not the science camera, and
    only ON DEMAND: nothing grabs at startup; registering a stream viewer opens and grabs the
    dedicated overview source while the science source is never touched.
    """
    overview_src = _TrackingSource()
    science_src = _TrackingSource()
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=science_src,
        overview_source=overview_src,
    )
    with TestClient(app) as c:
        # Nothing opened/grabbed at startup.
        time.sleep(0.1)
        assert overview_src.open_count == 0
        assert overview_src.grab_count == 0

        # Registering a viewer (the on-demand trigger) opens+grabs the OVERVIEW source only.
        gen = app.state.overview_streamer.frames()
        try:
            next(gen)
            assert overview_src.open_count == 1
            assert overview_src.grab_count >= 1
            assert science_src.open_count == 0  # dedicated: science never touched
        finally:
            gen.close()

        status = c.get("/api/vision/status").json()
        assert "overview" in status["cameras"]


def test_vision_capture_event_writes_file_under_active_run_dir(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    app, client = app_and_client
    r = client.post("/api/recording/start", json={"name": "vision-e2e"})
    assert r.status_code == 200
    run_name = r.json()["run"]

    app.state.events.append(
        "capture:post_jet", {"layer": 1, "axis_positions_mm": {"build": 0.0}}
    )
    app.state.vision.drain(timeout=2.0)

    captured = tmp_path / run_name / "vision" / "layer_0001" / "post_jet.webp"
    assert captured.exists()

    client.post("/api/recording/stop")


def test_science_capture_endpoint_stores_a_client_upload(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """The client-side capture path end-to-end: POST an encoded still to
    /api/vision/science/capture -> stored under the active run with cad_layer + source=client."""
    import cv2

    app, client = app_and_client
    run_name = client.post("/api/recording/start", json={"name": "client-cap-e2e"}).json()["run"]

    image = np.zeros((64, 64, 3), np.uint8)
    image[:, 32:] = 255
    ok, buf = cv2.imencode(".webp", image)
    assert ok
    resp = client.post(
        "/api/vision/science/capture?layer=7&stage=post_jet&cad_layer=2",
        content=buf.tobytes(),
        headers={"content-type": "image/webp"},
    )
    assert resp.status_code == 200 and resp.json()["stored"] is True
    assert (tmp_path / run_name / "vision" / "layer_0007" / "post_jet.webp").exists()

    records = client.get("/api/vision/captures", params={"run": run_name}).json()
    assert any(
        r["layer"] == 7 and r["cad_layer"] == 2 and r["stage"] == "post_jet" for r in records
    )
    client.post("/api/recording/stop")


def test_capture_signal_in_status_and_client_guard_skips_server_grab(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """A capture mark exposes a 'capture now' signal on the status (for the browser client), and
    while a client heartbeat is fresh the server's own cv2 grab is SKIPPED (the client captures)."""
    app, client = app_and_client
    run = client.post("/api/recording/start", json={"name": "sig-guard"}).json()["run"]

    client.post("/api/vision/science/client-heartbeat")  # client is live
    app.state.events.append("capture:post_jet", {"layer": 5, "print_layer": 2})
    app.state.vision.drain(timeout=2.0)

    # server grab skipped -> no server-written file for this mark
    assert not (tmp_path / run / "vision" / "layer_0005" / "post_jet.webp").exists()
    # but the signal is on the status for the browser to act on
    st = client.get("/api/status").json()
    assert st["capture_request"]["stage"] == "post_jet"
    assert st["capture_request"]["layer"] == 5 and st["capture_request"]["cad_layer"] == 2
    assert st["capture_request"]["seq"] >= 1
    client.post("/api/recording/stop")


def test_science_client_fallback_requeues_the_current_capture(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """A browser that heartbeated but then produced no frame can release ownership and preserve
    that exact layer/stage through the server worker. A stale sequence cannot capture the wrong
    event."""
    app, client = app_and_client
    run = client.post("/api/recording/start", json={"name": "client-fallback"}).json()["run"]
    client.post("/api/vision/science/client-heartbeat")
    app.state.events.append("capture:post_jet", {"layer": 5, "print_layer": 2})
    app.state.vision.drain(timeout=2.0)
    target = tmp_path / run / "vision" / "layer_0005" / "post_jet.webp"
    assert not target.exists()

    seq = client.get("/api/status").json()["capture_request"]["seq"]
    response = client.post("/api/vision/science/client-fallback", params={"seq": seq})
    assert response.status_code == 200 and response.json()["queued"] is True
    app.state.vision.drain(timeout=2.0)
    assert target.exists()
    assert client.post(
        "/api/vision/science/client-fallback", params={"seq": seq - 1}
    ).status_code == 409
    client.post("/api/recording/stop")


def test_science_capture_endpoint_rejects_bad_stage_and_empty_body(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    app, client = app_and_client
    client.post("/api/recording/start", json={"name": "client-cap-reject"})
    bogus = client.post("/api/vision/science/capture?layer=1&stage=bogus", content=b"x")
    assert bogus.status_code == 400
    assert client.post(
        "/api/vision/science/capture?layer=1&stage=pre_jet", content=b""
    ).status_code == 400
    client.post("/api/recording/stop")


def test_science_capture_endpoint_rejects_blank_image(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    import cv2

    _, client = app_and_client
    run = client.post("/api/recording/start", json={"name": "blank-client-cap"}).json()["run"]
    ok, buf = cv2.imencode(".webp", np.zeros((64, 64, 3), np.uint8))
    assert ok
    response = client.post(
        "/api/vision/science/capture?layer=1&stage=post_jet",
        content=buf.tobytes(),
        headers={"content-type": "image/webp"},
    )
    assert response.status_code == 422
    assert "blank or near-uniform" in response.json()["detail"]
    assert not (tmp_path / run / "vision").exists()
    client.post("/api/recording/stop")


def test_macos_server_fallback_is_blocked_before_opening_an_indexed_camera(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vention_printer_interface.api.app.platform.system", lambda: "Darwin")
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        device_enumerator=lambda: [],
    )
    with TestClient(app) as client:
        client.post("/api/recording/start", json={"name": "mac-safe-fallback"})
        app.state.events.append("capture:post_jet", {"layer": 3, "print_layer": 1})
        capture = client.get("/api/status").json()["capture_request"]
        assert capture["server_fallback_blocked"] is True
        response = client.post(
            "/api/vision/science/client-fallback", params={"seq": capture["seq"]}
        )
        assert response.status_code == 503
        assert "Continuity Camera" in response.json()["detail"]
        assert app.state.vision is None
        client.post("/api/recording/stop")


def test_vision_captures_endpoint_lists_capture_after_e2e_flow(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """Regression guard: the manifest (and therefore this endpoint) must not silently stay
    empty after a real capture — a debug/status page reading this must never show a false
    "no captures" when a capture actually happened (data-contract-verification false-green)."""
    app, client = app_and_client
    r = client.post("/api/recording/start", json={"name": "vision-captures-e2e"})
    assert r.status_code == 200
    run_name = r.json()["run"]

    app.state.events.append(
        "capture:post_jet", {"layer": 1, "axis_positions_mm": {"build": 0.0}}
    )
    app.state.vision.drain(timeout=2.0)
    client.post("/api/recording/stop")

    r = client.get("/api/vision/captures", params={"run": run_name})
    assert r.status_code == 200
    records = r.json()
    assert len(records) == 1
    assert records[0]["layer"] == 1
    assert records[0]["stage"] == "post_jet"


def _capture_one_run(app: FastAPI, client: TestClient, name: str) -> tuple[str, dict[str, Any]]:
    """Shared e2e-capture helper for the file-serving tests below: starts a run, fires one
    capture, drains it, stops the run, and returns (run_name, manifest_record)."""
    r = client.post("/api/recording/start", json={"name": name})
    assert r.status_code == 200
    run_name = r.json()["run"]

    app.state.events.append(
        "capture:post_jet", {"layer": 1, "axis_positions_mm": {"build": 0.0}}
    )
    app.state.vision.drain(timeout=2.0)
    client.post("/api/recording/stop")

    r = client.get("/api/vision/captures", params={"run": run_name})
    assert r.status_code == 200
    records = r.json()
    assert len(records) == 1
    record: dict[str, Any] = records[0]
    return run_name, record


def test_vision_captures_enriches_records_with_url_and_sidecar_url(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    """The captures API must hand back ready-to-use URLs (not just a bare run-relative
    `registered` path) so the Cameras UI can render an <img> without reconstructing a route
    the backend doesn't actually serve."""
    app, client = app_and_client
    _run_name, record = _capture_one_run(app, client, "vision-url-e2e")

    assert record["registered"] == "vision/layer_0001/post_jet.webp"
    assert isinstance(record.get("url"), str) and record["url"]
    assert isinstance(record.get("sidecar_url"), str) and record["sidecar_url"]
    assert "/api/vision/runs/" in record["url"]
    assert "path=" in record["url"]


def test_vision_run_file_serves_registered_image(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    app, client = app_and_client
    _run_name, record = _capture_one_run(app, client, "vision-file-img-e2e")

    r = client.get(record["url"])
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WEBP"  # WebP magic bytes
    assert r.headers["content-type"] == "image/webp"


def test_vision_run_file_serves_sidecar_json(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    app, client = app_and_client
    _run_name, record = _capture_one_run(app, client, "vision-file-json-e2e")

    r = client.get(record["sidecar_url"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["layer"] == 1
    assert body["stage"] == "post_jet"


def test_vision_run_file_rejects_path_traversal_outside_run(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    """A ../.. escape must never leak an arbitrary filesystem file (400/403, not a file)."""
    app, client = app_and_client
    run_name, _record = _capture_one_run(app, client, "vision-file-traversal-e2e")

    r = client.get(f"/api/vision/runs/{run_name}/file", params={"path": "../../../etc/passwd"})
    assert r.status_code in (400, 403)


def test_vision_run_file_rejects_path_outside_vision_subtree(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    """A path that stays inside the run dir but escapes the run's vision/ subtree (e.g. the
    run's own metadata.json, a sibling of vision/) must still be rejected — containment is
    scoped to vision/, not merely to the run directory."""
    app, client = app_and_client
    run_name, _record = _capture_one_run(app, client, "vision-file-scope-e2e")

    r = client.get(f"/api/vision/runs/{run_name}/file", params={"path": "metadata.json"})
    assert r.status_code in (400, 403)


def test_vision_run_file_rejects_absolute_path(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    app, client = app_and_client
    run_name, _record = _capture_one_run(app, client, "vision-file-absolute-e2e")

    r = client.get(f"/api/vision/runs/{run_name}/file", params={"path": "/etc/passwd"})
    assert r.status_code in (400, 403)


def test_vision_run_file_404_when_missing(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    app, client = app_and_client
    run_name, _record = _capture_one_run(app, client, "vision-file-missing-e2e")

    r = client.get(
        f"/api/vision/runs/{run_name}/file",
        params={"path": "vision/layer_0001/no_such_stage.png"},
    )
    assert r.status_code == 404


# ---- intrinsics/distortion calibration (Phase 6b, /api/vision/calibrate) --------------------
#
# Hardware-free: all points are SYNTHESIZED from a known pinhole model (K, zero distortion)
# via cv2.projectPoints -- no camera. With zero distortion the corrected path must reduce to
# the homography-only path (dist=0 equivalence), which anchors the geometry contract.
_K_TRUE = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
_IMAGE_SIZE = (640, 480)
_ZERO_DIST = np.zeros(5)
# One fixed camera pose looking at the bed plane (Z=0); the bed correspondence points are its
# exact projection, so world(x,y) -> image is an exact planar homography.
_BED_RVEC = np.array([0.02, -0.03, 0.01])
_BED_TVEC = np.array([-50.0, -40.0, 500.0])
_BED_WORLD = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 80.0], [0.0, 80.0], [50.0, 40.0]])
_BED_EXTENT = [0.0, 0.0, 100.0, 80.0]
_MM_PER_PX = 0.5


def _project_bed(world_xy: np.ndarray) -> list[list[float]]:
    """Project bed-plane world points (mm, Z=0) through the fixed bed pose + known K."""
    import cv2

    obj = np.stack(
        [world_xy[:, 0], world_xy[:, 1], np.zeros(len(world_xy))], axis=1
    ).astype(np.float64)
    img, _ = cv2.projectPoints(obj, _BED_RVEC, _BED_TVEC, _K_TRUE, _ZERO_DIST)
    result: list[list[float]] = img.reshape(-1, 2).tolist()
    return result


def _intrinsics_block() -> dict[str, Any]:
    """A multi-view planar-target intrinsics block synthesized from the known K (zero dist)."""
    import cv2

    grid_x, grid_y = np.meshgrid(np.arange(7, dtype=float), np.arange(5, dtype=float))
    target = np.stack([grid_x.ravel(), grid_y.ravel(), np.zeros(grid_x.size)], axis=1) * 20.0
    poses = [
        (np.array([0.1, -0.2, 0.05]), np.array([-60.0, -40.0, 400.0])),
        (np.array([-0.15, 0.1, 0.1]), np.array([-50.0, -30.0, 450.0])),
        (np.array([0.05, 0.15, -0.1]), np.array([-70.0, -50.0, 420.0])),
        (np.array([0.2, 0.0, 0.0]), np.array([-40.0, -35.0, 380.0])),
    ]
    views: list[dict[str, Any]] = []
    for rvec, tvec in poses:
        proj, _ = cv2.projectPoints(target, rvec, tvec, _K_TRUE, _ZERO_DIST)
        views.append(
            {"object_points": target.tolist(), "image_points": proj.reshape(-1, 2).tolist()}
        )
    return {"image_size": list(_IMAGE_SIZE), "views": views}


def _common_bed_body() -> dict[str, Any]:
    """The homography-only request payload (bed correspondence + raster params)."""
    return {
        "image_points": _project_bed(_BED_WORLD),
        "world_points_mm": _BED_WORLD.tolist(),
        "mm_per_px": _MM_PER_PX,
        "bed_extent_mm": _BED_EXTENT,
    }


def test_vision_calibrate_intrinsics_path_corrected_and_reaches_runtime(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """Intrinsics provided -> distortion-corrected calibration, persisted AND live at runtime."""
    app, client = app_and_client
    body = {**_common_bed_body(), "intrinsics": _intrinsics_block()}

    r = client.post("/api/vision/calibrate", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["corrected"] is True
    assert out["intrinsics_rms"] is not None
    assert out["intrinsics_rms"] < 1.0
    assert out["reprojection_error"] < 1e-3

    # Persisted with a non-null camera_matrix.
    loaded = load_calibration(tmp_path / ".vision_calibration.json")
    assert loaded is not None
    assert loaded.camera_matrix is not None
    assert loaded.dist_coeffs is not None
    assert loaded.image_size == _IMAGE_SIZE

    # Proof it reached the runtime capture worker -> the corrected register path is now live.
    assert app.state.vision.calibration is not None
    assert app.state.vision.calibration.camera_matrix is not None


def test_vision_calibrate_dist0_equivalence_matches_homography_only(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    """With zero distortion the corrected result must equal the homography-only result:
    tiny reprojection error, identical bed geometry, and sub-pixel-identical registration."""
    app, client = app_and_client
    common = _common_bed_body()

    corr_body = {**common, "intrinsics": _intrinsics_block()}
    r_corr = client.post("/api/vision/calibrate", json=corr_body)
    assert r_corr.status_code == 200
    assert r_corr.json()["corrected"] is True
    assert r_corr.json()["reprojection_error"] < 1e-3
    cal_corrected = app.state.vision.calibration
    h_corrected = cal_corrected.H.copy()

    r_plain = client.post("/api/vision/calibrate", json=common)
    assert r_plain.status_code == 200
    assert r_plain.json()["corrected"] is False
    assert r_plain.json()["reprojection_error"] < 1e-3
    cal_plain = app.state.vision.calibration
    h_plain = cal_plain.H.copy()

    bed_img = np.asarray(common["image_points"], dtype=float)
    # Both homographies map the bed points to the same world coords (sub-mm), and to truth.
    world_corr = apply_homography(h_corrected, bed_img)
    world_plain = apply_homography(h_plain, bed_img)
    assert np.allclose(world_corr, world_plain, atol=1e-3)
    assert np.allclose(world_corr, _BED_WORLD, atol=1e-3)

    # End-to-end: the two calibrations register the same frame to the same raster (dist=0
    # undistort is an identity map, so corrected reduces to homography-only).
    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (_IMAGE_SIZE[1], _IMAGE_SIZE[0], 3), dtype=np.uint8).astype(np.uint8)
    reg_corrected, _ = register_frame(img, cal_corrected)
    reg_plain, _ = register_frame(img, cal_plain)
    assert reg_corrected.shape == reg_plain.shape
    assert np.allclose(reg_corrected.astype(float), reg_plain.astype(float), atol=1.0)


def test_vision_calibrate_without_intrinsics_is_backward_compatible(
    app_and_client: tuple[FastAPI, TestClient], tmp_path: Path
) -> None:
    """No intrinsics -> homography-only, corrected=False, null camera_matrix on disk + runtime."""
    app, client = app_and_client

    r = client.post("/api/vision/calibrate", json=_common_bed_body())
    assert r.status_code == 200
    out = r.json()
    assert out["corrected"] is False
    assert out["intrinsics_rms"] is None
    assert out["validation"] is None

    loaded = load_calibration(tmp_path / ".vision_calibration.json")
    assert loaded is not None
    assert loaded.camera_matrix is None
    assert loaded.dist_coeffs is None
    assert loaded.image_size is None

    assert app.state.vision.calibration is not None
    assert app.state.vision.calibration.camera_matrix is None


def test_vision_calibrate_validation_block_reports_small_rms(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    """A validation block (independent points) -> response validation.rms_mm present + small."""
    app, client = app_and_client
    val_world = np.array([[25.0, 25.0], [70.0, 55.0], [40.0, 60.0]])
    body = {
        **_common_bed_body(),
        "intrinsics": _intrinsics_block(),
        "validation": {
            "image_points": _project_bed(val_world),
            "world_points_mm": val_world.tolist(),
        },
    }

    r = client.post("/api/vision/calibrate", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["validation"] is not None
    assert "rms_mm" in out["validation"]
    assert out["validation"]["rms_mm"] < 0.1


# ---- calibration board generator (A8, GET /api/vision/board) --------------------------------
def test_board_endpoint_svg_preset_returns_svg_with_download_name(client: TestClient) -> None:
    r = client.get("/api/vision/board", params={"format": "svg", "preset": "medium_5x7"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in r.headers["content-disposition"]
    assert ".svg" in r.headers["content-disposition"]
    assert r.text.lstrip().startswith("<?xml") or r.text.lstrip().startswith("<svg")
    assert "<svg" in r.text


def test_board_endpoint_dxf_preset_returns_dxf_with_download_name(client: TestClient) -> None:
    r = client.get("/api/vision/board", params={"format": "dxf", "preset": "small_cylinder"})
    assert r.status_code == 200
    assert r.headers["content-type"] in ("application/dxf", "image/vnd.dxf")
    assert "attachment" in r.headers["content-disposition"]
    assert ".dxf" in r.headers["content-disposition"]
    # DXF round-trips through ezdxf.
    import io

    import ezdxf

    doc = ezdxf.read(io.StringIO(r.content.decode("utf-8")))
    assert len(doc.modelspace().query("LWPOLYLINE")) > 0


def test_board_endpoint_bad_preset_returns_400(client: TestClient) -> None:
    r = client.get("/api/vision/board", params={"format": "svg", "preset": "does_not_exist"})
    assert r.status_code == 400


def test_board_endpoint_bad_format_returns_400(client: TestClient) -> None:
    r = client.get("/api/vision/board", params={"format": "pdf", "preset": "medium_5x7"})
    assert r.status_code == 400


def test_board_endpoint_explicit_params_svg_has_exact_mm(client: TestClient) -> None:
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 5,
            "squares_y": 7,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    assert r.status_code == 200
    # board 100x140 mm + quiet-zone margins; width/height carried in mm.
    assert 'mm"' in r.text
    assert 'viewBox="0 0' in r.text


def test_board_endpoint_missing_params_and_no_preset_returns_400(client: TestClient) -> None:
    r = client.get("/api/vision/board", params={"format": "svg"})
    assert r.status_code == 400


def test_board_endpoint_engrave_black_false_differs(client: TestClient) -> None:
    base = {"format": "svg", "preset": "medium_5x7"}
    r_true = client.get("/api/vision/board", params={**base, "engrave_black": "true"})
    r_false = client.get("/api/vision/board", params={**base, "engrave_black": "false"})
    assert r_true.status_code == 200 and r_false.status_code == 200
    assert r_true.text != r_false.text


# ---- I-1: GET /api/vision/board must validate params -> 400 (never 500 / CPU-burn) ----------
def test_board_endpoint_dict_not_a_real_aruco_dictionary_name_returns_400(
    client: TestClient,
) -> None:
    """``CharucoBoard`` is a real attribute of cv2.aruco, but not a DICT_* dictionary name --
    the allowlist must be built from real dictionary names, not just ``hasattr``."""
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 5,
            "squares_y": 7,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "CharucoBoard",
        },
    )
    assert r.status_code == 400


def test_board_endpoint_marker_mm_greater_equal_square_mm_returns_400(
    client: TestClient,
) -> None:
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 5,
            "squares_y": 7,
            "square_mm": 15.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    assert r.status_code == 400


def test_board_endpoint_squares_x_zero_returns_400(client: TestClient) -> None:
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 0,
            "squares_y": 7,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    assert r.status_code == 400


def test_board_endpoint_squares_x_negative_returns_400(client: TestClient) -> None:
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": -3,
            "squares_y": 7,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    assert r.status_code == 400


def test_board_endpoint_huge_squares_rejected_fast(client: TestClient) -> None:
    """squares_x=squares_y=300 must be rejected by validation BEFORE any cv2 board-generation
    compute -- so this request must return 400 quickly, not burn CPU building a 300x300 board."""
    start = time.monotonic()
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 300,
            "squares_y": 300,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    elapsed = time.monotonic() - start
    assert r.status_code == 400
    assert elapsed < 1.0, f"rejection took {elapsed:.2f}s -- validation did not short-circuit"


def test_board_endpoint_valid_explicit_params_still_returns_200(client: TestClient) -> None:
    r = client.get(
        "/api/vision/board",
        params={
            "format": "svg",
            "squares_x": 5,
            "squares_y": 7,
            "square_mm": 20.0,
            "marker_mm": 15.0,
            "dict": "DICT_4X4_50",
        },
    )
    assert r.status_code == 200


# ---- camera auto-connect + persistent role memory + quick-start (A7) ------------------------
#
# Both ELP cameras enumerate alike (same sensor/near-identical names), so a `device_enumerator`
# is injected here -- never real hardware -- returning a fixed, stubbed device list per test.


def _fake_devices() -> list[dict[str, Any]]:
    return [
        {"index": 0, "stable_id": "usb-A-overview", "name": "ELP overview", "has_frame": True},
        {"index": 1, "stable_id": "usb-B-science", "name": "ELP science", "has_frame": True},
    ]


def _vision_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    kwargs: dict[str, Any] = {
        "backend": "none",
        "experiments_root": tmp_path,
        "poll_interval_s": 0.05,
        "print_min_wait_s": 0.1,
        "print_step_timeout_s": 5.0,
        "vision_source": SimulatedFrameSource(width=32, height=24),
        "overview_source": SimulatedFrameSource(width=8, height=8),
        "device_enumerator": _fake_devices,
    }
    kwargs.update(overrides)
    return create_app(**kwargs)


def test_vision_status_roles_resolved_true_and_both_active_with_full_role_map(
    tmp_path: Path,
) -> None:
    from vention_printer_interface.vision.cameras import save_role_map

    save_role_map(
        tmp_path / ".vision_roles.json",
        {"usb-A-overview": "overview", "usb-B-science": "science"},
    )
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        status = c.get("/api/vision/status").json()
        assert status["roles_resolved"] is True
        assert status["unresolved"] == []
        assert set(status["cameras"]) == {"overview", "science"}


def test_vision_status_roles_unresolved_when_map_missing_current_stable_ids(
    tmp_path: Path,
) -> None:
    """An empty (new-machine) role map -> both roles unresolved, listed, and reported False --
    even though the science/overview sources still auto-open via resolve_roles' index fallback
    (auto-connect keeps working; only the *confirmed* status flips false)."""
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        status = c.get("/api/vision/status").json()
        assert status["roles_resolved"] is False
        assert status["unresolved"] == ["overview", "science"]
        assert set(status["cameras"]) == {"overview", "science"}


def test_vision_devices_lists_stubbed_devices_with_resolved_roles(tmp_path: Path) -> None:
    """The role field comes straight from `resolve_roles` (as the spec/plan direct), so an
    unmapped device sitting at a role's configured default index still resolves via that
    fallback -- same fallback GET /api/vision/status's `unresolved` would flag as unconfirmed."""
    from vention_printer_interface.vision.cameras import save_role_map

    save_role_map(tmp_path / ".vision_roles.json", {"usb-A-overview": "overview"})
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/vision/devices")
        assert r.status_code == 200
        body = r.json()
        assert body["camera_access"] == "ok"
        devices = body["devices"]
        assert len(devices) == 2
        by_index = {d["index"]: d for d in devices}
        assert by_index[0]["stable_id"] == "usb-A-overview"
        assert by_index[0]["role"] == "overview"
        assert by_index[0]["has_frame"] is True
        assert by_index[1]["stable_id"] == "usb-B-science"
        assert by_index[1]["role"] == "science"  # index-fallback resolved, not operator-confirmed
        assert by_index[1]["has_frame"] is True


# ---- GET /api/vision/devices camera_access (macOS permission-denied signal) -------------------
def _fake_devices_denied() -> list[dict[str, Any]]:
    """Both devices enumerate (opened successfully) but neither yields a frame -- the macOS
    "camera permission not granted" signature."""
    return [
        {"index": 0, "stable_id": "usb-A-overview", "name": "ELP overview", "has_frame": False},
        {"index": 1, "stable_id": "usb-B-science", "name": "ELP science", "has_frame": False},
    ]


def _fake_devices_mixed() -> list[dict[str, Any]]:
    return [
        {"index": 0, "stable_id": "usb-A-overview", "name": "ELP overview", "has_frame": False},
        {"index": 1, "stable_id": "usb-B-science", "name": "ELP science", "has_frame": True},
    ]


def test_vision_devices_camera_access_denied_when_no_device_yields_a_frame(tmp_path: Path) -> None:
    app = _vision_app(tmp_path, device_enumerator=_fake_devices_denied)
    with TestClient(app) as c:
        r = c.get("/api/vision/devices")
        assert r.status_code == 200
        body = r.json()
        assert body["camera_access"] == "denied"
        assert all(d["has_frame"] is False for d in body["devices"])


def test_vision_devices_camera_access_no_devices_when_enumerator_returns_empty(
    tmp_path: Path,
) -> None:
    app = _vision_app(tmp_path, device_enumerator=lambda: [])
    with TestClient(app) as c:
        r = c.get("/api/vision/devices")
        assert r.status_code == 200
        body = r.json()
        assert body["camera_access"] == "no_devices"
        assert body["devices"] == []


def test_vision_devices_camera_access_ok_when_at_least_one_device_yields_a_frame(
    tmp_path: Path,
) -> None:
    app = _vision_app(tmp_path, device_enumerator=_fake_devices_mixed)
    with TestClient(app) as c:
        body = c.get("/api/vision/devices").json()
        assert body["camera_access"] == "ok"


def test_vision_roles_get_returns_persisted_map(tmp_path: Path) -> None:
    from vention_printer_interface.vision.cameras import save_role_map

    save_role_map(tmp_path / ".vision_roles.json", {"usb-A-overview": "overview"})
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/vision/roles")
        assert r.status_code == 200
        assert r.json() == {"usb-A-overview": "overview"}


def test_vision_roles_get_empty_dict_when_no_map_saved_yet(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/vision/roles").json() == {}


def test_vision_roles_put_persists_reopens_and_flips_roles_resolved(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/vision/status").json()["roles_resolved"] is False

        r = c.put(
            "/api/vision/roles",
            json={"mapping": {"usb-A-overview": "overview", "usb-B-science": "science"}},
        )
        assert r.status_code == 200
        out = r.json()
        assert out["roles_resolved"] is True
        assert out["unresolved"] == []

        status_after = c.get("/api/vision/status").json()
        assert status_after["roles_resolved"] is True
        # (re)opened, guarded: both roles still report active after the PUT-triggered reopen.
        assert set(status_after["cameras"]) == {"overview", "science"}


def test_vision_roles_put_survives_a_recreated_app_at_the_same_root(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put(
            "/api/vision/roles",
            json={"mapping": {"usb-A-overview": "overview", "usb-B-science": "science"}},
        )
        assert r.status_code == 200

    app2 = _vision_app(tmp_path)
    with TestClient(app2) as c2:
        status2 = c2.get("/api/vision/status").json()
        assert status2["roles_resolved"] is True
        assert set(status2["cameras"]) == {"overview", "science"}


def test_vision_roles_put_with_unknown_device_never_crashes(tmp_path: Path) -> None:
    """A role pointed at a stable_id that isn't (yet) plugged in must be guarded -- persisted,
    reported unresolved for that role, but never a 500 and never crashes the reopen."""
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put(
            "/api/vision/roles",
            json={"mapping": {"usb-A-overview": "overview", "usb-not-plugged-in": "science"}},
        )
        assert r.status_code == 200
        out = r.json()
        assert out["roles_resolved"] is False
        assert out["unresolved"] == ["science"]


# ---- M-2: PUT /api/vision/roles must validate role values ------------------------------------
def test_vision_roles_put_rejects_bad_role_value_and_persists_nothing(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put(
            "/api/vision/roles",
            json={"mapping": {"usb-A-overview": "Science"}},  # bad case
        )
        assert r.status_code in (400, 422)

        # nothing persisted: a fresh app at the same root still sees an empty map.
        assert c.get("/api/vision/roles").json() == {}

    app2 = _vision_app(tmp_path)
    with TestClient(app2) as c2:
        assert c2.get("/api/vision/roles").json() == {}


def test_vision_roles_put_still_persists_a_valid_mapping(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put(
            "/api/vision/roles",
            json={"mapping": {"usb-A-overview": "overview", "usb-B-science": "science"}},
        )
        assert r.status_code == 200
        assert c.get("/api/vision/roles").json() == {
            "usb-A-overview": "overview",
            "usb-B-science": "science",
        }


def test_vision_settings_get_reports_defaults(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        body = c.get("/api/vision/settings").json()
        assert body["overview"]["resolution"] == [1920, 1080]
        assert body["overview"]["format"] == "MJPG"
        assert body["overview"]["exposure"] is None
        assert body["science"]["resolution"] == [5120, 3840]
        assert body["science"]["fps"] == 7.5


def test_vision_settings_put_then_get_round_trips_and_persists(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put(
            "/api/vision/settings",
            json={
                "science": {
                    "resolution": [2560, 1440],
                    "fps": 15.0,
                    "format": "MJPG",
                    "exposure": -4.0,
                }
            },
        )
        assert r.status_code == 200

        got = c.get("/api/vision/settings").json()
        assert got["science"]["resolution"] == [2560, 1440]
        assert got["science"]["fps"] == 15.0
        assert got["science"]["format"] == "MJPG"
        assert got["science"]["exposure"] == -4.0
        # overview untouched
        assert got["overview"]["resolution"] == [1920, 1080]

    # persisted alongside the role map, in CameraSpec-field form
    persisted = tmp_path / ".vision_settings.json"
    assert persisted.exists()
    saved = json.loads(persisted.read_text())
    assert saved["science"]["width"] == 2560 and saved["science"]["height"] == 1440
    assert saved["science"]["pixel_format"] == "MJPG"

    # CameraConfig reflects the override (via /api/vision/cameras)
    with TestClient(app) as c:
        cams = c.get("/api/vision/cameras").json()
        assert cams["science"]["width"] == 2560 and cams["science"]["height"] == 1440
        assert cams["science"]["exposure"] == -4.0


def test_vision_settings_accepts_wxh_string_resolution(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        r = c.put("/api/vision/settings", json={"overview": {"resolution": "1280x720"}})
        assert r.status_code == 200
        got = c.get("/api/vision/settings").json()
        assert got["overview"]["resolution"] == [1280, 720]


def test_vision_settings_survive_a_recreated_app_at_the_same_root(tmp_path: Path) -> None:
    app = _vision_app(tmp_path)
    with TestClient(app) as c:
        c.put("/api/vision/settings", json={"science": {"fps": 12.0}})
    # a fresh app at the same root merges the persisted override at build time
    app2 = _vision_app(tmp_path)
    with TestClient(app2) as c:
        assert c.get("/api/vision/settings").json()["science"]["fps"] == 12.0


# ---- guided calibration-capture session (A6b, /api/vision/calibrate/session|capture|finalize)
#
# Hardware-free: a synthetic FrameSource renders warped ChArUco poses (rendered from the REAL
# installed cv2.aruco, so geometry is the library's own, not invented) -- one pose per grab.
# Session -> repeated capture (views accumulate) -> finalize (intrinsics + bed homography).

_SESSION_CHARUCO = {
    "kind": "charuco",
    "squares_x": 7,
    "squares_y": 5,
    "square_length_mm": 20.0,
    "marker_length_mm": 15.0,
    "aruco_dict": "DICT_5X5_100",
}


def _render_charuco_base(size: tuple[int, int] = (900, 700)) -> np.ndarray:
    import cv2.aruco as aruco

    dictionary = aruco.getPredefinedDictionary(aruco.DICT_5X5_100)
    board = aruco.CharucoBoard((7, 5), 20.0, 15.0, dictionary)
    img: np.ndarray = board.generateImage(size, marginSize=60)
    return img


def _warped_charuco_frames(n: int, seed: int = 11) -> list[np.ndarray]:
    import cv2

    base = _render_charuco_base()
    rng = np.random.default_rng(seed)
    h, w = base.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    frames: list[np.ndarray] = []
    for _ in range(n):
        jitter = rng.uniform(-25, 25, (4, 2)).astype(np.float32)
        m = cv2.getPerspectiveTransform(src, src + jitter)
        frames.append(cv2.warpPerspective(base, m, (w, h), borderValue=255))
    return frames


class _CharucoPoseSource(FrameSource):
    """Returns a different warped ChArUco frame on each grab (cycles through a fixed set)."""

    def __init__(self, n: int = 10) -> None:
        self._frames = _warped_charuco_frames(n)
        self._i = 0

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        img = self._frames[self._i % len(self._frames)]
        self._i += 1
        return Frame(image=img, timestamp_ns=time.time_ns() + self._i)


class _BlankSource(FrameSource):
    """Always returns a blank (no-board) frame -- detect_board must return None on it."""

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        return Frame(image=np.full((500, 700, 3), 255, np.uint8), timestamp_ns=time.time_ns())


def _calib_app(tmp_path: Path, source: FrameSource) -> FastAPI:
    return create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=source,
    )


def test_calibrate_session_start_resets_and_reports_state(tmp_path: Path) -> None:
    app = _calib_app(tmp_path, _CharucoPoseSource())
    with TestClient(app) as c:
        r = c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        assert r.status_code == 200
        body = r.json()
        assert body["n_views"] == 0
        assert body["ready"] is False
        assert body["spec"]["kind"] == "charuco"

        # GET mirrors the POST-reported state.
        g = c.get("/api/vision/calibrate/session").json()
        assert g["n_views"] == 0
        assert g["spec"]["squares_x"] == 7


def test_calibrate_capture_accumulates_views(tmp_path: Path) -> None:
    app = _calib_app(tmp_path, _CharucoPoseSource())
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        captured = 0
        for _ in range(8):
            r = c.post("/api/vision/calibrate/capture")
            assert r.status_code == 200
            if r.json()["captured"]:
                captured += 1
        assert captured >= 4
        session = c.get("/api/vision/calibrate/session").json()
        assert session["n_views"] == captured
        assert session["ready"] is True


def test_calibrate_capture_on_blank_frame_reports_not_captured_without_raising(
    tmp_path: Path,
) -> None:
    app = _calib_app(tmp_path, _BlankSource())
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        r = c.post("/api/vision/calibrate/capture")
        assert r.status_code == 200
        body = r.json()
        assert body["captured"] is False
        assert isinstance(body.get("reason"), str) and body["reason"]
        assert c.get("/api/vision/calibrate/session").json()["n_views"] == 0


def test_calibrate_finalize_uses_last_capture_as_bed_and_reaches_runtime(
    tmp_path: Path,
) -> None:
    app = _calib_app(tmp_path, _CharucoPoseSource())
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        for _ in range(8):
            c.post("/api/vision/calibrate/capture")

        r = c.post(
            "/api/vision/calibrate/finalize",
            json={
                "mm_per_px": 0.5,
                "bed_extent_mm": [0.0, 0.0, 120.0, 80.0],
                "use_last_capture_as_bed": True,
            },
        )
        assert r.status_code == 200
        out = r.json()
        assert out["corrected"] is True
        assert out["intrinsics_rms"] is not None
        assert out["n_views"] >= 4
        assert isinstance(out["calibration_version"], str) and out["calibration_version"]

        # Persisted with a non-null camera_matrix.
        loaded = load_calibration(tmp_path / ".vision_calibration.json")
        assert loaded is not None
        assert loaded.camera_matrix is not None
        assert loaded.dist_coeffs is not None

        # Reached the live capture worker.
        assert app.state.vision.calibration is not None
        assert app.state.vision.calibration.camera_matrix is not None
        assert app.state.vision.calibration.version == out["calibration_version"]


def _charuco_png_bytes(seed: int = 3) -> bytes:
    import cv2
    frame = _warped_charuco_frames(1, seed=seed)[0]
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    return bytes(buf.tobytes())


def test_calibrate_capture_upload_accumulates_without_a_server_camera(tmp_path: Path) -> None:
    # The browser grabs the science frame (reliable device id) and POSTs it: calibration must
    # accumulate from the UPLOADED image, using NO server camera. This is the frame-source fix —
    # calibration now shares the exact browser getUserMedia source the print captures use — and it
    # also removes the macOS "no science camera" 503 (there is no vision_source here).
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)  # no vision_source
    with TestClient(app) as c:
        assert app.state.vision is None  # genuinely no server science camera
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        r = c.post("/api/vision/calibrate/capture-upload", content=_charuco_png_bytes())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["captured"] is True
        assert body["count"] == 1 and body["corners_found"] > 0
        assert c.get("/api/vision/calibrate/session").json()["n_views"] == 1


def test_calibrate_capture_upload_finalizes_to_a_real_calibration(tmp_path: Path) -> None:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        for i in range(8):
            c.post("/api/vision/calibrate/capture-upload", content=_charuco_png_bytes(seed=i))
        r = c.post("/api/vision/calibrate/finalize",
                   json={"mm_per_px": 0.5, "bed_extent_mm": [0.0, 0.0, 120.0, 80.0],
                         "use_last_capture_as_bed": True})
        assert r.status_code == 200, r.text
        assert r.json()["corrected"] is True and r.json()["intrinsics_rms"] is not None


def test_calibrate_capture_upload_blank_reports_not_captured(tmp_path: Path) -> None:
    import cv2
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        ok, buf = cv2.imencode(".png", np.full((500, 700, 3), 255, np.uint8))
        r = c.post("/api/vision/calibrate/capture-upload", content=bytes(buf.tobytes()))
        assert r.status_code == 200
        assert r.json()["captured"] is False and r.json()["reason"]
        assert c.get("/api/vision/calibrate/session").json()["n_views"] == 0


def test_calibrate_capture_upload_guards_empty_body_and_no_session(tmp_path: Path) -> None:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        # no session yet
        assert c.post("/api/vision/calibrate/capture-upload",
                      content=_charuco_png_bytes()).status_code == 400
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        assert c.post("/api/vision/calibrate/capture-upload", content=b"").status_code == 400
        assert c.post("/api/vision/calibrate/capture-upload",
                      content=b"not an image").status_code == 400


def test_calibrate_finalize_with_zero_views_returns_400(tmp_path: Path) -> None:
    app = _calib_app(tmp_path, _CharucoPoseSource())
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        r = c.post(
            "/api/vision/calibrate/finalize",
            json={
                "mm_per_px": 0.5,
                "bed_extent_mm": [0.0, 0.0, 120.0, 80.0],
                "use_last_capture_as_bed": True,
            },
        )
        assert r.status_code == 400


def test_calibrate_finalize_without_bed_view_returns_400(tmp_path: Path) -> None:
    app = _calib_app(tmp_path, _CharucoPoseSource())
    with TestClient(app) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        for _ in range(8):
            c.post("/api/vision/calibrate/capture")
        # neither use_last_capture_as_bed nor explicit bed correspondence -> 400.
        r = c.post(
            "/api/vision/calibrate/finalize",
            json={"mm_per_px": 0.5, "bed_extent_mm": [0.0, 0.0, 120.0, 80.0]},
        )
        assert r.status_code == 400


# ---- checkerboard-validation mode (/api/vision/validate) ------------------------------------
#
# Hardware-free: a synthetic checkerboard image + a KNOWN calibration whose bed homography
# maps image px -> mm at a controlled scale. Case 1 (H scale == true pitch) -> tiny rms and
# scale_bias ~= 1. Case 2 (H scale 5% high) -> scale_bias ~= 1.05 caught, while the rigid
# (no-scale) alignment still strips the large placement offset so rms stays small.

_CHECKER_VALIDATE_SPEC = {
    "kind": "checkerboard",
    "cols": 6,
    "rows": 4,
    "square_size_mm": 20.0,
}
_CHECKER_SQUARE_PX = 40
_CHECKER_BORDER = 40
_CHECKER_W = (6 + 1) * _CHECKER_SQUARE_PX + 2 * _CHECKER_BORDER  # 360
_CHECKER_H = (4 + 1) * _CHECKER_SQUARE_PX + 2 * _CHECKER_BORDER  # 280


def _render_checker_validate() -> np.ndarray:
    n_cols_sq, n_rows_sq = 6 + 1, 4 + 1
    img = np.full((_CHECKER_H, _CHECKER_W), 255, np.uint8)
    for r in range(n_rows_sq):
        for col in range(n_cols_sq):
            if (r + col) % 2 == 0:
                y0 = _CHECKER_BORDER + r * _CHECKER_SQUARE_PX
                x0 = _CHECKER_BORDER + col * _CHECKER_SQUARE_PX
                img[y0 : y0 + _CHECKER_SQUARE_PX, x0 : x0 + _CHECKER_SQUARE_PX] = 0
    return img


class _CheckerSource(FrameSource):
    def __init__(self) -> None:
        self._img = _render_checker_validate()

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        return Frame(image=self._img.copy(), timestamp_ns=time.time_ns())


def _save_checker_calib(path: Path, k_scale: float) -> None:
    """Persist a calibration whose H maps px -> mm at 0.5*k_scale mm/px (+ a big mm offset)."""
    scale = 0.5 * k_scale  # px pitch 40 -> mm pitch 20*k_scale
    h_matrix = np.array([[scale, 0.0, 500.0], [0.0, scale, 300.0], [0.0, 0.0, 1.0]])
    k_matrix = np.array(
        [[1000.0, 0.0, _CHECKER_W / 2], [0.0, 1000.0, _CHECKER_H / 2], [0.0, 0.0, 1.0]]
    )
    calib = Calibration(
        H=h_matrix,
        mm_per_px=0.05,
        bed_extent_mm=(0.0, 0.0, 400.0, 400.0),
        version="cal-validate-test",
        reprojection_error=0.0,
        camera_matrix=k_matrix,
        dist_coeffs=np.zeros(5),
        distortion_model="opencv-5",
        image_size=(_CHECKER_W, _CHECKER_H),
    )
    save_calibration(path, calib)


def _validate_app(tmp_path: Path, source: FrameSource) -> FastAPI:
    return create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=source,
    )


def test_validate_true_geometry_small_rms_and_unit_scale_bias(tmp_path: Path) -> None:
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.0)
    app = _validate_app(tmp_path, _CheckerSource())
    with TestClient(app) as c:
        r = c.post(
            "/api/vision/validate",
            json={"spec": _CHECKER_VALIDATE_SPEC, "square_size_mm": 20.0},
        )
        assert r.status_code == 200
        out = r.json()
        assert out["n_points"] == 24
        assert len(out["per_point"]) == 24
        assert out["rms_mm"] < 0.5
        assert out["scale_bias"] == pytest.approx(1.0, abs=0.01)


def test_validate_catches_scale_error_after_alignment_removes_offset(tmp_path: Path) -> None:
    """A 5% scale error must show up in scale_bias (a scaled fit would hide it), while the
    rigid no-scale alignment still strips the large placement offset so rms stays small."""
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.05)
    app = _validate_app(tmp_path, _CheckerSource())
    with TestClient(app) as c:
        r = c.post(
            "/api/vision/validate",
            json={"spec": _CHECKER_VALIDATE_SPEC, "square_size_mm": 20.0},
        )
        assert r.status_code == 200
        out = r.json()
        assert out["scale_bias"] == pytest.approx(1.05, abs=0.01)  # scale error CAUGHT
        # the ~580 mm placement offset is removed by the rigid fit; only the scale residual
        # (0.05 * field radius) remains, well under the raw un-aligned distance.
        assert out["rms_mm"] < 3.0


def test_validate_returns_400_without_calibration(tmp_path: Path) -> None:
    app = _validate_app(tmp_path, _CheckerSource())  # no calibration file saved
    with TestClient(app) as c:
        r = c.post(
            "/api/vision/validate",
            json={"spec": _CHECKER_VALIDATE_SPEC, "square_size_mm": 20.0},
        )
        assert r.status_code == 400


def test_validate_returns_400_when_board_not_detected(tmp_path: Path) -> None:
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.0)
    app = _validate_app(tmp_path, _BlankSource())  # blank frame -> no checkerboard
    with TestClient(app) as c:
        r = c.post(
            "/api/vision/validate",
            json={"spec": _CHECKER_VALIDATE_SPEC, "square_size_mm": 20.0},
        )
        assert r.status_code == 400
