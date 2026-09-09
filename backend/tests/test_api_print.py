import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app

FAST: dict[str, Any] = {
    "precoat": {"n_layers": 0},
    "printing": {
        "layer_thickness_mm": 1.0,
        "n_layers": 1,
        "part_speed": 20,
        "part_accel": 100,
        "feed_speed": 20,
        "feed_accel": 100,
        "printhead_speed": 300,
        "printhead_accel": 2000,
        "recoater_speed": 300,
        "recoater_accel": 2000,
    },
    "postcoat": {"n_layers": 0},
    "feed_end_mm": 10,
    "recoater_end_mm": 30,
    "heater_end_mm": 20,
    "printhead_end_mm": 30,
    "heater_speed": 300,
    "heater_accel": 2000,
    "heater_enabled": True,
    "settle_s": 0.05,
    "feed_fast_speed": 20,
    "feed_fast_accel": 100,
}


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
    assert c.post("/api/connect", json={"backend": "simulated"}).status_code == 200
    for _ in range(100):
        if c.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    assert c.post("/api/arm").status_code == 200


def wait_print(c: TestClient, state: str, timeout: float = 30.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s: dict[str, Any] = c.get("/api/status").json()["print"]
        if s["state"] == state:
            return s
        time.sleep(0.05)
    raise AssertionError(f"print never reached {state}: {c.get('/api/status').json()['print']}")


def test_get_print_settings_has_plan_bounds_validation_and_steps(client: TestClient) -> None:
    r = client.get("/api/print-settings").json()
    assert r["plan"]["printing"]["n_layers"] == 10
    assert r["validation"] == [] and r["n_steps"] > 0 and r["total_layers"] == 12
    assert "bounds" in r and "max_speed" in r["bounds"]


def test_put_print_settings_rebounds_validates_and_persists(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.put(
        "/api/print-settings", json={"printing": {"n_layers": 3, "recoater_speed": 99999}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["printing"]["n_layers"] == 3
    assert body["plan"]["printing"]["recoater_speed"] == 200.0  # bounded by limits
    assert (tmp_path / ".print_settings.json").exists()
    bad = client.put(
        "/api/print-settings", json={"printing": {"n_layers": 200, "layer_thickness_mm": 2}}
    )
    assert bad.status_code == 200 and any("thickness" in v for v in bad.json()["validation"])


def test_start_refused_when_not_armed_or_invalid(client: TestClient) -> None:
    assert client.post("/api/print/start", json={}).status_code == 409
    client.post("/api/connect", json={"backend": "simulated"})
    assert client.post("/api/print/start", json={}).status_code == 409
    client.put("/api/print-settings", json={"printing": {"n_layers": 200, "layer_thickness_mm": 2}})
    connect_arm(client)
    r = client.post("/api/print/start", json={})
    assert r.status_code == 409 and "thickness" in r.json()["detail"]


def test_run_to_done_with_auto_log_and_layers(client: TestClient) -> None:
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    r = client.post("/api/print/start", json={"dry_run": False})
    assert r.status_code == 200 and r.json()["state"] == "running"
    assert client.get("/api/status").json()["recording"]["active"] is True  # auto-log opened
    done = wait_print(client, "done")
    assert done["layer"] == 1 and done["part_height_mm"] == 1.0
    for _ in range(50):
        rec = client.get("/api/status").json()["recording"]
        if not rec["active"]:
            break
        time.sleep(0.05)
    assert rec["active"] is False  # auto-log closed on done
    runs = client.get("/api/recordings").json()["runs"]
    assert runs and runs[-1]["complete"] is True
    layers = client.get(f"/api/recordings/{runs[-1]['run']}/layers.csv").text.splitlines()
    assert len(layers) == 2 and ",1,printing,1.0," in layers[1]
    events = client.get(f"/api/recordings/{runs[-1]['run']}/events.json").json()
    labels = [e["label"] for e in events]
    assert "print_started" in labels and "layer_completed" in labels and "print_done" in labels


def test_pause_resume_abort(client: TestClient) -> None:
    client.put(
        "/api/print-settings", json={**FAST, "printing": {**FAST["printing"], "n_layers": 3}}
    )
    connect_arm(client)
    assert client.post("/api/print/start", json={}).status_code == 200
    assert client.post("/api/print/pause").status_code == 200
    wait_print(client, "paused")
    assert client.post("/api/print/resume").status_code == 200
    wait_print(client, "running")
    r = client.post("/api/print/abort")
    assert r.status_code == 200 and r.json()["state"] == "aborted"
    assert client.get("/api/status").json()["controller"]["heater"]["commanded_on"] is False


def test_dry_run_and_single_step(client: TestClient) -> None:
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    r = client.post("/api/print/start", json={"dry_run": True, "single_step": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    wait_print(client, "paused")
    assert client.post("/api/print/step").status_code == 200
    wait_print(client, "paused")
    assert client.post("/api/print/resume").status_code == 200
    wait_print(client, "done")


def test_auto_log_toggle(client: TestClient) -> None:
    assert client.get("/api/auto-log").json()["enabled"] is True
    assert client.put("/api/auto-log", json={"enabled": False}).json()["enabled"] is False
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    client.post("/api/print/start", json={"dry_run": True})
    assert client.get("/api/status").json()["recording"]["active"] is False


def test_estop_aborts_print_settings(client: TestClient) -> None:
    client.put(
        "/api/print-settings", json={**FAST, "printing": {**FAST["printing"], "n_layers": 5}}
    )
    connect_arm(client)
    client.post("/api/print/start", json={})
    client.post("/api/estop")
    s = wait_print(client, "aborted", timeout=5)
    assert "fault" in s["reason"]
