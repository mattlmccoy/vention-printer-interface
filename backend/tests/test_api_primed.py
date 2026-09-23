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


def connect(c: TestClient) -> None:
    c.post("/api/connect", json={"backend": "simulated"})
    for _ in range(100):
        if c.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    assert c.get("/api/status").json()["controller"]["telemetry"]


def test_primed_get_none_when_unsaved(client: TestClient) -> None:
    r = client.get("/api/primed").json()
    assert r["primed"] is None and r["status"]["state"] == "none"


def test_capture_requires_controller(client: TestClient) -> None:
    assert client.post("/api/primed/capture").status_code == 409


def test_capture_reads_live_positions_and_persists(client: TestClient) -> None:
    connect(client)
    positions = client.get("/api/status").json()["controller"]["telemetry"]["positions"]
    r = client.post("/api/primed/capture")
    assert r.status_code == 200
    primed = r.json()["primed"]
    assert primed["part_mm"] == positions["1"]
    assert primed["feed_mm"] == positions["2"]
    assert primed["captured_at"] > 0
    # persisted: a fresh GET returns the same snapshot
    got = client.get("/api/primed").json()["primed"]
    assert got == primed
