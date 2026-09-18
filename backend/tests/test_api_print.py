import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app

FAST: dict[str, Any] = {
    "thin_precoat": {"n_layers": 0},
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
    # A print now requires a captured primed bed; capture it once the controller is live.
    assert c.post("/api/primed/capture").status_code == 200


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
    assert r["validation"] == [] and r["n_steps"] > 0 and r["total_layers"] == 13
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


def _wait_ref(c: TestClient, pred: Any, timeout: float = 8.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        t = c.get("/api/status").json()["controller"]["telemetry"]
        if t and pred(t["referenced"]):
            return t
        time.sleep(0.05)
    raise AssertionError(f"reference predicate never met: {c.get('/api/status').json()['print']}")


def test_reference_restored_after_software_reconnect(client: TestClient, tmp_path: Path) -> None:
    # A real MM keeps power and its positions across a software disconnect. The simulator instead
    # resets to 50 on each connect, so to model "positions unchanged" we park every axis at 50
    # while referenced; on reconnect the positions match the saved reference and it is restored.
    connect_arm(client)
    _wait_ref(client, lambda r: not any(r.values()))  # fresh connect is unreferenced
    client.post("/api/motion/home", json={"axes": []})
    _wait_ref(client, lambda r: all(r.values()))  # homing references every axis
    for a in (1, 2, 3, 4):
        client.post("/api/motion/move", json={"axis": a, "mode": "abs", "mm": 50.0})

    def parked() -> bool:
        t = client.get("/api/status").json()["controller"]["telemetry"]
        return bool(t) and all(abs(t["positions"][str(a)] - 50.0) < 1.0 for a in (1, 2, 3, 4))

    end = time.monotonic() + 8
    while time.monotonic() < end and not parked():
        time.sleep(0.05)
    assert parked()
    _wait_ref(client, lambda r: all(r.values()))  # moving does not drop reference
    assert (tmp_path / ".reference.json").exists()

    client.post("/api/disconnect")
    assert client.post("/api/connect", json={"backend": "simulated"}).status_code == 200
    t = _wait_ref(client, lambda r: all(r.values()), timeout=4.0)  # restored, not unref
    assert all(t["referenced"].values()), t["referenced"]


def test_partial_patch_preserves_unmentioned_routine_fields(client: TestClient) -> None:
    # The UI editors send partial patches; a later partial patch must NOT reset routine fields it
    # omits (multipass n_jet_passes, pre_heater_drop_mm) — the clobber that silently disabled them.
    client.put("/api/print-settings", json={"n_jet_passes": 3, "pre_heater_drop_mm": 4.0})
    body = client.put("/api/print-settings", json={"printing": {"n_layers": 5}}).json()
    assert body["plan"]["n_jet_passes"] == 3
    assert body["plan"]["pre_heater_drop_mm"] == 4.0
    assert body["plan"]["printing"]["n_layers"] == 5


def connect_arm_no_prime(c: TestClient) -> None:
    """Connect + arm but do NOT capture the primed bed (for the require-primed guard test)."""
    assert c.post("/api/connect", json={"backend": "simulated"}).status_code == 200
    for _ in range(100):
        if c.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    assert c.post("/api/arm").status_code == 200


def test_start_requires_primed_bed(client: TestClient) -> None:
    client.put("/api/print-settings", json=FAST)
    connect_arm_no_prime(client)
    # armed + valid settings, but no primed bed captured yet -> refused with a prime-the-bed detail
    r = client.post("/api/print/start", json={})
    assert r.status_code == 409 and "prime" in r.json()["detail"].lower()
    # capture the primed bed, then the start proceeds (no longer a 409)
    assert client.post("/api/primed/capture").status_code == 200
    ok = client.post("/api/print/start", json={})
    assert ok.status_code != 409


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
    r = client.post("/api/print/start", json={})
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


def test_single_step(client: TestClient) -> None:
    # Dry run removed (#3); single-step (debug) remains: start paused, advance one step at a time.
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    r = client.post("/api/print/start", json={"single_step": True})
    assert r.status_code == 200 and r.json()["single_step"] is True
    wait_print(client, "paused")
    assert client.post("/api/print/step").status_code == 200
    wait_print(client, "paused")
    assert client.post("/api/print/resume").status_code == 200
    wait_print(client, "done")


def test_single_step_route_toggles_during_run(client: TestClient) -> None:
    client.put(
        "/api/print-settings", json={**FAST, "printing": {**FAST["printing"], "n_layers": 2}}
    )
    connect_arm(client)
    assert client.post("/api/print/start", json={}).status_code == 200
    wait_print(client, "running")
    r = client.post("/api/print/single-step", json={"on": True})
    assert r.status_code == 200 and r.json()["single_step"] is True
    wait_print(client, "paused")
    r = client.post("/api/print/single-step", json={"on": False})
    assert r.status_code == 200 and r.json()["single_step"] is False
    wait_print(client, "done")


def test_steps_route_lists_compiled_steps(client: TestClient) -> None:
    # Idle (no print loaded): the controller has no compiled steps yet.
    assert client.get("/api/print/steps").json()["steps"] == []
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    assert client.post("/api/print/start", json={}).status_code == 200
    r = client.get("/api/print/steps")
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert steps and all(
        set(s) == {"index", "phase", "layer", "kind", "axis", "value", "label"} for s in steps
    )
    assert [s["index"] for s in steps] == list(range(len(steps)))  # dense, ordered


def test_seek_route_paused_only(client: TestClient) -> None:
    client.put(
        "/api/print-settings", json={**FAST, "printing": {**FAST["printing"], "n_layers": 2}}
    )
    connect_arm(client)
    assert client.post("/api/print/start", json={}).status_code == 200
    wait_print(client, "running")
    assert client.post("/api/print/seek", json={"index": 3}).status_code == 409  # not paused
    client.post("/api/print/pause")
    wait_print(client, "paused")
    r = client.post("/api/print/seek", json={"index": 4})
    assert r.status_code == 200 and r.json()["step_index"] == 4


def test_auto_log_toggle(client: TestClient) -> None:
    assert client.get("/api/auto-log").json()["enabled"] is True
    assert client.put("/api/auto-log", json={"enabled": False}).json()["enabled"] is False
    client.put("/api/print-settings", json=FAST)
    connect_arm(client)
    client.post("/api/print/start", json={})
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


def test_print_settings_payload_has_exposure(client: TestClient) -> None:
    d = client.get("/api/print-settings").json()
    ex = d["exposure"]
    assert ex["energy_j"] > 0 and ex["time_s"] > 0 and ex["sweep_speed_mm_s"] > 0
