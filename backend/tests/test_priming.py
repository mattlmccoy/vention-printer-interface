"""Priming = job SETUP (spec §6): build piston UP, feed piston DOWN to open a powder cavity,
HOLD for the operator to load powder, then the THICK PRECOATS that fill the runway + part cavity.
The part piston is FIXED throughout the thick precoats (backfill). NOT a part-drop layer loop."""
from __future__ import annotations

from vention_printer_interface.control.priming import (
    MAX_THICK_PRECOATS,
    PrimingSettings,
    compile_priming_setup,
)
from vention_printer_interface.control.print_settings import FEED, PART, RECOATER
from vention_printer_interface.control.safety import SafetyLimits

LIM = SafetyLimits()


def kinds(steps):  # type: ignore[no-untyped-def]
    return [(s.kind, s.axis, s.value) for s in steps]


def test_positions_pistons_then_holds_then_thick_precoats() -> None:
    s = PrimingSettings()
    steps = compile_priming_setup(s, LIM)
    ks = kinds(steps)
    assert ("set_speed", PART, s.part_speed) in ks
    assert ("set_speed", FEED, s.feed_speed) in ks
    assert ("set_speed", RECOATER, s.recoater_speed) in ks
    i_hold = next(n for n, st in enumerate(steps) if st.kind == "hold")
    # both pistons home UP to 0 first, THEN the feed drops to the cavity — all before the hold
    i_part0 = ks.index(("move_abs", PART, s.part_top_mm))
    i_feed0 = ks.index(("move_abs", FEED, 0.0))
    i_feed_cavity = ks.index(("move_abs", FEED, s.feed_cavity_mm))
    assert i_part0 < i_hold and i_feed0 < i_feed_cavity < i_hold
    # the recoater is parked at the start (left of the feed) BEFORE the powder-load hold
    i_start = ks.index(("move_abs", RECOATER, s.level_recoat_start_mm))
    assert i_start < i_hold
    holds = [st for st in steps if st.kind == "hold"]
    assert len(holds) == 1 and "powder" in holds[0].label.lower()
    # after the hold, the first fill move is the spread across the bed
    i_spread = ks.index(("move_abs", RECOATER, s.level_recoat_end_mm))
    assert i_hold < i_spread


def test_thick_precoat_pass_body_feeds_but_never_moves_part() -> None:
    s = PrimingSettings()
    steps = compile_priming_setup(s, LIM)
    # slice from the hold to the priming_done mark = the thick-precoat loop
    i_hold = next(n for n, st in enumerate(steps) if st.kind == "hold")
    i_done = next(n for n, st in enumerate(steps) if st.kind == "mark")
    loop = steps[i_hold + 1 : i_done]
    ks = kinds(loop)
    # n_thick_precoats identical passes, each: spread across -> recoater back -> FEED up -> dwell
    one_pass = [
        ("move_abs", RECOATER, s.level_recoat_end_mm),
        ("wait", None, None),
        ("move_abs", RECOATER, s.level_recoat_start_mm),
        ("wait", None, None),
        ("move_rel", FEED, -s.thick_feed_mm),
        ("wait", None, None),
        ("dwell", None, s.settle_s),
    ]
    assert ks == one_pass * s.n_thick_precoats
    # the part piston NEVER moves during the thick precoats (it stays fixed to backfill the runway).
    assert not any(st.axis == PART and st.kind.startswith("move") for st in loop)
    assert steps[i_done].label == "priming_done"


def test_no_piston_is_ever_homed() -> None:
    steps = compile_priming_setup(PrimingSettings(), LIM)
    assert all(not (s.kind == "home" and s.axis in (PART, FEED)) for s in steps)


def test_thick_precoats_are_configurable() -> None:
    s = PrimingSettings(n_thick_precoats=2)
    steps = compile_priming_setup(s, LIM)
    ends = [st for st in steps if st.kind == "move_abs" and st.axis == RECOATER
            and st.value == s.level_recoat_end_mm]
    feeds = [st for st in steps if st.kind == "move_rel" and st.axis == FEED]
    assert len(ends) == 2 and len(feeds) == 2


def test_default_thick_precoats_and_feed() -> None:
    s = PrimingSettings()
    assert s.n_thick_precoats == 3
    assert s.thick_feed_mm == 7.0


def test_recoater_targets_within_travel() -> None:
    s = PrimingSettings()
    for st in compile_priming_setup(s, LIM):
        if st.kind == "move_abs" and st.axis == RECOATER and st.value is not None:
            assert LIM.travel_min[RECOATER] <= st.value <= LIM.travel_max[RECOATER]


def test_bounded_clamps_thick_precoats_and_feed() -> None:
    over = PrimingSettings.bounded({"n_thick_precoats": 9999, "thick_feed_mm": 9999.0}, LIM)
    assert over.n_thick_precoats == MAX_THICK_PRECOATS
    assert over.thick_feed_mm == 50.0
    under = PrimingSettings.bounded({"n_thick_precoats": 0, "thick_feed_mm": -5.0}, LIM)
    assert under.n_thick_precoats == 1
    assert under.thick_feed_mm == 0.0


def test_round_trip_dict_carries_new_fields() -> None:
    s = PrimingSettings(n_thick_precoats=4, thick_feed_mm=6.0)
    d = s.to_dict()
    assert d["n_thick_precoats"] == 4 and d["thick_feed_mm"] == 6.0
    assert PrimingSettings.from_dict(d) == s


def test_validate_flags_out_of_travel_and_bad_thick_precoats() -> None:
    assert any("recoat" in r for r in PrimingSettings(level_recoat_end_mm=5000.0).validate(LIM))
    assert any("thick_precoat" in r for r in PrimingSettings(n_thick_precoats=0).validate(LIM))
    assert PrimingSettings().validate(LIM) == []
