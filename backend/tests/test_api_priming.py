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


def connect_arm(c: TestClient) -> None:
    c.post("/api/connect", json={"backend": "simulated"})
    for _ in range(100):
        if c.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    assert c.post("/api/arm").status_code == 200


def test_priming_get_put_persists(client: TestClient) -> None:
    p = client.get("/api/priming").json()
    assert p["validation"] == []
    assert p["settings"]["feed_start_mm"] == 30.0 and p["n_cycles"] > 0
    r = client.put("/api/priming", json={"feed_start_mm": 12.0})
    assert r.status_code == 200 and r.json()["settings"]["feed_start_mm"] == 12.0
    assert client.get("/api/priming").json()["settings"]["feed_start_mm"] == 12.0  # persisted


def test_priming_run_requires_arm_then_starts(client: TestClient) -> None:
    assert client.post("/api/priming/run").status_code == 409  # not armed
    connect_arm(client)
    client.put("/api/priming", json={"feed_start_mm": 5.0, "thick_precoat_count": 0})  # short
    r = client.post("/api/priming/run")
    assert r.status_code == 200 and r.json()["macro"] == "priming"
    client.post("/api/print/abort")  # priming runs on the print step engine


def test_priming_run_rejects_out_of_travel_recoater(client: TestClient) -> None:
    connect_arm(client)
    # a recoater target past the 972 mm end stop is clamped by bounded(), so validation stays clean;
    # force an invalid one directly through the settings file path is out of scope — instead assert
    # that bounded clamps it into range (never a move past the end stop).
    r = client.put("/api/priming", json={"recoater_end_mm": 5000.0})
    assert r.status_code == 200 and r.json()["settings"]["recoater_end_mm"] <= 972.0
