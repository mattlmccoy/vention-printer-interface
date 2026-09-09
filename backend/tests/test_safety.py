import time
from typing import Any

import pytest

from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits, evaluate
from vention_printer_interface.device.printer import Telemetry


def tel(**kw: Any) -> Telemetry:
    base: dict[str, Any] = dict(
        host_timestamp_ns=time.time_ns(),
        positions={1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0},
        motion_complete={1: True, 2: True, 3: True, 4: True},
        estop_triggered=False,
        drives_ready=True,
        health_ok=True,
        heater_on=False,
    )
    base.update(kw)
    return Telemetry(**base)


def test_clean_sample_no_trip() -> None:
    d = evaluate(tel(), SafetyLimits(), telemetry_age_s=0.1, heater_on_s=0.0, move_pending=False)
    assert d.trip is False and d.reasons == () and d.warnings == ()


def test_stale_telemetry_trips() -> None:
    d = evaluate(tel(), SafetyLimits(), telemetry_age_s=10, heater_on_s=0, move_pending=False)
    assert d.trip and "stale" in d.reasons[0]


def test_estop_trips() -> None:
    d = evaluate(tel(estop_triggered=True), SafetyLimits(), 0.1, 0, False)
    assert d.trip and "e-stop" in d.reasons[0]


def test_drives_not_ready_trips_only_when_move_pending() -> None:
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, False).trip is False
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, True).trip is True


def test_soft_travel_limit_trips_and_warns() -> None:
    lim = SafetyLimits()
    assert evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 931}), lim, 0.1, 0, False).trip
    w = evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 927}), lim, 0.1, 0, False)
    assert not w.trip and any("near" in x for x in w.warnings)
    # sitting at home (0) is normal, not a warning; a raised travel_min is warned about
    home = evaluate(tel(positions={1: 0, 2: 0, 3: 0, 4: 0}), lim, 0.1, 0, False)
    assert home.warnings == ()
    raised = SafetyLimits.bounded(travel_min={"3": 50})
    assert any(
        "near" in x
        for x in evaluate(
            tel(positions={1: 10, 2: 10, 3: 52, 4: 10}), raised, 0.1, 0, False
        ).warnings
    )


def test_heater_watchdog_by_on_time_even_if_unobserved() -> None:
    lim = SafetyLimits(heater_max_on_s=10)
    assert evaluate(tel(heater_on=True), lim, 0.1, 11, False).trip
    assert evaluate(tel(heater_on=None), lim, 0.1, 11, False).trip
    d = evaluate(tel(heater_on=None), lim, 0.1, 9, False)
    assert not d.trip and any("not observed" in w for w in d.warnings)


def test_unknown_estop_status_trips() -> None:
    d = evaluate(tel(estop_triggered=None), SafetyLimits(), 0.1, 0, False)
    assert d.trip and "unknown" in d.reasons[0]


def test_unknown_drives_ready_trips_only_with_move_pending() -> None:
    assert not evaluate(tel(drives_ready=None), SafetyLimits(), 0.1, 0, False).trip
    assert evaluate(tel(drives_ready=None), SafetyLimits(), 0.1, 0, True).trip


def test_health_not_ok_trips() -> None:
    assert evaluate(tel(health_ok=False), SafetyLimits(), 0.1, 0, False).trip


def test_bounded_is_tighten_only() -> None:
    lim = SafetyLimits.bounded(heater_max_on_s=99999, max_speed={3: 100000})
    assert lim.heater_max_on_s == HARD_BOUNDS["heater_max_on_s"][1]
    assert lim.max_speed[3] == HARD_BOUNDS["max_speed"][3][1]


def test_bounded_round_trips_to_dict_and_swaps_inverted_travel() -> None:
    base = SafetyLimits().to_dict()
    lim = SafetyLimits.bounded(**{**base, "travel_min": {"4": 500}, "travel_max": {"4": 100}})
    assert lim.travel_min[4] == 100 and lim.travel_max[4] == 500
    assert SafetyLimits.bounded(**lim.to_dict()) == lim


def test_clamps() -> None:
    lim = SafetyLimits()
    assert lim.clamp_speed(1, 1000) == lim.max_speed[1]
    assert lim.clamp_accel(3, 1e9) == lim.max_accel[3]
    assert lim.clamp_position(2, -5) == 0.0
    with pytest.raises(ValueError):
        lim.clamp_speed(9, 1)
