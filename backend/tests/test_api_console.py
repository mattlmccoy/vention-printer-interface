import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        backend="none",
        experiments_root=tmp_path,
        poll_interval_s=0.05,
        recipe_min_wait_s=0.1,
        recipe_step_timeout_s=5.0,
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


def wait_recipe(c: TestClient, state: str, timeout: float = 60.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s: dict[str, Any] = c.get("/api/status").json()["recipe"]
        if s["state"] == state:
            return s
        time.sleep(0.05)
    raise AssertionError(f"never {state}")


def test_events_in_status_and_endpoint(client: TestClient) -> None:
    connect_arm(client)
    client.post("/api/motion/home", json={"axes": []})
    ev = client.get("/api/events").json()["events"]
    labels = [e["label"] for e in ev]
    assert "connected" in labels and "armed" in labels and "home" in labels
    assert client.get("/api/status").json()["events"][-1]["label"] == "home"


def test_macro_load_cart(client: TestClient) -> None:
    assert client.post("/api/macro/load_cart").status_code == 409  # not armed
    connect_arm(client)
    client.post("/api/motion/home", json={"axes": []})
    for _ in range(200):
        pos = client.get("/api/status").json()["controller"]["telemetry"]["positions"]
        if pos["1"] == 0 and pos["2"] == 0:
            break
        time.sleep(0.05)
    client.put("/api/safety-limits", json={"travel_max": {"1": 10, "2": 10}})  # short: fast test
    assert client.post("/api/macro/nope").status_code == 400
    r = client.post("/api/macro/load_cart")
    assert r.status_code == 200 and r.json()["macro"] == "load_cart"
    wait_recipe(client, "done")
    tel = client.get("/api/status").json()["controller"]["telemetry"]
    assert tel["positions"]["1"] == 10.0 and tel["positions"]["4"] == 0.0


def test_fault_is_logged_as_event(client: TestClient) -> None:
    connect_arm(client)
    client.post("/api/estop")
    time.sleep(0.3)
    labels = [e["label"] for e in client.get("/api/events").json()["events"]]
    assert "estop" in labels and "fault" in labels


def test_recipe_payload_has_estimate(client: TestClient) -> None:
    r = client.get("/api/recipe").json()
    assert r["estimated_duration_s"] > 29
