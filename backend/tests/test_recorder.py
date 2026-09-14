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
    assert set(manifest["checksums"]) == {
        "metadata.json",
        "events.json",
        "telemetry.csv",
        "layers.csv",
        "motion_profiles.csv",
    }
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


def test_current_run_dir_tracks_active_run(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    assert rec.current_run_dir is None
    run = rec.start("vision")
    assert rec.current_run_dir == run
    assert rec.current_run_dir is not None and rec.current_run_dir.exists()
    rec.stop()
    assert rec.current_run_dir is None


def _snap_at(ts_ns: int, z: float) -> dict[str, Any]:
    d = snap(z)
    d["telemetry"]["host_timestamp_ns"] = ts_ns
    return d


def test_motion_profiles_csv_finite_differences(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("motion")
    # Three telemetry rows 0.5 s apart; axis 1 moves 1 mm then 2 mm.
    rec.record(_snap_at(0, 0.0))
    rec.record(_snap_at(500_000_000, 1.0))  # +1 mm / 0.5 s -> vel 2.0 mm/s
    rec.record(_snap_at(1_000_000_000, 3.0))  # +2 mm / 0.5 s -> vel 4.0; accel (4-2)/0.5 = 4.0
    assert rec.stop() == run

    lines = (run / "motion_profiles.csv").read_text().splitlines()
    header = lines[0].split(",")
    assert header[0] == "host_timestamp_ns"
    for axis in (1, 2, 3, 4):
        assert f"pos_{axis}" in header
        assert f"vel_{axis}" in header
        assert f"accel_{axis}" in header
    # 3 telemetry rows -> 2 motion rows (the first is dropped; it has no prior row for Δ).
    assert len(lines) == 3

    def cell(row: list[str], col: str) -> str:
        return row[header.index(col)]

    r1 = lines[1].split(",")
    r2 = lines[2].split(",")
    assert float(cell(r1, "pos_1")) == 1.0
    assert float(cell(r1, "vel_1")) == 2.0  # finite difference of positions
    assert cell(r1, "accel_1") == ""  # no prior velocity yet
    assert float(cell(r2, "pos_1")) == 3.0
    assert float(cell(r2, "vel_1")) == 4.0
    assert float(cell(r2, "accel_1")) == 4.0

    manifest = json.loads((run / "manifest.json").read_text())
    assert "motion_profiles.csv" in manifest["checksums"]


def test_layers_csv(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("layers")
    rec.record_layer({"layer": 1, "phase": "printing", "part_height_mm": 2.0, "elapsed_s": 3.5})
    rec.stop()
    lines = (run / "layers.csv").read_text().splitlines()
    assert lines[0] == "host_timestamp_ns,layer,phase,part_height_mm,elapsed_s"
    assert lines[1].endswith(",1,printing,2.0,3.5")
    manifest = json.loads((run / "manifest.json").read_text())
    assert "layers.csv" in manifest["checksums"]
