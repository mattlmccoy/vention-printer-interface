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
    assert p["settings"]["feed_cavity_mm"] == 30.0 and p["n_thick_precoats"] == 3
    r = client.put("/api/priming", json={"feed_cavity_mm": 22.0, "n_thick_precoats": 2})
    assert r.status_code == 200 and r.json()["settings"]["feed_cavity_mm"] == 22.0
    assert client.get("/api/priming").json()["settings"]["feed_cavity_mm"] == 22.0


def test_priming_run_requires_arm_then_holds_for_powder(client: TestClient) -> None:
    assert client.post("/api/priming/run").status_code == 409  # not armed
    connect_arm(client)
    # sim axes start at 50 mm and pistons cap at 5 mm/s; keep the pre-hold piston targets near the
    # start so each move's wait finishes inside the fixture's 5 s step timeout (the default part
    # target 0 mm would take ~20 s and fault before the hold).
    client.put("/api/priming", json={"part_top_mm": 48.0, "feed_cavity_mm": 48.0})
    r = client.post("/api/priming/run")
    assert r.status_code == 200 and r.json()["macro"] == "priming"
    for _ in range(200):
        if client.get("/api/status").json()["print"]["state"] == "paused":
            break
        time.sleep(0.05)
    assert client.get("/api/status").json()["print"]["state"] == "paused"
    client.post("/api/print/abort")


def test_priming_bounded_clamps_recoater(client: TestClient) -> None:
    connect_arm(client)
    r = client.put("/api/priming", json={"level_recoat_end_mm": 5000.0})
    assert r.status_code == 200 and r.json()["settings"]["level_recoat_end_mm"] <= 972.0
