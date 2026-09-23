"""Print start checks that the feed holds enough powder (see control/feed_budget.py).

The simulator starts UNREFERENCED (like a power-cycled MM2), so its feed position can't be
trusted until homed; homing then an absolute move gives a known powder column.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app

# 5 printing layers at 0.5 mm feed each -> 2.5 mm of feed demand; nothing else consumes feed.
PLAN: dict[str, Any] = {
    "thin_precoat": {"n_layers": 0},
    "printing": {
        "layer_thickness_mm": 0.25, "feed_thickness_mm": 0.5, "n_layers": 5,
        "part_speed": 20, "part_accel": 100, "feed_speed": 20, "feed_accel": 100,
        "printhead_speed": 300, "printhead_accel": 2000,
        "recoater_speed": 300, "recoater_accel": 2000,
    },
    "postcoat": {"n_layers": 0},
    "postcoat_enabled": False,
    "recoater_end_mm": 30, "heater_end_mm": 20, "printhead_end_mm": 30,
    "heater_speed": 300, "heater_accel": 2000, "heater_enabled": False,
    "settle_s": 0.05, "feed_fast_speed": 20, "feed_fast_accel": 100,
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                     print_min_wait_s=0.1, print_step_timeout_s=5.0)
    with TestClient(app) as c:
        yield c


def _telemetry(c: TestClient) -> dict[str, Any] | None:
    t: dict[str, Any] | None = c.get("/api/status").json()["controller"]["telemetry"]
    return t


def _connect_arm_prime(c: TestClient) -> None:
    assert c.post("/api/connect", json={"backend": "simulated"}).status_code == 200
    for _ in range(100):
        if _telemetry(c):
            break
        time.sleep(0.02)
    assert c.post("/api/arm").status_code == 200
    assert c.put("/api/print-settings", json=PLAN).status_code == 200
    assert c.post("/api/primed/capture").status_code == 200


def _feed_at(c: TestClient, mm: float) -> None:
    """Home (references every axis) then put the feed piston at ``mm`` below flush."""
    c.post("/api/motion/home", json={"axes": []})
    end = time.monotonic() + 8
    while time.monotonic() < end:
        t = _telemetry(c)
        if t and all(t["referenced"].values()):
            break
        time.sleep(0.05)
    assert c.post("/api/motion/move", json={"axis": 2, "mode": "abs", "mm": mm}).status_code == 200
    end = time.monotonic() + 8
    while time.monotonic() < end:
        t = _telemetry(c)
        if t and abs(float(t["positions"]["2"]) - mm) < 1e-6:
            return
        time.sleep(0.05)
    raise AssertionError("feed never reached its target")


def test_print_settings_reports_the_feed_demand(client: TestClient) -> None:
    client.put("/api/print-settings", json=PLAN)
    assert client.get("/api/print-settings").json()["feed_demand_mm"] == 2.5


def test_budget_is_unknown_when_the_feed_is_not_homed(client: TestClient) -> None:
    _connect_arm_prime(client)
    b = client.get("/api/print/feed-budget").json()
    assert b["demand_mm"] == 2.5
    assert b["available_mm"] is None and b["sufficient"] is None
    assert "homed" in b["unknown_reason"]


def test_start_refuses_an_unverified_feed_unless_acknowledged(client: TestClient) -> None:
    _connect_arm_prime(client)
    r = client.post("/api/print/start", json={})
    assert r.status_code == 409 and "homed" in r.json()["detail"]
    assert client.post("/api/print/start", json={"accept_feed_risk": True}).status_code == 200


def test_enough_feed_starts_normally(client: TestClient) -> None:
    _connect_arm_prime(client)
    _feed_at(client, 10.0)
    b = client.get("/api/print/feed-budget").json()
    assert b["sufficient"] is True and b["available_mm"] == 10.0
    assert client.post("/api/print/start", json={}).status_code == 200


def test_short_feed_is_refused_then_a_partial_print_stops_safely(client: TestClient) -> None:
    _connect_arm_prime(client)
    _feed_at(client, 2.0)  # 2.0 mm of powder vs 2.5 mm needed -> layer 4 would reach flush
    b = client.get("/api/print/feed-budget").json()
    assert b["sufficient"] is False and b["layers_supported"] == 3 and b["layers_total"] == 5
    r = client.post("/api/print/start", json={})
    assert r.status_code == 409
    assert "powder" in r.json()["detail"] and "layer 3 of 5" in r.json()["detail"]
    full_steps = client.get("/api/print-settings").json()["n_steps"]
    started = client.post("/api/print/start", json={"accept_feed_risk": True})
    assert started.status_code == 200
    # compiled from the REAL feed position: the safe stop cuts the sequence short
    assert started.json()["n_steps"] < full_steps
