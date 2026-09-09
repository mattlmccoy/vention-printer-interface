import json
from pathlib import Path
from typing import Any

from vention_printer_interface.recording.recorder import Recorder


def snap(z: float = 1.0, heater: bool = False) -> dict[str, Any]:
    return {
        "state": "connected",
        "armed": True,
        "heater": {"on": heater, "on_s": 0},
        "telemetry": {
            "host_timestamp_ns": 1,
            "positions": {"1": z, "2": 0, "3": 0, "4": 0},
            "motion_complete": {"1": True, "2": True, "3": True, "4": True},
            "estop_triggered": False,
            "drives_ready": True,
            "health_ok": True,
            "heater_on": heater,
        },
    }


def test_layout_and_manifest_on_clean_stop(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("Test Run", notes="n", metadata={"backend": "simulated"})
    assert (run / "metadata.json").exists()
    meta = json.loads((run / "metadata.json").read_text())
    assert meta["experiment"]["backend"] == "simulated"
    rec.record(snap(1.0))
    rec.record(snap(2.0))
    rec.event("layer_completed", {"layer": 1})
    assert rec.stop() == run
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["complete"] is True and manifest["sample_count"] == 2
    assert set(manifest["checksums"]) == {"metadata.json", "events.json", "telemetry.csv"}
    lines = (run / "telemetry.csv").read_text().splitlines()
    assert lines[0].startswith("host_timestamp_ns,controller_state,armed,pos_1,pos_2,pos_3,pos_4")
    assert len(lines) == 3
    events = json.loads((run / "events.json").read_text())
    labels = [e["label"] for e in events]
    assert labels == ["recording_started", "layer_completed", "recording_stopped"]


def test_missing_manifest_means_incomplete(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("crash")
    rec.record(snap())
    assert not (run / "manifest.json").exists()
    runs = rec.list_runs()
    assert runs[0]["run"] == run.name and runs[0]["complete"] is False
    assert runs[0]["size_bytes"] > 0


def test_slug_and_collision(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    a = rec.start("My Part!")
    rec.stop()
    b = rec.start("My Part!")
    rec.stop()
    assert a.name.endswith("_My_Part") and b.name.endswith("_My_Part_2")


def test_record_and_event_ignored_when_idle(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.record(snap())
    rec.event("x")
    assert rec.active is None and rec.stop() is None
    assert rec.list_runs() == []


def test_double_start_refused(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.start("a")
    try:
        rec.start("b")
    except RuntimeError as exc:
        assert "already" in str(exc)
    else:
        raise AssertionError("second start should be refused")
