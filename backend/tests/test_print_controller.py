import dataclasses
import time
from collections.abc import Callable
from typing import Any

import pytest

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.print_controller import PrintController
from vention_printer_interface.control.print_settings import PhasePlan, PrintSettings
from vention_printer_interface.control.safety import SafetyLimits
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.device.simulated import SimulatedTransport
from vention_printer_interface.protocol import routes as r

HEATER = r.io_output_topic(1, 2)


def fast_plan(n_print: int = 1, heater: bool = True) -> PrintSettings:
    """One tiny print the simulator finishes in a few seconds at the bounded speeds."""
    fast = PhasePlan(
        layer_thickness_mm=1.0,
        n_layers=0,
        part_speed=20,
        part_accel=100,
        feed_speed=20,
        feed_accel=100,
        printhead_speed=300,
        printhead_accel=2000,
        recoater_speed=300,
        recoater_accel=2000,
    )
    return PrintSettings(
        thin_precoat=dataclasses.replace(fast, n_layers=0),
        printing=dataclasses.replace(fast, n_layers=n_print),
        postcoat=dataclasses.replace(fast, n_layers=0),
        feed_end_mm=10,
        recoater_end_mm=30,
        heater_end_mm=20,
        printhead_end_mm=30,
        heater_speed=300,
        heater_accel=2000,
        heater_enabled=heater,
        settle_s=0.05,
        feed_fast_speed=20,
        feed_fast_accel=100,
    )


def make(**sim: Any) -> tuple[PrintController, Controller, SimulatedTransport]:
    t = SimulatedTransport(realtime=True, **sim)
    # Let the pistons run at the fast_plan's requested 20 mm/s (default limits clamp them to 5 mm/s,
    # which would throttle the finish's part->part_max move past the 3 s step timeout below).
    c = Controller(poll_interval_s=0.05, limits=SafetyLimits.bounded(max_speed={"1": 20, "2": 20}))
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    rc = PrintController(c, min_wait_s=0.1, step_timeout_s=3.0)
    c.add_listener(rc.tick)
    return rc, c, t


def wait(pred: Callable[[], bool], timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_start_requires_armed_and_valid() -> None:
    rc, c, _ = make()
    try:
        with pytest.raises(RuntimeError, match="not armed"):
            rc.start(fast_plan())
        c.arm()
        bad = dataclasses.replace(
            fast_plan(), printing=PhasePlan(layer_thickness_mm=2, n_layers=99)
        )
        with pytest.raises(RuntimeError, match="thickness"):
            rc.start(bad)
        assert rc.snapshot()["state"] == "idle"
    finally:
        c.stop()


def test_one_layer_runs_to_done_with_layer_events() -> None:
    rc, c, t = make()
    events: list[tuple[str, dict[str, Any]]] = []
    rc.on_event = lambda label, data: events.append((label, data))
    try:
        c.arm()
        rc.start(fast_plan())
        assert rc.snapshot()["state"] == "running"
        assert wait(lambda: rc.snapshot()["state"] == "done")
        labels = [e[0] for e in events]
        assert labels[0] == "print_started" and labels[-1] == "print_done"
        assert "layer_started" in labels and "layer_completed" in labels
        done = next(d for lbl, d in events if lbl == "layer_completed")
        assert done["layer"] == 1 and done["phase"] == "printing" and done["part_height_mm"] == 1.0
        assert t.mqtt_latest(HEATER) == "0"  # heater ended off
        assert any(lbl == "heater_on" for lbl, _ in events)
        snap = rc.snapshot()
        assert snap["step_index"] == snap["n_steps"] and snap["layer"] == 1
    finally:
        c.stop()


def test_dry_run_never_touches_heater() -> None:
    rc, c, t = make()
    seen: list[str] = []
    rc.on_event = lambda label, data: seen.append(label)
    try:
        c.arm()
        rc.start(fast_plan(), dry_run=True)
        assert wait(lambda: rc.snapshot()["state"] == "done")
        assert "heater_on" not in seen and t.mqtt_latest(HEATER) != "1"
        assert rc.snapshot()["dry_run"] is True
    finally:
        c.stop()


def test_pause_and_resume() -> None:
    rc, c, _ = make()
    try:
        c.arm()
        rc.start(fast_plan(n_print=2))
        assert wait(lambda: rc.snapshot()["step_index"] > 6)
        rc.pause()
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        idx = rc.snapshot()["step_index"]
        time.sleep(0.3)
        assert rc.snapshot()["step_index"] == idx  # no progress while paused
        rc.resume()
        assert wait(lambda: rc.snapshot()["state"] == "done")
    finally:
        c.stop()


def test_abort_stops_motion_and_heater() -> None:
    rc, c, t = make()
    try:
        c.arm()
        rc.start(fast_plan())
        assert wait(lambda: t.mqtt_latest(HEATER) == "1")
        rc.abort()
        assert rc.snapshot()["state"] == "aborted"
        assert t.mqtt_latest(HEATER) == "0"
        assert wait(lambda: all(t.machine.axes[n].target is None for n in t.machine.axes))
    finally:
        c.stop()


def test_controller_fault_aborts_printer() -> None:
    rc, c, t = make()
    try:
        c.arm()
        rc.start(fast_plan(n_print=3))
        assert wait(lambda: rc.snapshot()["step_index"] > 3)
        c.estop()
        assert wait(lambda: rc.snapshot()["state"] == "aborted")
        assert "fault" in rc.snapshot()["reason"] or "disarm" in rc.snapshot()["reason"]
        assert c.state == ControllerState.FAULT
    finally:
        c.stop()


def test_single_step_waits_for_step_calls() -> None:
    rc, c, _ = make()
    try:
        c.arm()
        rc.start(fast_plan(), single_step=True)
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        idx = rc.snapshot()["step_index"]
        rc.step()
        assert wait(lambda: rc.snapshot()["step_index"] > idx)
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        rc.resume()  # leave single-step mode
        assert wait(lambda: rc.snapshot()["state"] == "done")
    finally:
        c.stop()


def test_set_single_step_toggles_during_run() -> None:
    """Feature 2: flipping single_step ON mid-run pauses after the next step; OFF resumes."""
    rc, c, _ = make()
    try:
        c.arm()
        rc.start(fast_plan(n_print=2))
        assert wait(lambda: rc.snapshot()["step_index"] > 6)
        assert rc.snapshot()["state"] == "running"
        rc.set_single_step(True)  # arm single-step while continuously running
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        assert rc.snapshot()["single_step"] is True
        idx = rc.snapshot()["step_index"]
        time.sleep(0.3)
        assert rc.snapshot()["step_index"] == idx  # stays put until acted on
        rc.set_single_step(False)  # OFF resumes continuous running to done
        assert rc.snapshot()["single_step"] is False
        assert wait(lambda: rc.snapshot()["state"] == "done")
    finally:
        c.stop()


def test_seek_refuses_running_and_moves_when_paused() -> None:
    """Feature 3: seek is a paused-only jump; it clamps the target step index."""
    rc, c, _ = make()
    try:
        c.arm()
        rc.start(fast_plan(n_print=2))
        assert wait(lambda: rc.snapshot()["state"] == "running")
        with pytest.raises(RuntimeError, match="pause the print"):
            rc.seek(3)
        rc.pause()
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        n = rc.snapshot()["n_steps"]
        rc.seek(2)
        assert rc.snapshot()["step_index"] == 2
        rc.seek(10_000)  # clamps to n_steps
        assert rc.snapshot()["step_index"] == n
        rc.seek(-5)  # clamps to 0
        assert rc.snapshot()["step_index"] == 0
    finally:
        c.stop()


def test_wait_timeout_faults_printer() -> None:
    rc, c, t = make(stall_axis=4)  # recoater never moves
    try:
        c.arm()
        rc.start(fast_plan())
        assert wait(lambda: rc.snapshot()["state"] == "fault", timeout=15)
        assert "timeout" in rc.snapshot()["reason"]
        assert t.mqtt_latest(HEATER) == "0"
    finally:
        c.stop()


def test_snapshot_shape_idle() -> None:
    rc = PrintController(Controller(poll_interval_s=0.05))
    s = rc.snapshot()
    assert s["state"] == "idle" and s["n_steps"] == 0 and s["current_step"] is None
    assert set(s) >= {
        "state",
        "step_index",
        "n_steps",
        "phase",
        "layer",
        "n_layers",
        "part_height_mm",
        "elapsed_s",
        "dry_run",
        "single_step",
        "reason",
        "current_step",
        "plan",
    }


def test_macro_runs_on_the_step_machine_and_reports_name() -> None:
    from vention_printer_interface.control.macros import macro_steps

    rc, c, t = make()
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: (c.snapshot()["telemetry"] or {}).get("positions", {}).get("2") == 0)
        c.set_limits(SafetyLimits.bounded(travel_max={"1": 10, "2": 12}))  # short: fast test
        rc.start_macro("load_cart", macro_steps("load_cart", c.limits))
        s = rc.snapshot()
        assert s["state"] == "running" and s["macro"] == "load_cart" and s["plan"] is None
        assert wait(lambda: rc.snapshot()["state"] == "done", timeout=60)
        tel = c.snapshot()["telemetry"]
        assert tel["positions"]["1"] == 10.0 and tel["positions"]["2"] == 12.0
        assert tel["positions"]["3"] == 0.0 and tel["positions"]["4"] == 0.0
        with pytest.raises(RuntimeError):
            rc.start_macro("load_cart", ())  # empty is refused
    finally:
        c.stop()


def test_hold_step_pauses_until_resume() -> None:
    from vention_printer_interface.control.print_settings import Step

    rc, c, _ = make()
    try:
        c.arm()
        steps = (
            Step(0, "setup", 0, "mark", None, None, "start", 0.0),
            Step(1, "setup", 0, "hold", None, None, "Load powder, then Resume", 0.0),
            Step(2, "setup", 0, "mark", None, None, "end", 0.0),
        )
        rc.start_macro("test-hold", steps)
        assert wait(lambda: rc.snapshot()["state"] == "paused")
        assert rc.snapshot()["current_step"]["kind"] == "hold"
        rc.resume()
        assert wait(lambda: rc.snapshot()["state"] == "done")
    finally:
        c.stop()


def test_part_height_measured_from_piston_zero() -> None:
    rc, c, _ = make()
    # Primed start does NOT re-home the part: the zero is the primed piston position, and the build
    # height is measured relative to it. Capture the measured height at layer completion, because
    # the finish then ejects the part to part_max (so the end position is not the build height).
    measured_at_layer: list[float] = []
    rc.on_event = lambda label, data: (
        measured_at_layer.append(rc.snapshot()["part_height_measured_mm"])
        if label == "layer_completed"
        else None
    )
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: (c.snapshot()["telemetry"] or {}).get("positions", {}).get("1") == 0)
        c.move_absolute(1, 20)  # operator placed the build piston by hand
        assert wait(lambda: (c.snapshot()["telemetry"] or {})["positions"]["1"] == 20)
        rc.start(fast_plan())
        assert rc.snapshot()["part_zero_mm"] == 20.0  # zero captured at the primed position
        assert wait(lambda: rc.snapshot()["state"] == "done")
        # measured build height at the (only) layer completion == 1 layer x 1 mm, independent of the
        # operator's hand placement (20 mm) and of the finish's part->part_max eject.
        assert measured_at_layer and measured_at_layer[-1] == pytest.approx(1.0, abs=0.05)
        assert rc.snapshot()["part_height_mm"] == 1.0  # bookkept build height (compiler)
    finally:
        c.stop()
