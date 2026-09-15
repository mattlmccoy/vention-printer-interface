import time
from collections.abc import Callable
from typing import Any

import pytest

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.safety import SafetyLimits
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.device.simulated import SimulatedTransport
from vention_printer_interface.protocol import routes as r

HEATER = r.io_output_topic(1, 2)


def make(**sim: Any) -> tuple[Controller, SimulatedTransport]:
    t = SimulatedTransport(realtime=True, **sim)
    c = Controller(poll_interval_s=0.05, limits=SafetyLimits())
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    return c, t


def wait(pred: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_attach_connects_and_polls() -> None:
    c, _ = make()
    try:
        assert c.state == ControllerState.CONNECTED
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        assert c.snapshot()["armed"] is False
        assert c.snapshot()["device"]["version"] == "2.14.1"
    finally:
        c.stop()


def test_positions_unreferenced_until_homed() -> None:
    # Incremental drives read ~0 after a power-cycle, NOT true position; until a home settles the
    # reported positions are unreferenced and must be flagged as such (never rendered as truth).
    c, _ = make()
    try:
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        assert c.snapshot()["telemetry"]["referenced"] == {
            "1": False, "2": False, "3": False, "4": False,
        }
        c.arm()
        c.home_all()
        assert wait(lambda: all(c.snapshot()["telemetry"]["referenced"].values()), timeout=6.0)
    finally:
        c.stop()


def test_reference_current_marks_all_axes_without_homing() -> None:
    # Operator-asserted reference: when the machine kept power and the reported positions are real,
    # mark EVERY axis referenced WITHOUT homing (no motion, no arming required). Only valid when
    # connected with settled telemetry.
    c, _ = make()
    try:
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        assert not any(c.snapshot()["telemetry"]["referenced"].values())  # unreferenced at connect
        pos = dict(c.snapshot()["telemetry"]["positions"])
        axes = c.reference_current()
        assert axes == {1, 2, 3, 4}
        assert all(c.snapshot()["telemetry"]["referenced"].values())
        assert c.snapshot()["telemetry"]["positions"] == pos  # nothing moved
    finally:
        c.stop()


def test_reference_current_refuses_while_moving() -> None:
    # Positions must be stable: refuse to reference mid-move (would trust a position in flight).
    c, _ = make()
    try:
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        c.arm()
        c.move_absolute(1, 60.0)  # a long move so motion is in progress
        assert wait(lambda: not all(c.snapshot()["telemetry"]["motion_complete"].values()))
        try:
            c.reference_current()
            raise AssertionError("expected reference_current to refuse while moving")
        except RuntimeError as exc:
            assert "settle" in str(exc) or "motion" in str(exc)
    finally:
        c.stop()


def test_reconcile_reference_keeps_matching_drops_moved() -> None:
    from vention_printer_interface.control.controller import reconcile_reference

    ref = {1, 2, 3, 4}
    saved = {1: 0.0, 2: 20.0, 3: 0.0, 4: 930.0}
    # MM stayed powered across a reconnect: positions unchanged -> keep every axis referenced.
    assert reconcile_reference(ref, saved, {1: 0.0, 2: 20.0, 3: 0.0, 4: 930.0}, 2.0) == {1, 2, 3, 4}
    # power-cycle: incremental drives collapse to ~0 -> only the axes that stayed put keep ref.
    assert reconcile_reference(ref, saved, {1: 0.0, 2: 0.1, 3: 0.0, 4: 0.1}, 2.0) == {1, 3}


def test_restore_reference_matches_saved_positions() -> None:
    # On reconnect the app restores reference for axes whose position is unchanged vs the saved
    # snapshot (the MM kept power); axes that moved (a power-cycle -> ~0) are not restored.
    c, _ = make()
    try:
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        pos = c.snapshot()["telemetry"]["positions"]
        c.restore_reference({1, 2, 3}, {1: pos["1"], 2: pos["2"], 3: pos["3"] + 500.0}, 2.0)
        ref = c.snapshot()["telemetry"]["referenced"]
        assert ref["1"] and ref["2"] and not ref["3"]  # 3's saved position no longer matches
    finally:
        c.stop()


def test_reference_state_getter_returns_axes_and_positions() -> None:
    c, _ = make()
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: all(c.snapshot()["telemetry"]["referenced"].values()), timeout=6.0)
        axes, positions = c.reference_state()
        assert axes == {1, 2, 3, 4} and set(positions) == {1, 2, 3, 4}
    finally:
        c.stop()


def test_reference_survives_a_reconnect_when_positions_unchanged() -> None:
    # A telemetry blip while the MM keeps power (positions unchanged on recovery) must NOT drop
    # reference — the "shows unref every reconnect" annoyance.
    c, t = make()
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: all(c.snapshot()["telemetry"]["referenced"].values()), timeout=6.0)
        t._unreachable = True  # reconnect gap
        assert wait(lambda: c.snapshot()["read_error"] is not None)
        t._unreachable = False  # back, positions unchanged (sim never power-cycles)
        assert wait(lambda: c.snapshot()["read_error"] is None)
        assert all(c.snapshot()["telemetry"]["referenced"].values())
    finally:
        c.stop()


def test_attach_failure_closes_device_and_raises() -> None:
    c = Controller(poll_interval_s=0.05)
    t = SimulatedTransport(realtime=True, unreachable=True)
    with pytest.raises(Exception):  # noqa: B017 - any transport failure must propagate
        c.attach_device(PrinterDevice(t), backend="simulated")
    assert c.state == ControllerState.DISCONNECTED
    c.stop()


def test_commands_refused_until_armed() -> None:
    c, _ = make()
    try:
        with pytest.raises(RuntimeError, match="not armed"):
            c.home_all()
        c.arm()
        c.home_all()
        assert c.snapshot()["armed"] is True
    finally:
        c.stop()


def test_move_is_clamped_and_speed_bounded() -> None:
    c, _ = make()
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: (c.snapshot()["telemetry"] or {}).get("positions", {}).get("3") == 0)
        assert c.set_max_speed(3, 99999) == SafetyLimits().max_speed[3]
        assert c.set_max_accel(3, 1e9) == SafetyLimits().max_accel[3]
        assert c.move_absolute(3, 5000) == 970.0
        assert wait(lambda: (c.snapshot()["telemetry"] or {})["positions"]["3"] > 100)
        c.stop_all()
        assert wait(lambda: all((c.snapshot()["telemetry"] or {})["motion_complete"].values()))
        assert c.move_relative(3, -99999) < 0
    finally:
        c.stop()


def test_estop_bypasses_gate_and_kills_heater() -> None:
    c, t = make()
    try:
        c.arm()
        c.heater_on()
        assert t.mqtt_latest(HEATER) == "1"
        c.estop()
        assert t.mqtt_latest(HEATER) == "0"
        assert c.snapshot()["armed"] is False
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert any("e-stop" in x.lower() for x in c.snapshot()["fault_reasons"])
    finally:
        c.stop()


def test_reset_drives_refuses_while_estop_asserted() -> None:
    # Re-energizing the drives is a software step, but only AFTER the physical E-STOP is released.
    c, _ = make()
    try:
        c.estop()
        assert wait(lambda: c.state == ControllerState.FAULT)
        with pytest.raises(RuntimeError, match="still engaged"):
            c.reset_drives()
    finally:
        c.stop()


def test_estop_release_then_clear_fault() -> None:
    c, t = make()
    try:
        c.estop()
        assert wait(lambda: c.state == ControllerState.FAULT)
        c.estop_release()
        t.advance(3.1)
        assert wait(lambda: (c.snapshot()["telemetry"] or {}).get("drives_ready") is True)
        assert wait(lambda: not (c.snapshot()["telemetry"] or {}).get("estop_triggered", True))
        assert wait(lambda: c.snapshot()["heater"]["on"] is False)
        c.clear_fault()
        assert c.state == ControllerState.CONNECTED
    finally:
        c.stop()


def test_estop_preserves_referenced_positions() -> None:
    # An e-stop triggers Safe-Torque-Off: it cuts MOTOR TORQUE, not the controller/encoder that
    # counts position. Referenced positions therefore SURVIVE an e-stop -- only a full power-cycle
    # loses them, and that path is handled on reconnect by reconcile_reference. Regression guard:
    # hitting the e-stop must NOT undefine the motor positions. This has regressed repeatedly
    # because nothing pinned it; the operator sees "positions undefined" the instant they e-stop.
    c, _ = make()
    try:
        c.arm()
        c.home_all()
        assert wait(lambda: all(c.snapshot()["telemetry"]["referenced"].values()), timeout=6.0)
        c.estop()
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert wait(lambda: (c.snapshot()["telemetry"] or {}).get("estop_triggered") is True)
        # torque was cut, position was not: every axis stays referenced through the e-stop
        assert all(c.snapshot()["telemetry"]["referenced"].values())
    finally:
        c.stop()


def test_unreachable_faults_and_clear_requires_clean() -> None:
    c, t = make()
    try:
        c.arm()
        c.heater_on()
        t._unreachable = True
        assert wait(lambda: c.state == ControllerState.FAULT)
        with pytest.raises(RuntimeError):
            c.clear_fault()
        t._unreachable = False
        assert wait(lambda: c.snapshot()["read_error"] is None)
        assert wait(lambda: t.mqtt_latest(HEATER) == "0")  # re-enforced once the link returns
        assert wait(lambda: c.snapshot()["heater"]["on"] is False)
        c.clear_fault()
        assert c.state == ControllerState.CONNECTED
        assert c.snapshot()["armed"] is False
    finally:
        c.stop()


def test_heater_watchdog_trips() -> None:
    c, t = make()
    c.set_limits(SafetyLimits(heater_max_on_s=5.0))
    try:
        c.arm()
        c.heater_on()
        c._heater_on_since = time.monotonic() - 10  # fast-forward the watchdog
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert t.mqtt_latest(HEATER) == "0"
    finally:
        c.stop()


def test_listener_receives_snapshots_and_exceptions_are_swallowed() -> None:
    c, _ = make()
    seen: list[dict[str, Any]] = []
    c.add_listener(seen.append)
    c.add_listener(lambda s: 1 / 0)
    try:
        assert wait(lambda: len(seen) > 2)
    finally:
        c.stop()


def test_detach_forces_heater_off_and_disconnects() -> None:
    c, t = make()
    c.arm()
    c.heater_on()
    c.detach_device()
    assert t.mqtt_latest(HEATER) == "0"
    assert c.state == ControllerState.DISCONNECTED
    c.stop()
    assert c.state == ControllerState.CLOSED


def test_ungated_safe_direction_commands() -> None:
    c, _ = make()
    try:
        c.stop_all()  # never gated
        c.heater_off()
        c.disarm()
    finally:
        c.stop()


def test_no_device_behaviour() -> None:
    c = Controller(poll_interval_s=0.05)
    with pytest.raises(RuntimeError, match="no device"):
        c.arm()
    c.estop()  # safe with no device
    c.heater_off()
    assert c.snapshot()["state"] == "disconnected"


def test_fast_poll_selects_print_interval() -> None:
    # During a print/recording the controller polls faster (finer motion data); idle uses the normal
    # interval. set_fast_poll flips between them; effective_poll_interval reports the active one.
    c = Controller(poll_interval_s=0.2, print_poll_interval_s=0.05)
    assert c.effective_poll_interval() == 0.2
    c.set_fast_poll(True)
    assert c.effective_poll_interval() == 0.05
    c.set_fast_poll(False)
    assert c.effective_poll_interval() == 0.2


def test_print_poll_interval_defaults_to_poll_interval_when_unset() -> None:
    # Not configured -> no behavior change: fast poll == normal poll.
    c = Controller(poll_interval_s=0.2)
    c.set_fast_poll(True)
    assert c.effective_poll_interval() == 0.2
