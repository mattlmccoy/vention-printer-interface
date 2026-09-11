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


def test_priming_run_requires_arm_then_holds_for_powder(tmp_path: Path) -> None:
    from vention_printer_interface.control.safety import SafetyLimits

    # The flow homes BOTH pistons to 0 first (from the sim's 50 mm start); run all axes fast so each
    # sim move finishes inside the step timeout instead of ~20 s at the default 2.5 mm/s.
    lim = SafetyLimits.bounded(max_speed={"1": 20, "2": 20, "3": 300, "4": 300})
    app = create_app(
        backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
        print_min_wait_s=0.1, print_step_timeout_s=5.0, limits=lim,
    )
    with TestClient(app) as c:
        assert c.post("/api/priming/run").status_code == 409  # not armed
        connect_arm(c)
        c.put("/api/priming", json={"part_speed": 20, "feed_speed": 20, "recoater_speed": 300})
        r = c.post("/api/priming/run")
        assert r.status_code == 200 and r.json()["macro"] == "priming"
        for _ in range(300):
            if c.get("/api/status").json()["print"]["state"] == "paused":
                break
            time.sleep(0.05)
        assert c.get("/api/status").json()["print"]["state"] == "paused"  # reached the powder hold
        c.post("/api/print/abort")


def test_priming_bounded_clamps_recoater(client: TestClient) -> None:
    connect_arm(client)
    r = client.put("/api/priming", json={"level_recoat_end_mm": 5000.0})
    assert r.status_code == 200 and r.json()["settings"]["level_recoat_end_mm"] <= 972.0
