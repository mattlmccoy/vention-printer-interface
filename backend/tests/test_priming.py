"""Priming = job SETUP (spec §6): build piston UP, feed piston DOWN to open a powder cavity,
HOLD for the operator to load powder, then a calibrated leveling spread. NOT a layer loop."""
from __future__ import annotations

from vention_printer_interface.control.priming import PrimingSettings, compile_priming_setup
from vention_printer_interface.control.print_settings import FEED, PART, RECOATER
from vention_printer_interface.control.safety import SafetyLimits

LIM = SafetyLimits()


def kinds(steps):  # type: ignore[no-untyped-def]
    return [(s.kind, s.axis, s.value) for s in steps]


def test_positions_pistons_then_holds_then_levels() -> None:
    s = PrimingSettings()
    steps = compile_priming_setup(s, LIM)
    ks = kinds(steps)
    assert ("set_speed", PART, s.part_speed) in ks
    assert ("set_speed", FEED, s.feed_speed) in ks
    assert ("set_speed", RECOATER, s.recoater_speed) in ks
    i_part = ks.index(("move_abs", PART, s.part_top_mm))
    i_feed = ks.index(("move_abs", FEED, s.feed_cavity_mm))
    i_hold = next(n for n, st in enumerate(steps) if st.kind == "hold")
    assert i_part < i_hold and i_feed < i_hold
    holds = [st for st in steps if st.kind == "hold"]
    assert len(holds) == 1 and "powder" in holds[0].label.lower()
    # Each level pass positions first (recoater moves to start, past the feed piston), then spreads.
    i_start = ks.index(("move_abs", RECOATER, s.level_recoat_start_mm))
    i_spread = ks.index(("move_abs", RECOATER, s.level_recoat_end_mm))
    assert i_hold < i_start < i_spread


def test_no_piston_is_ever_homed() -> None:
    steps = compile_priming_setup(PrimingSettings(), LIM)
    assert all(not (s.kind == "home" and s.axis in (PART, FEED)) for s in steps)


def test_level_passes_are_configurable() -> None:
    s = PrimingSettings(n_level_passes=2)
    steps = compile_priming_setup(s, LIM)
    ends = [st for st in steps if st.kind == "move_abs" and st.axis == RECOATER
            and st.value == s.level_recoat_end_mm]
    assert len(ends) == 2


def test_recoater_targets_within_travel() -> None:
    s = PrimingSettings()
    for st in compile_priming_setup(s, LIM):
        if st.kind == "move_abs" and st.axis == RECOATER and st.value is not None:
            assert LIM.travel_min[RECOATER] <= st.value <= LIM.travel_max[RECOATER]


def test_validate_flags_out_of_travel_and_bad_passes() -> None:
    assert any("recoat" in r for r in PrimingSettings(level_recoat_end_mm=5000.0).validate(LIM))
    assert any("passes" in r for r in PrimingSettings(n_level_passes=0).validate(LIM))
    assert PrimingSettings().validate(LIM) == []
