"""Endpoint tests for the piston backlash-calibration API against the simulated backend."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
    )
    with TestClient(app) as c:
        yield c


def connect_arm_reference(c: TestClient) -> None:
    c.post("/api/connect", json={"backend": "simulated"})
    for _ in range(100):
        if c.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    assert c.post("/api/arm").status_code == 200
    # Reference every axis at its current position (no homing move) so the piston is referenced.
    assert c.post("/api/reference/current").status_code == 200
    for _ in range(200):
        ref = c.get("/api/status").json()["controller"]["telemetry"]["referenced"]
        if ref.get("1") and ref.get("2"):
            break
        time.sleep(0.02)


def wait_backlash(c: TestClient, timeout: float = 25.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s = c.get("/api/motion/backlash/session").json()
        if s["state"] in ("done", "error", "cancelled"):
            return s
        time.sleep(0.1)
    last = c.get("/api/motion/backlash/session").json()
    raise AssertionError(f"backlash never finished; last={last}")


def test_status_is_idle_before_any_run(client: TestClient) -> None:
    s = client.get("/api/motion/backlash/session").json()
    assert s["state"] == "idle"


def test_start_refused_when_not_armed(client: TestClient) -> None:
    r = client.post("/api/motion/backlash/session", json={"axis": 1})
    assert r.status_code == 409
    assert "arm" in r.json()["detail"].lower() or "connect" in r.json()["detail"].lower()


def test_apply_refused_without_a_completed_measurement(client: TestClient) -> None:
    r = client.post("/api/motion/backlash/apply", json={"axis": 1})
    assert r.status_code == 409


def test_start_refused_for_dither_past_the_max(client: TestClient) -> None:
    connect_arm_reference(client)
    # 71 + 2 mm dither exceeds the 72 mm max -> rejected before any motion.
    r = client.post(
        "/api/motion/backlash/session",
        json={"axis": 1, "positions": [71.0], "d_mm": 2.0, "reps": 1},
    )
    assert r.status_code == 400


def test_full_cycle_measures_then_applies(client: TestClient) -> None:
    connect_arm_reference(client)
    client.post("/api/motion/move", json={"axis": 1, "mode": "abs", "mm": 10.0})
    started = client.post(
        "/api/motion/backlash/session",
        json={"axis": 1, "positions": [10.0], "d_mm": 2.0, "reps": 1},
    )
    assert started.status_code == 200
    done = wait_backlash(client)
    assert done["state"] == "done", done
    assert done["result"]["axis"] == 1
    assert done["result"]["recommended_mm"] == 0.0  # ideal simulator has no lash

    applied = client.post("/api/motion/backlash/apply", json={"axis": 1})
    assert applied.status_code == 200
    assert applied.json()["plan"]["build_backlash_mm"] == 0.0


def test_apply_axis_must_match_the_measurement(client: TestClient) -> None:
    connect_arm_reference(client)
    client.post("/api/motion/move", json={"axis": 1, "mode": "abs", "mm": 10.0})
    client.post(
        "/api/motion/backlash/session",
        json={"axis": 1, "positions": [10.0], "d_mm": 2.0, "reps": 1},
    )
    wait_backlash(client)
    r = client.post("/api/motion/backlash/apply", json={"axis": 2})  # measured axis 1, not 2
    assert r.status_code == 409
