import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from vention_printer_interface.recording.recorder import (
    MOTION_PROFILE_FIELDS,
    Recorder,
    derive_run_status,
    layer_accuracy_rows,
    layer_accuracy_summary,
    motion_profile_rows,
)


def test_derive_run_status_finished_on_print_done() -> None:
    assert derive_run_status(["print_started", "print_done"], complete=True) == "finished"


def test_derive_run_status_aborted_on_print_aborted() -> None:
    assert derive_run_status(["print_started", "print_aborted"], complete=True) == "aborted"


def test_derive_run_status_fault_on_print_fault() -> None:
    assert derive_run_status(["print_started", "print_fault"], complete=True) == "fault"


def test_derive_run_status_estop_escalates_to_fault_over_abort() -> None:
    # An e-stop during a run is an emergency condition — it must read as a fault (danger), not a
    # graceful abort, even though the print controller also emits print_aborted in its wake.
    labels = ["print_started", "estop", "print_aborted"]
    assert derive_run_status(labels, complete=True) == "fault"


def test_derive_run_status_incomplete_when_started_but_no_terminal() -> None:
    # A run that began a print but recorded no terminal outcome (crashed/stopped mid-print) is
    # NOT healthy — it reads as incomplete, distinct from finished (data-contract §5).
    assert derive_run_status(["print_started", "layer_started"], complete=True) == "incomplete"


def test_derive_run_status_recorded_when_no_print() -> None:
    # A telemetry-only session (manual jogging / capture, no print) is neither pass nor fail.
    assert derive_run_status(["recording_started", "heater_on"], complete=True) == "recorded"


def test_derive_run_status_running_for_active_incomplete_run() -> None:
    # The live, still-recording run (no manifest yet) reads as running, not incomplete/crashed.
    assert derive_run_status(["print_started"], complete=False, active=True) == "running"


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
        "layer_accuracy.csv",
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
    # Run-dir names are timestamped to the second, so two runs that start within the SAME second
    # collide and the second is suffixed _2. A pinned (injected) clock makes this deterministic
    # regardless of test order/timing — with the real wall clock the two starts occasionally
    # straddled a 1-second boundary, giving b a fresh timestamp and no _2 (the flake).
    frozen = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    rec = Recorder(tmp_path, clock=lambda: frozen)
    a = rec.start("My Part!")
    rec.stop()
    b = rec.start("My Part!")
    rec.stop()
    assert a.name.endswith("_My_Part") and b.name.endswith("_My_Part_2")


def test_slug_no_collision_across_seconds(tmp_path: Path) -> None:
    # Two runs whose starts land in DIFFERENT seconds get distinct timestamps and do NOT collide,
    # so neither carries a _2 suffix. This pins the complement of test_slug_and_collision so the
    # naming's timing behavior can't silently regress.
    times = iter(
        [datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC), datetime(2026, 9, 17, 12, 0, 1, tzinfo=UTC)]
    )
    rec = Recorder(tmp_path, clock=lambda: next(times))
    a = rec.start("My Part!")
    rec.stop()
    b = rec.start("My Part!")
    rec.stop()
    assert a.name.endswith("_My_Part") and b.name.endswith("_My_Part")
    assert a.name != b.name


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


def test_list_runs_enriched_fields(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("Rich Run", notes="hello there", metadata={"backend": "simulated"})
    rec.record(_snap_at(0, 0.0))
    rec.record(_snap_at(2_000_000_000, 1.0))  # 2.0 s after the first telemetry row
    rec.record_layer({"layer": 1, "phase": "printing", "part_height_mm": 1.0, "elapsed_s": 1.0})
    rec.record_layer({"layer": 2, "phase": "printing", "part_height_mm": 2.0, "elapsed_s": 2.0})
    rec.stop()
    item = rec.list_runs()[0]
    # Existing fields are preserved.
    assert item["run"] == run.name
    assert item["complete"] is True
    assert item["size_bytes"] > 0
    # Enriched fields, read back from the durable run record.
    assert item["name"] == "Rich Run"
    assert item["notes"] == "hello there"
    assert isinstance(item["started_at"], str) and item["started_at"]
    assert item["layer_count"] == 2  # two layer rows recorded (layers.csv minus header)
    assert item["duration_s"] == 2.0  # (last - first) host_timestamp_ns / 1e9


def test_list_runs_includes_status_from_events(tmp_path: Path) -> None:
    # The runs list carries a derived outcome status so the UI needn't fetch each run's events.
    rec = Recorder(tmp_path)
    rec.start("Aborted Run", metadata={"backend": "simulated"})
    rec.event("print_started", {})
    rec.event("print_aborted", {"reason": "operator abort"})
    rec.stop()
    item = rec.list_runs()[0]
    assert item["status"] == "aborted"


def test_list_runs_surfaces_job_link_when_recorded(tmp_path: Path) -> None:
    # A run whose metadata records the printed job (going forward) surfaces the job folder/name so
    # the Runs card can show that job's preview thumbnail. Runs without a job link report None.
    rec = Recorder(tmp_path)
    rec.start("Linked", metadata={"job_folder": "20260909_120000_widget", "job_name": "widget"})
    rec.stop()
    rec.start("Manual", metadata={"backend": "simulated"})
    rec.stop()
    runs = {r["run"]: r for r in rec.list_runs()}
    linked = next(r for k, r in runs.items() if "Linked" in k)
    manual = next(r for k, r in runs.items() if "Manual" in k)
    assert linked["job_folder"] == "20260909_120000_widget"
    assert linked["job_name"] == "widget"
    assert manual["job_folder"] is None
    assert manual["job_name"] is None


def test_list_runs_bare_run_reports_nulls_without_error(tmp_path: Path) -> None:
    # A crashed/bare run dir (no metadata/telemetry/layers) must not raise.
    (tmp_path / "20260101_000000_bare").mkdir(parents=True)
    rec = Recorder(tmp_path)
    item = rec.list_runs()[0]
    assert item["run"] == "20260101_000000_bare"
    assert item["complete"] is False
    assert item["name"] == ""
    assert item["notes"] == ""
    assert item["started_at"] is None
    assert item["layer_count"] is None
    assert item["duration_s"] is None


def _tel(ts: int, pos1: float) -> dict[str, Any]:
    return {"host_timestamp_ns": ts, "pos_1": pos1}


def _lay(ts: int, layer: int, phase: str, cum_mm: float) -> dict[str, Any]:
    return {"host_timestamp_ns": ts, "layer": layer, "phase": phase, "part_height_mm": cum_mm}


def test_recorder_signals_active_change(tmp_path: Path) -> None:
    # The recorder announces start/stop so the controller can poll faster while a run records.
    events: list[bool] = []
    rec = Recorder(tmp_path, on_active_change=events.append)
    rec.start("x")
    rec.stop()
    assert events == [True, False]


def test_telemetry_csv_logs_native_speed(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("nspeed")
    s = _snap_at(0, 0.0)
    s["telemetry"]["actual_speed"] = {"1": 2.5, "2": 0.0, "3": 0.0, "4": 0.0}
    rec.record(s)
    rec.stop()
    lines = (run / "telemetry.csv").read_text().splitlines()
    header = lines[0].split(",")
    for a in (1, 2, 3, 4):
        assert f"vspeed_{a}" in header
    row = lines[1].split(",")
    assert float(row[header.index("vspeed_1")]) == 2.5


def test_telemetry_csv_native_speed_blank_when_absent(tmp_path: Path) -> None:
    # No actual_speed in the snapshot (old controller) -> blank cell, never a fabricated 0.
    rec = Recorder(tmp_path)
    run = rec.start("noneed")
    rec.record(_snap_at(0, 0.0))
    rec.stop()
    lines = (run / "telemetry.csv").read_text().splitlines()
    header = lines[0].split(",")
    assert lines[1].split(",")[header.index("vspeed_1")] == ""


def test_motion_profiles_prefer_native_speed() -> None:
    # When telemetry carries native vspeed_*, the profile uses it for velocity instead of the
    # finite difference of position (native is more accurate); accel = Δ(native vel)/Δt.
    rows = [
        {"host_timestamp_ns": 0, "pos_1": 0.0, "vspeed_1": 5.0},
        {"host_timestamp_ns": 500_000_000, "pos_1": 1.0, "vspeed_1": 9.0},  # Δpos→2.0, native→9.0
        {"host_timestamp_ns": 1_000_000_000, "pos_1": 3.0, "vspeed_1": 13.0},
    ]
    out = motion_profile_rows(rows)
    vel_i = MOTION_PROFILE_FIELDS.index("vel_1")
    accel_i = MOTION_PROFILE_FIELDS.index("accel_1")
    assert out[0][vel_i] == 9.0  # native, not the finite-diff 2.0
    assert out[1][vel_i] == 13.0
    assert out[1][accel_i] == (13.0 - 9.0) / 0.5  # accel from native velocity deltas


def test_layer_accuracy_commanded_vs_actual_build_height() -> None:
    # Build piston descends (pos_1 rises) as the part grows; actual layer height = settled Δpos_1
    # between layers; commanded = Δ of layers.csv part_height_mm. baseline = first sample.
    telem = [  # ts, actual pos_1: baseline 10.0, then settled per layer (cmd 0.2/0.2/2.0)
        _tel(0, 10.0),
        _tel(1_000_000_000, 10.19),  # layer 1: actual 0.19 (cmd 0.2)
        _tel(2_000_000_000, 10.40),  # layer 2: actual 0.21 (cmd 0.2)
        _tel(3_000_000_000, 12.42),  # layer 3: actual 2.02 (cmd 2.0)
    ]
    layers = [
        _lay(1_000_000_000, 1, "thin_precoat", 0.2),
        _lay(2_000_000_000, 2, "thin_precoat", 0.4),
        _lay(3_000_000_000, 3, "printing", 2.4),
    ]
    rows = layer_accuracy_rows(telem, layers, part_axis=1)
    assert [r["layer"] for r in rows] == [1, 2, 3]
    assert rows[0]["commanded_mm"] == pytest.approx(0.2)
    assert rows[0]["actual_mm"] == pytest.approx(0.19)
    assert rows[0]["deviation_mm"] == pytest.approx(-0.01)
    assert rows[1]["actual_mm"] == pytest.approx(0.21)
    assert rows[1]["deviation_mm"] == pytest.approx(0.01)
    assert rows[2]["commanded_mm"] == pytest.approx(2.0)
    assert rows[2]["actual_mm"] == pytest.approx(2.02)
    assert rows[2]["deviation_mm"] == pytest.approx(0.02)
    assert rows[2]["actual_cum_mm"] == pytest.approx(2.42)

    s = layer_accuracy_summary(rows)
    assert s["n"] == 3
    assert s["max_abs_dev_mm"] == pytest.approx(0.02)
    assert s["mean_abs_dev_mm"] == pytest.approx((0.01 + 0.01 + 0.02) / 3)


def test_layer_accuracy_first_layer_unknown_when_run_was_jumped() -> None:
    # Timeline-jump (debug-only): the recording starts mid-print, so the first executed layer's
    # per-layer increment can't be differenced against the (unrecorded) prior layer's cumulative.
    # It must be None — NOT a huge false error from prev_cum=0 (the observed "layer 6: actual 0.2 /
    # target 3.2 -> off by -3000um"). Cumulative is preserved; later layers difference normally.
    telem = [
        _tel(0, 10.0),  # baseline at the jump (piston already mid-build)
        _tel(1_000_000_000, 10.2),  # first executed layer: +0.2 actual
        _tel(2_000_000_000, 10.4),  # next: +0.2 actual
    ]
    layers = [
        _lay(1_000_000_000, 6, "printing", 3.2),  # cumulative commanded 3.2 at the jumped-to layer
        _lay(2_000_000_000, 7, "printing", 3.4),
    ]
    rows = layer_accuracy_rows(telem, layers, part_axis=1, jumped=True)
    assert rows[0]["commanded_mm"] is None
    assert rows[0]["actual_mm"] is None
    assert rows[0]["deviation_mm"] is None
    assert rows[0]["commanded_cum_mm"] == pytest.approx(3.2)  # cumulative kept
    # the next layer differences against the first row's cumulative -> correct 0.2 vs 0.2
    assert rows[1]["commanded_mm"] == pytest.approx(0.2)
    assert rows[1]["actual_mm"] == pytest.approx(0.2)
    assert rows[1]["deviation_mm"] == pytest.approx(0.0)
    # a NON-jumped run keeps the legacy behavior (first layer differenced from cum 0)
    assert layer_accuracy_rows(telem, layers, part_axis=1)[0]["commanded_mm"] == pytest.approx(3.2)


def test_run_was_jumped_reads_the_print_seeked_event(tmp_path: Path) -> None:
    from vention_printer_interface.recording.recorder import _run_was_jumped

    assert _run_was_jumped(tmp_path) is False  # no events.json
    (tmp_path / "events.json").write_text(
        json.dumps([{"label": "layer_started", "data": {"layer": 1}}])
    )
    assert _run_was_jumped(tmp_path) is False  # no seek
    (tmp_path / "events.json").write_text(
        json.dumps([{"label": "layer_started"}, {"label": "print_seeked", "data": {"index": 40}}])
    )
    assert _run_was_jumped(tmp_path) is True


def test_layer_accuracy_unknown_when_no_telemetry_in_window() -> None:
    # A layer with no telemetry sample in its window reports actual/deviation None, never a false 0.
    telem = [_tel(0, 5.0)]  # baseline only; nothing during the layers
    layers = [_lay(1_000_000_000, 1, "printing", 2.0)]
    rows = layer_accuracy_rows(telem, layers, part_axis=1)
    assert rows[0]["commanded_mm"] == pytest.approx(2.0)
    assert rows[0]["actual_mm"] is None
    assert rows[0]["deviation_mm"] is None
    assert layer_accuracy_summary(rows)["n"] == 0


def test_layer_accuracy_excludes_the_finish_move() -> None:
    # After the last layer the part is driven to part_max (the finish move); those samples are far
    # beyond the commanded stack and must NOT be read as the last layer's settled height.
    telem = [
        _tel(0, 10.0),                 # baseline
        _tel(1_000_000_000, 10.2),     # layer 1 settled (+0.2)
        _tel(2_000_000_000, 10.4),     # layer 2 settled (+0.2)
        _tel(2_500_000_000, 82.0),     # finish move to part_max (~72 above baseline) -> ignore
    ]
    layers = [_lay(1_000_000_000, 1, "printing", 0.2), _lay(2_000_000_000, 2, "printing", 0.4)]
    rows = layer_accuracy_rows(telem, layers)
    assert rows[1]["actual_mm"] == pytest.approx(0.2)       # not ~71.6
    assert rows[1]["actual_cum_mm"] == pytest.approx(0.4)
    assert rows[1]["deviation_mm"] == pytest.approx(0.0)


def test_layer_accuracy_samples_at_next_layer_start_not_completion_transient() -> None:
    # With a pre-heater drop/raise the piston swings ~1 mm within each layer, so the layer_completed
    # instant can catch a TRANSIENT position. Sampling at the NEXT layer's start (piston at rest,
    # before its drop) gives the true settled height. Here the completion samples are transients;
    # settled positions live at the layer_start timestamps.
    telem = [
        _tel(0, 10.0),                 # baseline (print start)
        _tel(1_000_000_000, 10.9),     # layer-1 COMPLETION instant — transient mid pre-heater swing
        _tel(1_800_000_000, 10.2),     # layer-2 START — settled: true layer-1 height (+0.2)
        _tel(2_000_000_000, 10.1),     # layer-2 COMPLETION instant — transient
        _tel(2_800_000_000, 10.4),     # layer-3 START — settled: true layer-2 height (+0.2)
        _tel(3_000_000_000, 11.0),     # layer-3 COMPLETION instant — transient
    ]
    layers = [
        _lay(1_000_000_000, 1, "printing", 0.2),
        _lay(2_000_000_000, 2, "printing", 0.4),
        _lay(3_000_000_000, 3, "printing", 0.6),
    ]
    starts = {2: 1_800_000_000, 3: 2_800_000_000}  # layer -> its layer_started timestamp
    rows = layer_accuracy_rows(telem, layers, part_axis=1, layer_start_ts=starts)
    # layer 1 settled = pos at layer-2 start (10.2 -> +0.2), NOT the completion transient (10.9)
    assert rows[0]["actual_mm"] == pytest.approx(0.2)
    assert rows[0]["actual_cum_mm"] == pytest.approx(0.2)
    # layer 2 settled = pos at layer-3 start (10.4) minus layer-1 settled (10.2) -> +0.2
    assert rows[1]["actual_mm"] == pytest.approx(0.2)


def test_layer_accuracy_csv_written_on_stop(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("accuracy")
    rec.record(_snap_at(0, 10.0))
    rec.record(_snap_at(1_000_000_000, 12.02))
    rec.record_layer({"layer": 1, "phase": "printing", "part_height_mm": 2.0, "elapsed_s": 1.0})
    rec.stop()
    lines = (run / "layer_accuracy.csv").read_text().splitlines()
    header = ["layer", "phase", "commanded_mm", "actual_mm", "deviation_mm"]
    assert lines[0].split(",")[:5] == header
    manifest = json.loads((run / "manifest.json").read_text())
    assert "layer_accuracy.csv" in manifest["checksums"]


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
