"""Regression tests for review findings C3, H1-H7, M2, M3 (all against the simulator)."""

import time
from collections.abc import Callable
from typing import Any

import pytest

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.safety import SafetyLimits
from vention_printer_interface.device.printer import PrinterDevice, Telemetry
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


def tel(c: Controller) -> dict[str, Any]:
    assert wait(lambda: c.snapshot()["telemetry"] is not None)
    return c.snapshot()["telemetry"]  # type: ignore[no-any-return]


# C3 ---------------------------------------------------------------------------------------------
def test_estop_latches_fault_itself_and_reports_steps() -> None:
    c, _ = make()
    try:
        tel(c)
        result = c.estop()
        assert c.state == ControllerState.FAULT  # immediately, not via the MQTT status topic
        assert result["ok"] is True and result["steps"]["estop_trigger"] == "ok"
    finally:
        c.stop()


def test_estop_reports_failed_steps() -> None:
    c, t = make()
    try:
        tel(c)
        t._unreachable = True
        result = c.estop()
        assert result["ok"] is False
        assert "failed" in result["steps"]["estop_trigger"]
        assert c.state == ControllerState.FAULT
    finally:
        c.stop()


# H1 ---------------------------------------------------------------------------------------------
def test_fault_state_is_set_before_stop_is_issued() -> None:
    """No window where an API move can slip in after the stop but before FAULT is latched."""
    c, _ = make()
    order: list[str] = []
    dev = c._device
    assert dev is not None
    real_stop = dev.stop_all

    def stop_spy() -> None:
        order.append(f"stop:{c.state.value}:{c.armed}")
        real_stop()

    dev.stop_all = stop_spy  # type: ignore[method-assign]
    try:
        tel(c)
        c.arm()
        c._enter_fault(("test",))
        assert order and order[0] == "stop:fault:False"
    finally:
        c.stop()


def test_faulted_reenforces_stop_while_motion_in_progress() -> None:
    c, t = make()
    try:
        tel(c)
        c.arm()
        t.http_post_json(r.max_speed_path(3), r.max_speed_body(5))
        c.move_absolute(3, 800)
        assert wait(lambda: t.machine.axes[3].target is not None)
        # inject a trip that does not itself stop motion at the transport level
        t.machine.axes[3].target = 800.0
        c._enter_fault(("test",))
        t.machine.axes[3].target = 800.0  # pretend the first stop was lost
        assert wait(lambda: t.machine.axes[3].target is None)  # re-enforced by the poll
    finally:
        c.stop()


# H2 / H3 ----------------------------------------------------------------------------------------
def test_disarm_clears_armed_even_if_heater_write_fails() -> None:
    c, t = make()
    try:
        tel(c)
        c.arm()
        t._unreachable = True
        with pytest.raises(Exception):  # noqa: B017 - heater_off raises; armed must still drop
            c.disarm()
        assert c.armed is False
    finally:
        c.stop()


def test_arm_requires_fresh_clean_sample_and_clear_fault_disarms() -> None:
    c = Controller(poll_interval_s=0.05)
    t = SimulatedTransport(realtime=True)
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    try:
        with c._lock:
            c._telemetry = None  # as if no poll has completed yet
            with pytest.raises(RuntimeError, match="telemetry"):
                c.arm()
        tel(c)
        c.arm()
        c._enter_fault(("test",))
        c.armed = True  # simulate the H3 race
        assert wait(lambda: c.snapshot()["heater"]["on"] is False)
        c.clear_fault()
        assert c.armed is False
    finally:
        c.stop()


# H4 ---------------------------------------------------------------------------------------------
def test_clear_fault_refuses_while_heater_on() -> None:
    c, t = make()
    try:
        tel(c)
        c.arm()
        c.heater_on()
        assert wait(lambda: c.snapshot()["heater"]["on"])
        c.state = ControllerState.FAULT  # fault without the stop actions (worst case)
        t._topics[HEATER] = "1"
        assert wait(lambda: c.snapshot()["telemetry"]["heater_on"] is True)
        with pytest.raises(RuntimeError, match="heater"):
            c.clear_fault()
    finally:
        c.stop()


# H5 ---------------------------------------------------------------------------------------------
def test_move_relative_requires_fresh_telemetry_and_idle_axis() -> None:
    c = Controller(poll_interval_s=0.05)
    t = SimulatedTransport(realtime=True)
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    try:
        c._telemetry = None
        c.armed = True
        with pytest.raises(RuntimeError, match="telemetry"):
            c.move_relative(3, -10)
        tel(c)
        c.home_all()
        assert wait(
            lambda: (
                all(c.snapshot()["telemetry"]["motion_complete"].values())
                and c.snapshot()["telemetry"]["positions"]["3"] == 0
            )
        )
        t.http_post_json(r.max_speed_path(3), r.max_speed_body(5))
        c.move_absolute(3, 100)
        assert wait(lambda: not c.snapshot()["telemetry"]["motion_complete"]["3"])
        with pytest.raises(RuntimeError, match="moving"):
            c.move_relative(3, 10)
    finally:
        c.stop()


# H6 ---------------------------------------------------------------------------------------------
def test_stale_age_is_measured_after_the_read() -> None:
    c, t = make()
    try:
        tel(c)
        t.read_delay_s = 0.5  # x5 GETs per sample = 2.5 s > telemetry_timeout_s=2.0
        assert wait(lambda: c.state == ControllerState.FAULT, timeout=8)
        assert any("stale" in x for x in c.snapshot()["fault_reasons"])
    finally:
        t.read_delay_s = 0.0
        c.stop()


# H7 ---------------------------------------------------------------------------------------------
def test_reattach_does_not_inherit_a_stuck_poll_thread_fault() -> None:
    c = Controller(poll_interval_s=0.05)
    slow = SimulatedTransport(realtime=True)
    c.attach_device(PrinterDevice(slow, heater_io=(1, 2)), backend="simulated")
    tel(c)
    slow.read_delay_s = 3.0  # the old thread will be stuck in a read while we detach
    time.sleep(0.2)
    fresh = SimulatedTransport(realtime=True)
    c.attach_device(PrinterDevice(fresh, heater_io=(1, 2)), backend="simulated")
    try:
        assert c.state == ControllerState.CONNECTED
        time.sleep(3.5)  # let the orphaned read finish and its thread exit
        assert c.state == ControllerState.CONNECTED
        assert c.snapshot()["read_error"] is None
    finally:
        slow.read_delay_s = 0.0
        c.stop()


# M2 ---------------------------------------------------------------------------------------------
def test_health_is_refreshed_when_enabled() -> None:
    # /health is slow on the real controller, so periodic refresh is opt-in (health_refresh_s).
    t = SimulatedTransport(realtime=True)
    c = Controller(poll_interval_s=0.05, limits=SafetyLimits(), health_refresh_s=0.1)
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    try:
        tel(c)
        t.health_reachable = False
        assert wait(lambda: c.state == ControllerState.FAULT, timeout=8)
        assert any("health" in x for x in c.snapshot()["fault_reasons"])
    finally:
        c.stop()


# M3 ---------------------------------------------------------------------------------------------
def test_estop_release_waits_for_drives_ready() -> None:
    c, _ = make()
    try:
        tel(c)
        c.estop()
        assert wait(lambda: c.snapshot()["telemetry"]["estop_triggered"] is True)
        t0 = time.monotonic()
        c.estop_release()
        assert time.monotonic() - t0 >= 2.5  # simulator re-energises after 3 s
        assert c.snapshot()["telemetry"]["drives_ready"] is True or wait(
            lambda: c.snapshot()["telemetry"]["drives_ready"] is True
        )
    finally:
        c.stop()


# unknown MQTT status is not healthy (C2, printer side) -----------------------------------------
def test_missing_estop_status_trips() -> None:
    c, t = make()
    try:
        tel(c)
        del t._topics[r.TOPIC_ESTOP_STATUS]
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert any("unknown" in x for x in c.snapshot()["fault_reasons"])
    finally:
        c.stop()


def test_heater_watchdog_uses_commanded_time_when_state_unobserved() -> None:
    c, t = make()
    c.set_limits(SafetyLimits(heater_max_on_s=5.0))
    try:
        tel(c)
        c.arm()
        c.heater_on()
        t.suppress_output_echo = True  # broker never echoes the output (C1 on real hardware)
        del t._topics[HEATER]
        c._heater_cmd_on_since = time.monotonic() - 10
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert any("heater" in x for x in c.snapshot()["fault_reasons"])
    finally:
        c.stop()


def test_telemetry_is_tristate() -> None:
    fields = Telemetry.__dataclass_fields__
    assert "None" in str(fields["heater_on"].type)
    assert "None" in str(fields["estop_triggered"].type)


# M4 ---------------------------------------------------------------------------------------------
def test_soft_limit_trip_through_simulator() -> None:
    c, t = make()
    c.set_limits(SafetyLimits.bounded(travel_max={"3": 100}))
    try:
        tel(c)
        c.arm()
        c.home_all()
        assert wait(lambda: c.snapshot()["telemetry"]["positions"]["3"] == 0)
        t.http_post_json(r.max_speed_path(3), r.max_speed_body(300))
        t.http_post_json(*r.move_absolute({3: 200}))  # bypass the clamp, like a stray command
        assert wait(lambda: c.state == ControllerState.FAULT)
        assert any("outside" in x for x in c.snapshot()["fault_reasons"])
    finally:
        c.stop()


def test_simulator_estop_on_boot_knob() -> None:
    t = SimulatedTransport(realtime=False, estop_on_boot=True)
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "false"
