import io
import json
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import _run_reveal_target, create_app


def test_run_reveal_target_points_at_metadata(tmp_path: Path) -> None:
    run = tmp_path / "20260101_000000_run"
    run.mkdir()
    (run / "metadata.json").write_text("{}")
    assert _run_reveal_target(tmp_path, "20260101_000000_run") == run / "metadata.json"


def test_run_reveal_target_falls_back_to_dir_without_metadata(tmp_path: Path) -> None:
    run = tmp_path / "20260101_000000_run"
    run.mkdir()
    assert _run_reveal_target(tmp_path, "20260101_000000_run") == run


def test_run_reveal_target_refuses_traversal(tmp_path: Path) -> None:
    (tmp_path / "20260101_000000_run").mkdir()
    with pytest.raises(ValueError, match="bad run"):
        _run_reveal_target(tmp_path, "../../etc")


def test_run_reveal_target_refuses_unknown_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bad run"):
        _run_reveal_target(tmp_path, "nope")


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield c


def wait_tel(c: TestClient) -> dict[str, Any]:
    for _ in range(100):
        s: dict[str, Any] = c.get("/api/status").json()
        if s["controller"]["telemetry"]:
            return s
        time.sleep(0.02)
    raise AssertionError("no telemetry")


def wait_state(c: TestClient, state: str) -> None:
    for _ in range(200):
        if c.get("/api/status").json()["controller"]["state"] == state:
            return
        time.sleep(0.02)
    raise AssertionError(f"never reached {state}")


def connect(c: TestClient, arm: bool = True) -> None:
    assert c.post("/api/connect", json={"backend": "simulated"}).status_code == 200
    if arm:
        assert c.post("/api/arm").status_code == 200


def test_recording_file_serves_layer_accuracy_csv(client: TestClient, tmp_path: Path) -> None:
    # Regression: layer_accuracy.csv must be in the served allowlist, else the Runs build-piston
    # chart fetches a 404 and shows "no data" even for a good run.
    run = tmp_path / "20260101_000000_run"
    run.mkdir(parents=True)
    (run / "layer_accuracy.csv").write_text(
        "layer,phase,commanded_mm,actual_mm,deviation_mm\n1,printing,0.2,0.2,0.0\n"
    )
    r = client.get("/api/recordings/20260101_000000_run/layer_accuracy.csv")
    assert r.status_code == 200
    assert "deviation_mm" in r.text


def test_recordings_report_capture_count(client: TestClient, tmp_path: Path) -> None:
    # The Analysis tab only lists runs that have something to analyze (vision captures). The
    # recordings list carries a per-run capture_count so the UI can filter without N extra calls.
    withcaps = tmp_path / "20260101_000000_withcaps" / "vision" / "layer_0001"
    withcaps.mkdir(parents=True)
    (withcaps / "post_jet.png").write_bytes(b"\x89PNG\r\n")
    (withcaps / "overview.png").write_bytes(b"\x89PNG\r\n")
    nocaps = tmp_path / "20260101_000001_nocaps"
    nocaps.mkdir(parents=True)
    (nocaps / "telemetry.csv").write_text("host_timestamp_ns\n1\n")
    runs = {r["run"]: r for r in client.get("/api/recordings").json()["runs"]}
    assert runs["20260101_000000_withcaps"]["capture_count"] == 2
    assert runs["20260101_000001_nocaps"]["capture_count"] == 0


def test_recording_reveal_returns_path_and_invokes_opener(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reveal endpoint returns the absolute metadata path and best-effort opens a file browser.
    import vention_printer_interface.api.app as appmod

    run = tmp_path / "20260101_000000_run"
    run.mkdir(parents=True)
    (run / "metadata.json").write_text("{}")
    calls: list[Any] = []
    monkeypatch.setattr(appmod.subprocess, "run", lambda *a, **k: calls.append(a))
    r = client.post("/api/recordings/20260101_000000_run/reveal")
    assert r.status_code == 200
    body = r.json()
    assert body["path"].endswith("metadata.json")
    assert body["revealed"] is True
    assert calls  # a file-browser opener was invoked


def test_recording_reveal_unknown_run_is_400(client: TestClient) -> None:
    r = client.post("/api/recordings/does_not_exist/reveal")
    assert r.status_code == 400


def test_science_frame_no_camera_is_5xx_not_500(client: TestClient) -> None:
    # The capture-pose calibration preview grabs a science still. With no usable science camera it
    # answers 503 (none configured) or 502 (configured but the grab failed) — never a 500 — so the
    # UI can show a clean "no science camera" state.
    r = client.get("/api/vision/science/frame.jpg")
    assert r.status_code in (502, 503)


def test_lane_b_reports_no_capture_honestly(client: TestClient, tmp_path: Path) -> None:
    # Lane B on a run with no captures returns an honest 200 {status: no_capture}, not a 500 —
    # checked before the job-folder lookup.
    run = tmp_path / "20260101_000000_lb"
    run.mkdir(parents=True)
    r = client.get("/api/analysis/20260101_000000_lb/lane-b", params={"layer": 1, "folder": "x"})
    assert r.status_code == 200
    assert r.json()["status"] == "no_capture"


def test_science_stream_refused_during_print(client: TestClient) -> None:
    # The science alignment stream holds the capture source open, so it is refused (409) while a
    # print/routine is running — checked before any camera access.
    from vention_printer_interface.control.print_controller import PrintState

    client.app.state.printer.state = PrintState.RUNNING  # type: ignore[attr-defined]
    r = client.get("/api/vision/science/stream")
    assert r.status_code == 409


def test_operator_restart_reexecs_when_idle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The in-app restart button re-execs the operator in place. Patch the actual exec away so the
    # test process survives; assert the endpoint acks and schedules exactly one restart.
    import vention_printer_interface.api.app as app_module

    calls: list[int] = []
    monkeypatch.setattr(app_module, "schedule_operator_restart", lambda *a, **k: calls.append(1))
    r = client.post("/api/operator/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert calls == [1]


def test_operator_restart_refused_while_printing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Never drop an in-progress build: restart is refused while a print is RUNNING or PAUSED, and
    # the exec is never scheduled.
    import vention_printer_interface.api.app as app_module
    from vention_printer_interface.control.print_controller import PrintState

    called: list[int] = []
    monkeypatch.setattr(app_module, "schedule_operator_restart", lambda *a, **k: called.append(1))
    client.app.state.printer.state = PrintState.RUNNING  # type: ignore[attr-defined]
    r = client.post("/api/operator/restart")
    assert r.status_code == 409
    assert called == []


def test_reference_current_endpoint_references_without_homing(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    before = client.get("/api/status").json()["controller"]["telemetry"]["referenced"]
    assert not any(before.values())  # unreferenced at connect
    r = client.post("/api/reference/current")
    assert r.status_code == 200
    after = r.json()["controller"]["telemetry"]["referenced"]
    assert all(after.values())  # every axis now referenced, no homing move issued


def test_health(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["api_version"] == "0.1" and h["backend"] == "none"


def test_status_idle(client: TestClient) -> None:
    s = client.get("/api/status").json()
    assert s["controller"]["state"] == "disconnected"
    assert s["recording"] == {"active": False, "run": None}
    assert s["device"] == {}


def test_discovery_lists_simulated(client: TestClient) -> None:
    d = client.get("/api/discovery").json()
    assert any(c["backend"] == "simulated" for c in d["candidates"])
    assert any(c.get("ip") == "192.168.0.2" for c in d["candidates"])


def test_connect_simulated_and_arm_flow(client: TestClient) -> None:
    r = client.post("/api/connect", json={"backend": "simulated"})
    assert r.status_code == 200 and r.json()["controller"]["state"] == "connected"
    assert client.post("/api/motion/home", json={"axes": []}).status_code == 409
    assert client.post("/api/arm").status_code == 200
    assert client.post("/api/motion/home", json={"axes": []}).status_code == 200
    wait_tel(client)
    r = client.post("/api/motion/move", json={"axis": 3, "mode": "abs", "mm": 9999})
    assert r.status_code == 200 and r.json()["applied_mm"] == 970.0
    assert client.post("/api/motion/stop", json={}).status_code == 200
    assert client.post("/api/disconnect").status_code == 200
    assert client.get("/api/status").json()["controller"]["state"] == "disconnected"


def test_connect_unknown_backend_400(client: TestClient) -> None:
    assert client.post("/api/connect", json={"backend": "nope"}).status_code == 400


def test_connect_unreachable_controller_503(client: TestClient) -> None:
    r = client.post("/api/connect", json={"backend": "machinemotion", "ip": "192.0.2.1"})
    assert r.status_code == 503


def test_axis_motion_settings_have_bounds(client: TestClient) -> None:
    connect(client)
    r = client.put("/api/axes/3/motion", json={"max_speed": 5000, "max_accel": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["max_speed"] == 200.0 and "bounds" in body
    assert client.put("/api/axes/9/motion", json={"max_speed": 1}).status_code == 400


def test_safety_limits_get_put(client: TestClient) -> None:
    g = client.get("/api/safety-limits").json()
    assert "bounds" in g and g["heater_max_on_s"] == 120.0
    r = client.put("/api/safety-limits", json={"heater_max_on_s": 30})
    assert r.json()["heater_max_on_s"] == 30.0
    assert client.get("/api/status").json()["controller"]["heater"]["max_on_s"] == 30.0


def test_heater_requires_arm_and_off_is_ungated(client: TestClient) -> None:
    connect(client, arm=False)
    assert client.post("/api/heater/on").status_code == 409
    assert client.post("/api/heater/off").status_code == 200
    client.post("/api/arm")
    assert client.post("/api/heater/on").status_code == 200
    for _ in range(50):
        if client.get("/api/status").json()["controller"]["heater"]["on"]:
            break
        time.sleep(0.02)
    assert client.get("/api/status").json()["controller"]["heater"]["on"] is True
    assert client.post("/api/disarm").status_code == 200
    for _ in range(50):
        if not client.get("/api/status").json()["controller"]["heater"]["on"]:
            break
        time.sleep(0.02)
    assert client.get("/api/status").json()["controller"]["heater"]["on"] is False


def test_estop_and_release(client: TestClient) -> None:
    connect(client)
    r = client.post("/api/estop")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["steps"]["estop_trigger"] == "ok"
    assert client.get("/api/status").json()["controller"]["state"] == "fault"  # latched itself
    assert client.post("/api/clear-fault").status_code == 409
    assert client.post("/api/estop/release").status_code == 200  # waits for drives ready
    for _ in range(100):
        s = client.get("/api/status").json()["controller"]
        if s["telemetry"]["estop_triggered"] is False and s["heater"]["on"] is False:
            break
        time.sleep(0.05)
    assert client.post("/api/clear-fault").status_code == 200
    assert client.get("/api/status").json()["controller"]["state"] == "connected"


def test_recording_flow(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    r = client.post("/api/recording/start", json={"name": "run A", "notes": ""})
    assert r.status_code == 200
    assert client.post("/api/recording/start", json={"name": "x"}).status_code == 409
    assert client.get("/api/recording/status").json()["active"] is True
    time.sleep(0.2)
    stop = client.post("/api/recording/stop").json()
    runs = client.get("/api/recordings").json()["runs"]
    assert runs[0]["run"] == stop["run"] and runs[0]["complete"] is True
    assert client.get(f"/api/recordings/{stop['run']}/telemetry.csv").status_code == 200
    # motion_profiles.csv is derived at stop and served by the same run-file route.
    mp = client.get(f"/api/recordings/{stop['run']}/motion_profiles.csv")
    assert mp.status_code == 200
    assert mp.text.splitlines()[0].startswith("host_timestamp_ns,pos_1")
    assert client.get(f"/api/recordings/{stop['run']}/secret.txt").status_code == 404
    assert client.get("/api/recordings/nope/telemetry.csv").status_code == 400


def test_recording_delete_removes_the_run(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.post("/api/recording/start", json={"name": "to delete", "notes": ""})
    time.sleep(0.2)
    run = client.post("/api/recording/stop").json()["run"]
    assert any(r["run"] == run for r in client.get("/api/recordings").json()["runs"])
    assert client.delete(f"/api/recordings/{run}").status_code == 200
    assert all(r["run"] != run for r in client.get("/api/recordings").json()["runs"])
    # deleting again / an unknown run is a clean error, not a crash
    assert client.delete("/api/recordings/nope").status_code in (400, 404)


def test_recording_delete_refuses_active_run(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.post("/api/recording/start", json={"name": "live", "notes": ""})
    run = client.get("/api/recording/status").json().get("run")
    assert run is not None
    # can't delete the run that's currently recording
    assert client.delete(f"/api/recordings/{run}").status_code == 409
    client.post("/api/recording/stop")


def test_recording_archive_zip(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.post("/api/recording/start", json={"name": "zip run", "notes": ""})
    time.sleep(0.2)
    stop = client.post("/api/recording/stop").json()
    run = stop["run"]

    r = client.get(f"/api/recordings/{run}/archive.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert zf.testzip() is None  # valid zip
    names = {n.split("/")[-1] for n in zf.namelist()}
    assert {
        "telemetry.csv",
        "motion_profiles.csv",
        "events.json",
        "manifest.json",
        "layers.csv",
        "metadata.json",
    } <= names
    # traversal / unknown run is rejected the same way the run-file route rejects it.
    assert client.get("/api/recordings/nope/archive.zip").status_code == 400


def test_recording_meta_update_roundtrips(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.post("/api/recording/start", json={"name": "orig", "notes": "orig notes"})
    time.sleep(0.2)
    run = client.post("/api/recording/stop").json()["run"]

    r = client.put(f"/api/recordings/{run}/meta", json={"name": "renamed", "notes": "new notes"})
    assert r.status_code == 200
    assert r.json() == {"name": "renamed", "notes": "new notes"}

    # The edit round-trips through the enriched recordings list.
    item = next(x for x in client.get("/api/recordings").json()["runs"] if x["run"] == run)
    assert item["name"] == "renamed" and item["notes"] == "new notes"


def test_recording_meta_partial_preserves_other_keys(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.post("/api/recording/start", json={"name": "orig", "notes": "n"})
    time.sleep(0.2)
    run = client.post("/api/recording/stop").json()["run"]
    root: Path = client.app.state.experiments_root  # type: ignore[attr-defined]
    before = json.loads((root / run / "metadata.json").read_text())

    # Only notes provided: name preserved, and unrelated metadata untouched.
    r = client.put(f"/api/recordings/{run}/meta", json={"notes": "only notes"})
    assert r.status_code == 200
    assert r.json() == {"name": "orig", "notes": "only notes"}
    after = json.loads((root / run / "metadata.json").read_text())
    assert after["software"] == before["software"]
    assert after["format_version"] == before["format_version"]
    assert after["experiment"]["backend"] == before["experiment"]["backend"]


def test_recording_meta_unknown_run_404(client: TestClient) -> None:
    assert client.put("/api/recordings/nope/meta", json={"name": "x"}).status_code == 404


def test_resolve_run_dir_rejects_traversal(tmp_path: Path) -> None:
    from fastapi import HTTPException

    from vention_printer_interface.api.app import _resolve_run_dir

    with pytest.raises(HTTPException) as exc:
        _resolve_run_dir(tmp_path, "..")
    assert exc.value.status_code == 400


def test_estop_reports_502_when_controller_unreachable(client: TestClient) -> None:
    connect(client, arm=False)
    wait_tel(client)
    client.app.state.controller._device._t._unreachable = True  # type: ignore[attr-defined]
    r = client.post("/api/estop")
    assert r.status_code == 502 and r.json()["ok"] is False
    assert "failed" in r.json()["steps"]["estop_trigger"]


def test_disconnect_stops_recording(client: TestClient) -> None:
    connect(client, arm=False)
    client.post("/api/recording/start", json={"name": "r"})
    client.post("/api/disconnect")
    assert client.get("/api/recording/status").json()["active"] is False


def test_ws_telemetry_pushes_status(client: TestClient) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        msg = ws.receive_json()
        assert msg["controller"]["state"] == "disconnected"
        assert "recording" in msg


def test_boot_with_simulated_backend(tmp_path: Path) -> None:
    app = create_app(backend="simulated", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        assert c.get("/api/status").json()["controller"]["state"] == "connected"
        assert c.get("/api/health").json()["backend"] == "simulated"
