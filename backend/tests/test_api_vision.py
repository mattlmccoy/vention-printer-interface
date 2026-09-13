"""API tests for /api/vision/* (Task 12/13, spec §... layerwise vision Phase 6b).

Mirrors ``test_api_priming.py``'s fixture style. A ``SimulatedFrameSource`` is injected via
``create_app(..., vision_source=...)`` so nothing here opens a real camera.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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


class _OneFrameThenStopSource(FrameSource):
    """Overview-stream test only: grab() succeeds once, then raises.

    The real endpoint loops forever by design (multipart/x-mixed-replace never ends on its
    own), and Starlette's in-process TestClient fully drains a streaming response before
    returning control to the test (it does not stream progressively like a real socket
    would) — so an unbounded source would hang the test. Raising on the second grab() bounds
    the generator to exactly one chunk after headers, deterministically ending the response.
    """

    def __init__(self) -> None:
        self._used = False

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        if self._used:
            raise RuntimeError("stop after one frame (test boundary)")
        self._used = True
        return Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), timestamp_ns=1)


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


def test_vision_overview_stream_headers(tmp_path: Path) -> None:
    # Uses its own app (not the shared `client` fixture) so the deliberately-bounded source
    # here never touches the other tests' working SimulatedFrameSource. raise_server_exceptions
    # is disabled because the source's designed-in stop (see _OneFrameThenStopSource) surfaces
    # as an in-stream exception after the (already-sent) 200 headers; the test only cares that
    # those headers were correct, not that the never-ending stream ran to some "completion".
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=_OneFrameThenStopSource(),
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/vision/overview/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")


def test_vision_overview_stream_uses_dedicated_overview_source(tmp_path: Path) -> None:
    """The overview live view must use its own OVERVIEW camera, not the science camera.

    Injects a distinct overview_source (bounded, per the established one-frame-then-stop
    pattern) alongside the science vision_source, and checks the stream reads from the
    overview source (not the science one) while status.cameras reports overview as active.
    """
    overview_src = _OneFrameThenStopSource()
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
        vision_source=SimulatedFrameSource(width=32, height=24),
        overview_source=overview_src,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/vision/overview/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
        # The dedicated overview source's single frame must actually have been consumed.
        assert overview_src._used is True

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
