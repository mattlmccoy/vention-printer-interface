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


def test_slow_read_warns_but_does_not_fault() -> None:
    # A telemetry read that is SLOW but SUCCEEDS (the controller stalls HTTP while it services a
    # jog/home) still yields fresh data. It must warn, never latch a fault — otherwise the machine
    # faults on every jog and home (real controller stalled a single /complete query ~1.9 s,
    # 2026-09-09). Warn band is telemetry_timeout_s (2.0 s); fault only past stale_fault_s (6.0 s).
    lim = SafetyLimits()
    d = evaluate(tel(), lim, telemetry_age_s=3.0, heater_on_s=0, move_pending=False)
    assert not d.trip
    assert any("slow" in w for w in d.warnings)


def test_stale_only_faults_past_stale_fault_s() -> None:
    lim = SafetyLimits()
    assert not evaluate(tel(), lim, 5.5, 0, False).trip  # under the fault threshold: warn only
    assert evaluate(tel(), lim, 7.0, 0, False).trip  # past it: a real blind period faults


def test_stale_fault_s_is_bounded_and_never_below_the_timeout() -> None:
    assert SafetyLimits.bounded(stale_fault_s=999).stale_fault_s == HARD_BOUNDS["stale_fault_s"][1]
    # the fault threshold must never sit below the freshness/warn threshold
    lim = SafetyLimits.bounded(telemetry_timeout_s=5.0, stale_fault_s=2.0)
    assert lim.stale_fault_s >= lim.telemetry_timeout_s


def test_estop_trips() -> None:
    d = evaluate(tel(estop_triggered=True), SafetyLimits(), 0.1, 0, False)
    assert d.trip and "e-stop" in d.reasons[0]


def test_drives_not_ready_trips_only_when_move_pending() -> None:
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, False).trip is False
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, True).trip is True


def test_home_in_progress_suspends_position_trip_only() -> None:
    # while homing, position is being re-established, so position limits are suspended; every
    # other protection (e-stop, stale, health, heater) still applies.
    lim = SafetyLimits()
    far = tel(positions={1: -200, 2: 300, 3: -99, 4: 9999})
    # position out of range is a warning, not a trip, even normally
    d = evaluate(far, lim, 0.1, 0, False)
    assert not d.trip and any("outside" in w for w in d.warnings)
    # homing suppresses even the warning
    assert evaluate(far, lim, 0.1, 0, False, home_in_progress=True).warnings == ()
    # but e-stop still trips during homing
    assert evaluate(tel(estop_triggered=True), lim, 0.1, 0, False, home_in_progress=True).trip
    assert evaluate(far, lim, 10.0, 0, False, home_in_progress=True).trip  # stale still trips


def test_homed_negative_position_is_within_limits() -> None:
    # real recoater homes to ~-22 mm; the soft floor must accommodate that (2026-09-09)
    lim = SafetyLimits()
    assert lim.travel_min[4] <= -22.0
    assert not evaluate(tel(positions={1: -0.1, 2: 0.1, 3: 250, 4: -22.0}), lim, 0.1, 0, False).trip
    # even beyond the floor it warns, never faults (must stay recoverable via homing)
    beyond = evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: -40.0}), lim, 0.1, 0, False)
    assert not beyond.trip and any("outside" in w for w in beyond.warnings)


def test_bounded_allows_negative_travel_min() -> None:
    lim = SafetyLimits.bounded(travel_min={"4": -25})
    assert lim.travel_min[4] == -25.0
    # but not past the hard floor
    assert SafetyLimits.bounded(travel_min={"4": -999}).travel_min[4] == -50.0


def test_encoder_drift_at_ends_does_not_fault() -> None:
    lim = SafetyLimits()
    assert not evaluate(tel(positions={1: -0.1, 2: 0.1, 3: 250, 4: -0.1}), lim, 0.1, 0, False).trip


def test_soft_travel_limit_warns() -> None:
    lim = SafetyLimits()
    over = evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 976}), lim, 0.1, 0, False)
    assert not over.trip and any("outside" in x for x in over.warnings)
    near = evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 969}), lim, 0.1, 0, False)
    assert not near.trip and any("near" in x for x in near.warnings)
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
    assert lim.clamp_position(2, -5) == -5.0  # travel_min is negative (home offset)
    assert lim.clamp_position(2, -999) == lim.travel_min[2]
    with pytest.raises(ValueError):
        lim.clamp_speed(9, 1)
