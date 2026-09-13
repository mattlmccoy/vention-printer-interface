"""API tests for /api/vision/* (Task 12/13, spec §... layerwise vision Phase 6b).

Mirrors ``test_api_priming.py``'s fixture style. A ``SimulatedFrameSource`` is injected via
``create_app(..., vision_source=...)`` so nothing here opens a real camera.
"""

from __future__ import annotations

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
    assert body["cameras"] == ["science"]


def test_vision_status_returns_200_and_disabled_when_camera_open_fails(tmp_path: Path) -> None:
    # Guard requirement: a camera that fails to open must never block/crash app startup.
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=_FailingSource(),
    )
    with TestClient(app) as c:
        r = c.get("/api/vision/status")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is False
        assert body["cameras"] == []
        assert body["calibration"] is None
        assert body["queue"] == {"drops": 0}


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


def test_vision_overview_stream_uses_dedicated_overview_source(tmp_path: Path) -> None:
    """The overview live view must use its own OVERVIEW camera, not the science camera.

    Injects a distinct, always-succeeding overview_source alongside the science
    vision_source and waits (bounded) for the background grabber thread to actually call
    grab() on it, confirming the wiring reads from the dedicated overview source.
    """
    overview_src = _CountingGrabSource()
    science_src = _CountingGrabSource()
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
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and overview_src.calls == 0:
            time.sleep(0.01)
        assert overview_src.calls >= 1

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

    captured = tmp_path / run_name / "vision" / "layer_0001" / "post_jet.png"
    assert captured.exists()

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

    assert record["registered"] == "vision/layer_0001/post_jet.png"
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
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
    assert r.headers["content-type"] == "image/png"


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
