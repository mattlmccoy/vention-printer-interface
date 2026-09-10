"""The powder-prep / priming ("priming job") routine, compiled to Steps for the step engine.

Fidelity target: the operator's powder-handling script (2026-09-09). Sign conventions: part piston
move_rel + = DOWN, feed piston move_rel - = UP. The routine NEVER homes a piston (that ejects
powder); it homes only the recoater when the feed is exhausted.
"""

from __future__ import annotations

from vention_printer_interface.control.priming import PrimingSettings, compile_priming
from vention_printer_interface.control.print_settings import FEED, PART, RECOATER
from vention_printer_interface.control.safety import SafetyLimits

LIM = SafetyLimits()


def kinds(steps):  # type: ignore[no-untyped-def]
    return [(s.kind, s.axis, s.value) for s in steps]


def test_setup_sets_speeds_then_drops_part_for_thick_precoat() -> None:
    s = PrimingSettings()
    steps = compile_priming(s, LIM)
    head = kinds(steps)[:8]
    assert head == [
        ("set_speed", PART, s.part_speed),
        ("set_accel", PART, s.part_accel),
        ("set_speed", FEED, s.feed_speed),
        ("set_accel", FEED, s.feed_accel),
        ("set_speed", RECOATER, s.recoater_speed),
        ("set_accel", RECOATER, s.recoater_accel),
        ("move_rel", PART, s.thick_precoat_layer_mm),  # initial thick-precoat drop
        ("wait", None, None),
    ]


def test_thick_cycle_has_no_part_move_and_spreads_then_feeds_up() -> None:
    # cycle 0 is a thick precoat: no part piston move, spread to end, feed UP by the thick layer,
    # return, dwell. (script: cycles < THICK_PRECOAT_COUNT)
    s = PrimingSettings()
    steps = compile_priming(s, LIM)
    body = kinds([x for x in steps if x.phase == "priming" and x.layer == 1])
    assert not any(k == "move_rel" and a == PART for (k, a, v) in body)  # no part move in thick
    assert ("move_abs", RECOATER, s.recoater_end_mm) in body  # spread to end
    assert ("move_rel", FEED, -s.thick_precoat_layer_mm) in body  # feed up by thick layer
    assert ("move_abs", RECOATER, s.recoater_return_mm) in body  # return
    assert ("dwell", None, s.settle_s) in body


def test_nominal_cycle_does_the_piston_break_move() -> None:
    # first nominal cycle (layer THICK_PRECOAT_COUNT+1): drop part by (nominal layer + break),
    # then back UP by the break distance; feed advances by the nominal feed thickness.
    s = PrimingSettings()
    steps = compile_priming(s, LIM)
    layer = s.thick_precoat_count + 1
    body = kinds([x for x in steps if x.phase == "priming" and x.layer == layer])
    assert ("move_rel", PART, s.nominal_layer_thickness_mm + s.piston_break_mm) in body
    assert ("move_rel", PART, -s.piston_break_mm) in body  # break move back up
    assert ("move_rel", FEED, -s.nominal_feed_thickness_mm) in body


def test_terminates_by_homing_the_recoater_when_feed_would_pass_the_floor() -> None:
    # small feed budget so the routine is short and deterministic
    s = PrimingSettings(feed_start_mm=5.0, thick_precoat_count=0, feed_floor_mm=3.0,
                        nominal_feed_thickness_mm=0.8)
    steps = compile_priming(s, LIM)
    ks = kinds(steps)
    # the LAST motion is homing the recoater (never a piston), then the routine ends
    assert ("home", RECOATER, None) in ks
    assert ks[-1][0] in ("mark", "wait")  # ends right after the recoater home
    # a piston is NEVER homed
    assert ("home", PART, None) not in ks and ("home", FEED, None) not in ks
    # feed never advanced past the floor: only 2 feed-up moves (5→4.2→3.4; next 2.6<=3 stops)
    feed_ups = [v for (k, a, v) in ks if k == "move_rel" and a == FEED]
    assert feed_ups == [-0.8, -0.8]


def test_all_recoater_targets_are_within_travel() -> None:
    s = PrimingSettings()
    steps = compile_priming(s, LIM)
    for st in steps:
        if st.kind == "move_abs" and st.axis == RECOATER and st.value is not None:
            assert LIM.travel_min[RECOATER] <= st.value <= LIM.travel_max[RECOATER]


def test_validate_flags_recoater_end_past_travel() -> None:
    bad = PrimingSettings(recoater_end_mm=5000.0)
    assert any("recoater_end" in r for r in bad.validate(LIM))
    assert PrimingSettings().validate(LIM) == []
