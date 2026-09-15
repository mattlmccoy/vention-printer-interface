import pytest

from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.printer import AxisConfig, PrinterDevice, Telemetry
from vention_printer_interface.device.simulated import SimulatedTransport


def make() -> tuple[PrinterDevice, SimulatedTransport]:
    t = SimulatedTransport(realtime=False)
    return PrinterDevice(t, heater_io=(1, 2)), t


def test_identify_reads_version_and_axes() -> None:
    d, _ = make()
    info = d.identify()
    assert info["version"] == "2.14.1"
    assert info["async_supported"] is True
    assert [a.name for a in d.axes.values()] == [
        "Build Piston",
        "Feed Piston",
        "Printhead Gantry",
        "Recoater Gantry",
    ]
    assert info["axes"]["3"]["travel_mm"] == 970.0


def test_read_telemetry_shape() -> None:
    d, t = make()
    d.identify()
    d.home_all()
    t.advance(60)
    tel = d.read_telemetry()
    assert isinstance(tel, Telemetry)
    assert tel.positions == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    assert tel.motion_complete == {1: True, 2: True, 3: True, 4: True}
    assert tel.estop_triggered is False and tel.drives_ready is True
    assert tel.health_ok is True
    assert tel.heater_on is None  # never written, never observed: unknown, not "off"
    d.heater_write(False)
    assert d.read_telemetry().heater_on is False


def test_read_telemetry_native_actual_speed() -> None:
    # The MM2 reports native actual speed (/smartDrives/get/actualSpeed). read_telemetry logs it in
    # Telemetry.actual_speed (signed mm/s); a settled axis reports 0.0.
    d, t = make()
    d.identify()
    d.home_all()
    t.advance(60)
    assert d.read_telemetry().actual_speed == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}  # all settled
    d.set_max_speed(1, 3.0)
    d.move_absolute(1, 40.0)  # axis 1 now moving up-position at 3.0 mm/s (target > position 0)
    tel = d.read_telemetry()
    assert tel.actual_speed[1] == pytest.approx(3.0)
    assert tel.actual_speed[2] == 0.0


def test_read_telemetry_native_speed_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    # If the actual-speed endpoint errors (old MM software / transient), telemetry still returns and
    # actual_speed is empty -- unknown, never fabricated.
    d, t = make()
    d.identify()
    real_get = t.http_get

    def flaky(path: str, *, timeout_s: float | None = None) -> bytes:
        if path.endswith("actualSpeed"):
            raise TransportError("actualSpeed unsupported")
        return real_get(path, timeout_s=timeout_s)

    monkeypatch.setattr(t, "http_get", flaky)
    tel = d.read_telemetry()
    assert tel.actual_speed == {}
    assert tel.positions  # the rest of telemetry is intact


def test_move_and_speed() -> None:
    d, t = make()
    d.home_all()
    t.advance(60)
    d.set_max_speed(3, 100)
    d.set_max_accel(3, 500)
    d.move_absolute(3, 50)
    t.advance(1)
    assert d.read_telemetry().positions[3] == pytest.approx(50)
    d.move_relative(3, -20)
    t.advance(1)
    assert d.read_telemetry().positions[3] == pytest.approx(30)
    assert d.motion_completed() is True


def test_heater_write_and_read() -> None:
    d, _ = make()
    d.heater_write(True)
    assert d.read_telemetry().heater_on is True
    d.heater_write(False)
    assert d.read_telemetry().heater_on is False


def test_heater_unconfigured_refuses_write_and_reads_unknown() -> None:
    d = PrinterDevice(SimulatedTransport(realtime=False), heater_io=None)
    with pytest.raises(TransportError):
        d.heater_write(True)
    assert d.heater_read() is None


def test_estop_cycle() -> None:
    d, t = make()
    assert d.estop_trigger("test") is True
    assert d.read_telemetry().estop_triggered is True
    assert d.estop_release() is True
    assert d.estop_reset() is True
    t.advance(3.1)
    assert d.read_telemetry().drives_ready is True


def test_drives_ready_overrides_stale_estop_flag() -> None:
    """Hardware invariant: drives are ready ONLY after the physical E-STOP was released and the
    machine RESET was pressed by hand. So a lingering estop/status or /health e-stop flag while
    drives_ready is true is stale and must not read as asserted (else the fault can never clear)."""
    d, t = make()
    d.identify()
    t.machine.estop = True          # stale e-stop status / health still says asserted…
    t.machine.drives_ready = True   # …but drives are ready (released + reset by hand)
    tel = d.read_telemetry(refresh_health=True)
    assert tel.drives_ready is True
    assert tel.estop_triggered is False


def test_endstops_and_stop() -> None:
    d, t = make()
    d.home_all()
    t.advance(60)
    assert d.endstops()["x_min"] == "TRIGGERED"
    d.stop_all()
    d.stop([1, 2])


def test_axis_config_frozen() -> None:
    a = AxisConfig(number=1, name="Build Piston", travel_mm=145.0, homing_speed=68.8)
    with pytest.raises(AttributeError):
        a.name = "x"  # type: ignore[misc]
