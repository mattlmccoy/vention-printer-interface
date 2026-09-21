"""compile_print must reproduce the async lab script's cycle order exactly (Plan 7 / fidelity spec).

The compiled ``Step`` sequence is the safety-critical contract; these tests pin it cycle-by-cycle:
primed-start setup (home gantries only), the thin (nominal) precoat cover passes, a printing layer
with the concurrent recoater-retract + printhead-jet, the heater 425->600 sweep, the feed-exhaustion
stop, and the part->max finish. The THICK precoats now live in the priming routine
(test_priming.py), so the print begins at the thin precoats, where the part piston first drops.
"""

import dataclasses

import pytest

from vention_printer_interface.control.print_settings import (
    FEED,
    PART,
    PHASES,
    PRINTHEAD,
    RECOATER,
    PhasePlan,
    PrintSettings,
    compile_print,
    estimate_duration_s,
)
from vention_printer_interface.control.safety import SafetyLimits


def one_layer() -> PrintSettings:
    """Printing-only, one layer, heater on.

    ``capture_stages`` is disabled here so the exact-sequence-pinned tests below keep verifying
    motion only; capture-mark behavior gets its own dedicated tests further down.
    """
    p = PrintSettings()
    return dataclasses.replace(
        p,
        thin_precoat=dataclasses.replace(p.thin_precoat, n_layers=0),
        printing=dataclasses.replace(p.printing, n_layers=1),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
        heater_enabled=True,
        capture_stages=False,
    )


def thin_only() -> PrintSettings:
    """One nominal (thin) precoat layer only — the print's first phase."""
    p = PrintSettings()
    return dataclasses.replace(
        p,
        thin_precoat=dataclasses.replace(p.thin_precoat, n_layers=1),
        printing=dataclasses.replace(p.printing, n_layers=0),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
    )


def kinds_of(plan: PrintSettings) -> list[tuple[str, int | None, float | None]]:
    return [(s.kind, s.axis, s.value) for s in compile_print(plan)]


# ---- phases + field / default / bounds -----------------------------------------------------------


def test_phases_have_no_thick_precoat() -> None:
    # thick precoats moved to priming; the print starts at thin_precoat.
    assert PHASES == ("thin_precoat", "printing", "postcoat")
    assert "thick_precoat" not in PHASES
    assert not hasattr(PrintSettings(), "thick_precoat")


def test_defaults_match_v1() -> None:
    p = PrintSettings()
    assert (p.thin_precoat.layer_thickness_mm, p.thin_precoat.n_layers) == (0.2, 2)
    assert (p.printing.layer_thickness_mm, p.printing.n_layers) == (2.0, 10)
    assert (p.postcoat.layer_thickness_mm, p.postcoat.n_layers) == (5.0, 1)
    assert p.printing.part_speed == 2.5 and p.printing.part_accel == 15
    assert p.printing.recoater_speed == 100 and p.printing.recoater_accel == 500
    assert (p.feed_end_mm, p.recoater_end_mm, p.printhead_end_mm, p.heater_end_mm) == (
        145,
        950,
        900,
        600,
    )
    assert p.heater_speed == 50 and p.heater_accel == 250 and p.n_heater_passes == 1
    assert p.heater_enabled is False  # heater is opt-in
    assert p.n_jet_passes == 1 and p.pre_heater_drop_mm == 0.0 and p.postcoat_enabled is True
    # thin 0.2*2 + printing 2.0*10 + postcoat 5.0*1 = 25.4 mm over 13 layers (no thick precoat)
    assert p.total_thickness_mm == pytest.approx(25.4) and p.total_layers == 13


def test_new_fields_defaults() -> None:
    p = PrintSettings()
    assert p.thin_precoat.n_layers == 2 and p.thin_precoat.layer_thickness_mm == 0.2
    assert p.n_jet_passes == 1 and p.pre_heater_drop_mm == 0.0
    assert p.postcoat_enabled is True


def test_validate_defaults_ok_and_printability() -> None:
    assert PrintSettings().validate() == []
    p = dataclasses.replace(PrintSettings(), printing=PhasePlan(layer_thickness_mm=2, n_layers=100))
    reasons = p.validate()
    assert any("thickness" in r for r in reasons)
    p2 = dataclasses.replace(PrintSettings(), recoater_end_mm=5000)
    assert any("recoater_end_mm" in r for r in p2.validate())
    p3 = dataclasses.replace(PrintSettings(), printing=PhasePlan(layer_thickness_mm=0, n_layers=1))
    assert any("layer_thickness" in r for r in p3.validate())


def test_bounded_clamps_speeds_and_positions() -> None:
    lim = SafetyLimits()
    p = PrintSettings.bounded({"feed_fast_speed": 1000, "recoater_end_mm": 5000}, lim)
    assert p.feed_fast_speed == lim.max_speed[FEED]
    assert p.recoater_end_mm == lim.travel_max[RECOATER]
    p2 = PrintSettings.bounded({"printing": {"recoater_speed": 9999, "n_layers": 5}}, lim)
    assert p2.printing.recoater_speed == lim.max_speed[RECOATER] and p2.printing.n_layers == 5


def test_round_trip_dict() -> None:
    p = one_layer()
    assert PrintSettings.from_dict(p.to_dict()) == p


def test_feed_thickness_defaults() -> None:
    # Feed-piston advance per layer is distinct from the part-piston drop (V1.py):
    # thin/print advance 0.4 mm (part 0.2/2.0); postcoat is a cover pass with no feed advance.
    p = PrintSettings()
    assert p.thin_precoat.feed_thickness_mm == 0.4
    assert p.printing.feed_thickness_mm == 0.4
    assert p.postcoat.feed_thickness_mm == 0.0


def test_script_faithful_position_defaults() -> None:
    p = PrintSettings()
    assert p.recoater_return_mm == 350.0
    assert p.heater_start_mm == 425.0
    assert p.part_max_mm == 72.0
    assert p.recoater_end_mm == 950.0
    assert p.printhead_end_mm == 900.0


def test_multipass_printhead_returns_to_midpoint_then_home() -> None:
    # During multipass the printhead shuttles to printhead_multipass_return_mm (250) between passes
    # to save travel, and only returns fully home on the LAST pass to clear for the next recoat.
    assert PrintSettings().printhead_multipass_return_mm == 250.0
    p = dataclasses.replace(one_layer(), n_jet_passes=3)
    returns = [
        s.value
        for s in compile_print(p)
        if s.phase == "printing" and s.kind == "move_abs" and s.axis == PRINTHEAD
        and s.value != p.printhead_end_mm
    ]
    assert returns == [250.0, 250.0, 5.0]
    # single pass unchanged: one return, straight home
    p1 = dataclasses.replace(one_layer(), n_jet_passes=1)
    returns1 = [
        s.value
        for s in compile_print(p1)
        if s.phase == "printing" and s.kind == "move_abs" and s.axis == PRINTHEAD
        and s.value != p1.printhead_end_mm
    ]
    assert returns1 == [5.0]


def three_printing_layers() -> PrintSettings:
    p = PrintSettings()
    return dataclasses.replace(
        p,
        thin_precoat=dataclasses.replace(p.thin_precoat, n_layers=0),
        printing=dataclasses.replace(p.printing, n_layers=3),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
        capture_stages=False,
    )


def test_nozzle_purge_dwell_and_scheduling() -> None:
    # Firing is external; the software's purge is a DWELL at the printhead start position (250) so
    # the printhead controller can fire. Default off. Modes: every pass / once per layer / every N.
    assert PrintSettings().purge_dwell_s == 0.0
    assert not any(s.label == "nozzle purge" for s in compile_print(one_layer()))

    # every_pass with multipass 3 -> a purge dwell before each of the 3 jet-outs, at 250 mm
    p = dataclasses.replace(one_layer(), n_jet_passes=3, purge_dwell_s=0.5, purge_mode="every_pass")
    steps = compile_print(p)
    purges = [s for s in steps if s.kind == "dwell" and s.label == "nozzle purge"]
    assert len(purges) == 3 and all(s.value == 0.5 for s in purges)
    # each purge is immediately preceded by a printhead move to the purge/start position (250)
    for i, s in enumerate(steps):
        if s.label == "nozzle purge":
            prev = [x for x in steps[:i] if x.axis == PRINTHEAD and x.kind == "move_abs"][-1]
            assert prev.value == p.printhead_start_mm

    # per_layer: one purge per printing layer regardless of multipass
    p2 = dataclasses.replace(three_printing_layers(), n_jet_passes=2, purge_dwell_s=1.0,
                             purge_mode="per_layer")
    assert len([s for s in compile_print(p2) if s.label == "nozzle purge"]) == 3

    # every_n_layers, N=2 -> printing layers 1 and 3 purge (first + every 2nd)
    p3 = dataclasses.replace(three_printing_layers(), purge_dwell_s=1.0,
                             purge_mode="every_n_layers", purge_every_n_layers=2)
    assert len([s for s in compile_print(p3) if s.label == "nozzle purge"]) == 2


def test_purge_position_defaults_to_printhead_start() -> None:
    # Default is None -> the purge hold falls back to printhead_start_mm exactly as before,
    # so a plan with purge on but no purge_position_mm compiles identically to today.
    assert PrintSettings().purge_position_mm is None
    base = dataclasses.replace(
        one_layer(), n_jet_passes=3, purge_dwell_s=0.5, purge_mode="every_pass"
    )
    assert base.purge_position_mm is None
    steps = compile_print(base)
    for i, s in enumerate(steps):
        if s.label == "nozzle purge":
            prev = [x for x in steps[:i] if x.axis == PRINTHEAD and x.kind == "move_abs"][-1]
            assert prev.value == base.printhead_start_mm


def test_purge_position_overrides_the_purge_hold() -> None:
    # When set, purge_position_mm is the absolute printhead position for the purge dwell,
    # WITHOUT changing printhead_start_mm (still the multipass/purge reference position).
    p = dataclasses.replace(
        one_layer(),
        n_jet_passes=3,
        purge_dwell_s=0.5,
        purge_mode="every_pass",
        purge_position_mm=175.0,
    )
    steps = compile_print(p)
    for i, s in enumerate(steps):
        if s.label == "nozzle purge":
            prev = [x for x in steps[:i] if x.axis == PRINTHEAD and x.kind == "move_abs"][-1]
            assert prev.value == 175.0


def test_bounded_clamps_purge_position_and_preserves_none() -> None:
    lim = SafetyLimits()
    # unset stays None (fallback behavior preserved)
    assert PrintSettings.bounded({}, lim).purge_position_mm is None
    # a set value is clamped into the printhead axis travel like other positions
    p = PrintSettings.bounded({"purge_position_mm": 5000}, lim)
    assert p.purge_position_mm == lim.travel_max[PRINTHEAD]


def test_feed_backlash_preload_drops_feed_before_spread() -> None:
    # Opt-in anti-backlash: the feed drops feed_backlash_mm BEFORE the recoater spread, then the
    # post-spread feed-up covers that drop plus the advance — net advance unchanged, approached from
    # below so mechanical backlash is taken up in one direction. Default 0 => no behavior change.
    assert PrintSettings().feed_backlash_mm == 0.0
    feeds0 = [k for k in kinds_of(one_layer()) if k[0] == "move_rel" and k[1] == FEED]
    assert feeds0 == [("move_rel", FEED, -0.4)]  # off: single up move (feed_thickness 0.4)
    p = dataclasses.replace(one_layer(), feed_backlash_mm=2.0)
    ks = kinds_of(p)
    feeds = [k for k in ks if k[0] == "move_rel" and k[1] == FEED]
    assert feeds == [("move_rel", FEED, 2.0), ("move_rel", FEED, -2.4)]  # down +2, then up -(0.4+2)
    # the preload drop is emitted BEFORE the spread (recoater to end), the up move AFTER it
    kinds = [(s.kind, s.axis, s.value) for s in compile_print(p)]
    i_down = kinds.index(("move_rel", FEED, 2.0))
    i_spread = kinds.index(("move_abs", RECOATER, p.recoater_end_mm))
    i_up = kinds.index(("move_rel", FEED, -2.4))
    assert i_down < i_spread < i_up


def test_build_backlash_preload_overshoots_the_part_drop() -> None:
    # Opt-in anti-backlash on the build-piston layer drop. Piston sweep (2026-09-16) showed a ~0.15
    # mm overshoot-and-return takes 0.1-0.3 mm layer steps from ~55-67% on-target to ~100% (backlash
    # < 0.1 mm). The drop overshoots DOWN past the layer target by build_backlash_mm, then returns
    # UP to it: net descent = layer_thickness, approached one-sided so slop is taken up. Default 0.
    # Default is ON at 0.15 mm: the 2026-09-18 sweep (4056 pts) confirmed 0.15 mm cuts mean step
    # error 0.046 -> 0.007 mm (6.5x). Explicitly request 0 to get the V1.py-faithful single move.
    assert PrintSettings().build_backlash_mm == 0.15
    off = dataclasses.replace(one_layer(), build_backlash_mm=0.0)
    parts0 = [k for k in kinds_of(off) if k[0] == "move_rel" and k[1] == PART]
    assert parts0 == [("move_rel", PART, 2.0)]  # off: single down move (layer_thickness 2.0)
    p = dataclasses.replace(one_layer(), build_backlash_mm=0.15)
    parts = [k for k in kinds_of(p) if k[0] == "move_rel" and k[1] == PART]
    assert parts == [("move_rel", PART, 2.15), ("move_rel", PART, -0.15)]  # down layer+bl, up bl
    # the overshoot is emitted at the layer start, BEFORE the recoater spread
    kinds = [(s.kind, s.axis, s.value) for s in compile_print(p)]
    assert kinds.index(("move_rel", PART, 2.15)) < kinds.index(
        ("move_abs", RECOATER, p.recoater_end_mm)
    )


def test_validate_flags_a_build_beyond_the_pistons_usable_travel() -> None:
    from vention_printer_interface.control.print_settings import PART_USABLE_TRAVEL_MM
    assert PART_USABLE_TRAVEL_MM == 72.0  # attached-piston usable range (= default part_max_mm)
    ok = PrintSettings()  # default part_max 72 mm, ~25 mm build → right at reach, still valid
    assert not any("max travel" in r for r in ok.validate())
    # part_max past the ~72 mm attached wall (bounded clamps to 145 mm, so validate must catch it)
    deep = dataclasses.replace(ok, part_max_mm=90.0)
    assert any("max travel" in r for r in deep.validate())
    # a tall build (cumulative descent) beyond usable travel is flagged too
    tall_printing = dataclasses.replace(ok.printing, n_layers=70, layer_thickness_mm=2.0)
    tall = dataclasses.replace(ok, printing=tall_printing)
    assert tall.total_thickness_mm > PART_USABLE_TRAVEL_MM
    assert any("max travel" in r for r in tall.validate())
    # the guard uses the SETTABLE per-cylinder build_piston_max_mm, not just the constant
    assert ok.build_piston_max_mm == 72.0
    raised = dataclasses.replace(deep, build_piston_max_mm=100.0)  # a looser cylinder reaches 90 mm
    assert not any("max travel" in r for r in raised.validate())


def test_build_backlash_mm_is_clamped_to_0_5() -> None:
    # The preload is a small overshoot to take up lash, never a large plunge: bounded() (the
    # clamping constructor; from_dict is a raw round-trip) bounds it to [0, 5] mm, so an over-large
    # value can't drive the part well past its layer target.
    assert PrintSettings.bounded({"build_backlash_mm": 99}, SafetyLimits()).build_backlash_mm == 5.0
    assert PrintSettings.bounded({"build_backlash_mm": -3}, SafetyLimits()).build_backlash_mm == 0.0


def test_bounded_snaps_layer_height_to_the_0_1mm_readout_grid() -> None:
    # The build-piston position readout is quantized to 0.1 mm, so a layer height between quanta
    # (0.05, 0.15) can't be placed or verified. bounded() snaps every phase's layer_thickness to the
    # nearest 0.1 mm (>= one quantum) — the API guard behind the UI gate. from_dict stays a raw
    # round-trip (unsnapped). A disabled phase's 0 is preserved.
    lim = SafetyLimits()
    p = PrintSettings.bounded({
        "printing": {"layer_thickness_mm": 0.15},       # between quanta -> up
        "thin_precoat": {"layer_thickness_mm": 0.05},   # below the floor -> the floor
        "postcoat": {"layer_thickness_mm": 0.0, "n_layers": 0},  # disabled -> preserved
    }, lim)
    assert p.printing.layer_thickness_mm == 0.2
    assert p.thin_precoat.layer_thickness_mm == 0.1
    assert p.postcoat.layer_thickness_mm == 0.0
    # an already-on-grid value is unchanged
    assert PrintSettings.bounded(
        {"printing": {"layer_thickness_mm": 0.3}}, lim
    ).printing.layer_thickness_mm == 0.3
    # from_dict does NOT snap (faithful round-trip)
    assert PrintSettings.from_dict(
        {"printing": {"layer_thickness_mm": 0.15}}
    ).printing.layer_thickness_mm == 0.15


def test_bounded_clamps_new_position_fields() -> None:
    lim = SafetyLimits()
    p = PrintSettings.bounded(
        {"recoater_return_mm": 5000, "heater_start_mm": 5000, "part_max_mm": 5000}, lim
    )
    assert p.recoater_return_mm == lim.travel_max[RECOATER]
    assert p.heater_start_mm == lim.travel_max[RECOATER]
    assert p.part_max_mm == lim.travel_max[PART]
    # feed_thickness_mm on a phase is clamped into [0, 50]
    p2 = PrintSettings.bounded({"printing": {"feed_thickness_mm": 9999}}, lim)
    assert p2.printing.feed_thickness_mm == 50.0


def test_heater_exposure_input_defaults() -> None:
    p = PrintSettings()
    assert p.target_carbon_wt == 0.15 and p.part_area_mm2 == 900.0
    assert p.powder_density_g_cm3 == 1.01 and p.ink_carbon_wt == 0.25
    assert p.ipa_dhvap_j_g == 663.0 and p.heater_section_power_w == 75.0


# ---- (a) primed-start setup ----------------------------------------------------------------------


def test_setup_homes_gantries_only_no_piston_move() -> None:
    steps = compile_print(one_layer())
    # First four steps: home printhead, home recoater — gantries only, each followed by a wait.
    assert (steps[0].kind, steps[0].axis) == ("home", PRINTHEAD)
    assert steps[1].kind == "wait"
    assert (steps[2].kind, steps[2].axis) == ("home", RECOATER)
    assert steps[3].kind == "wait"
    # Primed start: NO home_all anywhere, and the setup never homes or moves PART or FEED.
    assert not any(s.kind == "home_all" for s in steps)
    setup = [s for s in steps if s.phase == "setup"]
    assert not any(s.kind == "home" and s.axis in (PART, FEED) for s in setup)
    assert not any(s.kind in ("move_abs", "move_rel") and s.axis in (PART, FEED) for s in setup)
    # Setup homes the gantries and sets profiles ONLY — it emits NO axis moves. The printhead stays
    # home (never parked mid-bed at 250, which would block the recoater's spread) and the pistons
    # stay at the primed bed.
    setup_moves = [s for s in setup if s.kind in ("move_abs", "move_rel")]
    assert setup_moves == []
    assert PrintSettings().printhead_start_mm == 250.0


# ---- (b) print starts at the thin (nominal) precoat, not a thick precoat --------------------


def test_print_first_phase_is_thin_precoat_no_thick_steps() -> None:
    p = dataclasses.replace(
        PrintSettings(),
        thin_precoat=dataclasses.replace(PrintSettings().thin_precoat, n_layers=2),
    )
    steps = compile_print(p)
    # No step is ever tagged with the removed thick_precoat phase.
    assert not any(s.phase == "thick_precoat" for s in steps)
    # The first non-setup phase to appear is thin_precoat.
    phases_in_order = [s.phase for s in steps if s.phase not in ("setup", "finish")]
    assert phases_in_order[0] == "thin_precoat"


def test_thin_precoat_layer_spreads_feeds_drops_part_and_returns() -> None:
    # V1.py-faithful baseline: no build backlash (default is now 0.15 — see the backlash test).
    plan = dataclasses.replace(thin_only(), build_backlash_mm=0.0)
    all_steps = [s for s in compile_print(plan) if s.phase == "thin_precoat"]
    steps = [s for s in all_steps if s.kind not in ("set_speed", "set_accel")]
    ks = [(s.kind, s.axis, s.value) for s in steps]
    body = [
        ("mark", None, None),
        ("move_rel", PART, 0.2),  # part drop 0.2 (nominal) FIRST — the print's first part drop
        ("wait", None, None),
        ("move_abs", RECOATER, 950.0),  # recoater past the feed piston (reposition)
        ("wait", None, None),
        ("move_rel", FEED, -0.4),  # feed advance 0.4 (nominal)
        ("wait", None, None),
        ("dwell", None, 1.0),
        ("move_abs", RECOATER, 350.0),  # precoat return, NOT home
        ("wait", None, None),
        ("mark", None, None),
    ]
    assert ks == body
    assert not any(s.axis == PRINTHEAD and s.kind.startswith("move") for s in all_steps)
    assert steps[0].part_height_mm == pytest.approx(0.2)  # part grew by one nominal layer


# ---- (d) printing layer: full sequence + concurrency + heater + finish ---------------------------


def test_compile_one_printing_layer_full_sequence() -> None:
    # V1.py-faithful baseline: no build backlash (default is now 0.15 — see the backlash test).
    steps = compile_print(dataclasses.replace(one_layer(), build_backlash_mm=0.0))
    kinds = [(s.kind, s.axis, s.value) for s in steps]

    # (a) setup — gantry homes + profiles ONLY, no printhead park (4 home/wait + 8 set_* = 12)
    assert kinds[0:4] == [
        ("home", PRINTHEAD, None),
        ("wait", None, None),
        ("home", RECOATER, None),
        ("wait", None, None),
    ]
    n_setup = sum(1 for s in steps if s.phase == "setup")
    assert n_setup == 12
    # setup emits no axis move — the printhead stays home (never parked at 250 mid-bed)
    assert not any(s.phase == "setup" and s.kind in ("move_abs", "move_rel") for s in steps)

    # phase setup for printing: set_speed/accel PART, FEED, PRINTHEAD, RECOATER
    i = n_setup
    assert kinds[i : i + 8] == [
        ("set_speed", PART, 2.5),
        ("set_accel", PART, 15.0),
        ("set_speed", FEED, 2.5),
        ("set_accel", FEED, 15.0),
        ("set_speed", PRINTHEAD, 100.0),
        ("set_accel", PRINTHEAD, 500.0),
        ("set_speed", RECOATER, 100.0),
        ("set_accel", RECOATER, 500.0),
    ]
    i += 8

    layer = [
        ("mark", None, None),              # layer_start
        ("move_rel", PART, 2.0),           # part drop — FIRST (V1.py order)
        ("wait", None, None),
        ("move_abs", RECOATER, 950.0),     # recoater past the feed piston to far end (reposition)
        ("wait", None, None),
        ("move_rel", FEED, -0.4),          # feed advance (the feed piston supplies powder)
        ("wait", None, None),
        ("dwell", None, 1.0),
        ("move_abs", RECOATER, 5.0),       # recoater home = SPREAD  \  concurrent: two moves,
        ("move_abs", PRINTHEAD, 900.0),    # printhead jet, trailing  /  then ONE wait
        ("wait", None, None),
        ("move_abs", PRINTHEAD, 5.0),      # printhead home
        ("wait", None, None),
        ("move_abs", RECOATER, 425.0),     # heater sweep start
        ("wait", None, None),
        ("heater", None, 1.0),
        ("set_speed", RECOATER, 50.0),     # slow follow
        ("set_accel", RECOATER, 250.0),
        ("move_abs", RECOATER, 600.0),     # heater sweep end
        ("wait", None, None),
        ("heater", None, 0.0),
        ("set_speed", RECOATER, 100.0),    # restore printing recoater profile
        ("set_accel", RECOATER, 500.0),
        # NO end-of-layer recoater->950. The recoater stays at the heater sweep end (600) and
        # repositions to the spread start (950) only at the NEXT layer's start, AFTER its feed
        # preload. Parking it at 950 here made the next preload land too late (bug report).
        ("mark", None, None),              # layer_end
    ]
    assert kinds[i : i + len(layer)] == layer
    layer_start = steps[i]
    layer_end = steps[i + len(layer) - 1]
    assert layer_start.label == "layer_start" and layer_end.label == "layer_end"
    assert layer_start.phase == "printing" and layer_start.layer == 1
    assert layer_start.part_height_mm == 2.0
    i += len(layer)

    # concurrency: the recoater-home and printhead-end moves are adjacent with the wait AFTER both.
    j = next(
        k
        for k in range(len(kinds))
        if kinds[k] == ("move_abs", RECOATER, 5.0)
    )
    assert kinds[j + 1] == ("move_abs", PRINTHEAD, 900.0)
    assert kinds[j + 2] == ("wait", None, None)

    # (d) finish: home printhead, home recoater, drive part -> part_max (72)
    finish = kinds[i:]
    assert finish == [
        ("home", PRINTHEAD, None),
        ("wait", None, None),
        ("home", RECOATER, None),
        ("wait", None, None),
        ("move_abs", PART, 72.0),
        ("wait", None, None),
    ]
    assert steps[-2].kind == "move_abs" and steps[-2].axis == PART and steps[-2].value == 72.0
    assert [s.index for s in steps] == list(range(len(steps)))


# ---- (e) multi-pass jetting ----------------------------------------------------------------------


def test_recoater_repositions_after_preload_never_at_layer_end() -> None:
    # Anti-backlash: the recoater moves out to the spread start (950) AFTER that layer's feed
    # preload drop — NEVER at the previous layer's end (which would park it at 950 before the next
    # preload). So each printing layer has exactly ONE recoater->950, and the feed move before it is
    # preload DOWN. Bug report: the feed drop happened after the recoater had already gone to 950.
    two = dataclasses.replace(one_layer(), feed_backlash_mm=2.0)
    two = dataclasses.replace(two, printing=dataclasses.replace(two.printing, n_layers=2))
    ks = [(s.kind, s.axis, s.value) for s in compile_print(two) if s.phase == "printing"]
    idx_950 = [i for i, k in enumerate(ks) if k == ("move_abs", RECOATER, 950.0)]
    assert len(idx_950) == 2  # one reposition per layer, and NONE at layer end
    for i in idx_950:
        prev_feed = [ks[j] for j in range(i) if ks[j][:2] == ("move_rel", FEED)]
        assert prev_feed[-1] == ("move_rel", FEED, 2.0)  # preload DOWN immediately precedes each


def test_heater_on_keeps_printhead_return_serial_before_the_sweep() -> None:
    # Heater ON: printhead returns home (its own wait) BEFORE the heater sweep starts.
    ks = [(s.kind, s.axis, s.value) for s in compile_print(one_layer()) if s.phase == "printing"]
    i_home = ks.index(("move_abs", PRINTHEAD, 5.0))
    assert ks[i_home + 1] == ("wait", None, None)
    assert ks[i_home + 2] == ("move_abs", RECOATER, 425.0)  # sweep start after the printhead return


def test_printing_multipass_shuttles_to_midpoint_then_home() -> None:
    p = dataclasses.replace(one_layer(), n_jet_passes=3, heater_enabled=False)
    ks = kinds_of(p)
    # Printhead moves within the printing phase only (setup printhead-to-start is separate).
    ph = [
        s for s in compile_print(p)
        if s.phase == "printing" and s.kind == "move_abs" and s.axis == PRINTHEAD
    ]
    assert len([s for s in ph if s.value == 900.0]) == 3  # 3 jet passes out to the end
    assert len([s for s in ph if s.value == 250.0]) == 2  # between-pass returns to the midpoint
    assert len([s for s in ph if s.value == 5.0]) == 1  # only the last pass returns fully home
    # heater disabled -> no heater sweep at all
    assert not any(k[0] == "heater" for k in ks)
    assert not any(k == ("move_abs", RECOATER, 600.0) for k in ks)


# ---- (f) pre-heater drop brackets the heater -----------------------------------------------------


def test_pre_heater_drop_brackets_the_heater() -> None:
    p = dataclasses.replace(
        one_layer(),
        printing=dataclasses.replace(PrintSettings().printing, n_layers=1, layer_thickness_mm=0.2),
        n_jet_passes=2,
        pre_heater_drop_mm=0.1,
        heater_enabled=True,
    )
    ks = kinds_of(p)
    jet = [i for i, k in enumerate(ks) if k == ("move_abs", PRINTHEAD, 900.0)]
    assert len(jet) == 2
    i_drop = ks.index(("move_rel", PART, 0.1))
    i_heater_on = next(i for i, k in enumerate(ks) if k[0] == "heater" and k[2] == 1.0)
    i_up = next(
        i for i, k in enumerate(ks) if k == ("move_rel", PART, -0.1) and i > i_heater_on
    )
    assert max(jet) < i_drop < i_heater_on < i_up  # jets -> drop -> heat -> raise back up


# ---- (g) postcoat toggle: off drops the phase AND validates clean --------------------------------


def test_postcoat_toggle_off_but_finish_still_drives_part_to_max() -> None:
    p_on = PrintSettings()
    p_off = dataclasses.replace(p_on, postcoat_enabled=False)
    assert any(s.phase == "postcoat" for s in compile_print(p_on))
    off_steps = compile_print(p_off)
    assert not any(s.phase == "postcoat" for s in off_steps)
    # finish still ends with part -> part_max
    assert off_steps[-2].kind == "move_abs"
    assert off_steps[-2].axis == PART and off_steps[-2].value == 72.0


def test_disabled_postcoat_validates_clean() -> None:
    # A disabled postcoat must NOT produce a validation reason, even with degenerate fields.
    p = dataclasses.replace(
        PrintSettings(),
        postcoat_enabled=False,
        postcoat=PhasePlan(layer_thickness_mm=0.0, n_layers=1),
    )
    assert p.validate() == []
    # An enabled postcoat with a zero thickness but positive layers is still flagged.
    p_on = dataclasses.replace(
        PrintSettings(),
        postcoat_enabled=True,
        postcoat=PhasePlan(layer_thickness_mm=0.0, n_layers=1),
    )
    assert any("layer_thickness" in r for r in p_on.validate())


def test_postcoat_is_a_precoat_style_cover_pass() -> None:
    # postcoat: spread -> (no feed, thickness 0) -> return 350; no part drop, no jet, no heater.
    p = dataclasses.replace(
        PrintSettings(),
        thin_precoat=PhasePlan(n_layers=0),
        printing=PhasePlan(n_layers=0),
        postcoat=dataclasses.replace(PrintSettings().postcoat, n_layers=1),
    )
    steps = [s for s in compile_print(p) if s.phase == "postcoat"]
    ks = [(s.kind, s.axis, s.value) for s in steps]
    assert ("move_abs", RECOATER, 950.0) in ks  # spread
    assert ("move_abs", RECOATER, 350.0) in ks  # precoat-style return
    assert not any(s.axis == PART and s.kind.startswith("move") for s in steps)  # no part drop
    assert not any(s.axis == PRINTHEAD and s.kind.startswith("move") for s in steps)  # no jetting
    assert not any(s.kind == "heater" for s in steps)
    assert not any(s.kind == "move_rel" and s.axis == FEED for s in steps)  # feed_thickness 0


# ---- (h) feed exhaustion -------------------------------------------------------------------------


def test_feed_exhaustion_homes_recoater_marks_and_stops() -> None:
    # Running feed starts at feed_end_mm (primed column top) 1.0 and drops 0.4 each printing layer:
    # 1.0 -> 0.6 (layer 1), 0.6 -> 0.2 (layer 2); layer 3 would go 0.2 - 0.4 = -0.2 <= 0 -> exhaust.
    p = dataclasses.replace(
        PrintSettings(),
        thin_precoat=PhasePlan(n_layers=0),
        printing=dataclasses.replace(
            PrintSettings().printing, n_layers=5, feed_thickness_mm=0.4, layer_thickness_mm=0.2
        ),
        postcoat=PhasePlan(n_layers=0),
        feed_end_mm=1.0,
        heater_enabled=False,
    )
    steps = compile_print(p)
    # exactly two printing layers completed
    completed = [s for s in steps if s.label == "layer_end"]
    assert len(completed) == 2
    # the sequence ends with recoater home + a "feed_exhausted" mark (terminal safety stop)
    assert steps[-1].kind == "mark" and steps[-1].label == "feed_exhausted"
    assert steps[-2].kind == "wait"
    assert (steps[-3].kind, steps[-3].axis, steps[-3].value) == (
        "move_abs",
        RECOATER,
        p.recoater_home_mm,
    )
    # exhaustion is terminal: NO part -> max finish after the stop
    assert not any(
        s.kind == "move_abs" and s.axis == PART and s.value == p.part_max_mm for s in steps
    )


def test_feed_advances_during_printing_user_override() -> None:
    # USER OVERRIDE: the feed piston advances every printing layer (it is the powder supply).
    steps = [s for s in compile_print(one_layer()) if s.phase == "printing"]
    assert any(s.kind == "move_rel" and s.axis == FEED and s.value == -0.4 for s in steps)


# ---- misc ----------------------------------------------------------------------------------------


def test_steps_are_frozen() -> None:
    s = compile_print(one_layer())[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.kind = "x"  # type: ignore[misc]


def test_layer_numbers_and_heights_over_a_full_plan() -> None:
    p = dataclasses.replace(PrintSettings(), heater_enabled=True)
    steps = compile_print(p)
    # 13 layers total numbered 1..13: thin 2 + printing 10 + postcoat 1 (thick precoats now prime)
    assert [s.layer for s in steps if s.label == "layer_start"] == list(range(1, 14))
    heights = [s.part_height_mm for s in steps if s.label == "layer_end"]
    # thin adds 0.2 each (2 layers); printing adds 2.0 each (10 layers);
    # postcoat is a cover pass (no part drop) so the last layer_end keeps the printing stack height.
    assert heights[0] == pytest.approx(0.2)
    assert heights[1] == pytest.approx(0.4)
    assert heights[2] == pytest.approx(2.4)  # first printing layer (+2.0)
    # thin 0.4 + printing 2.0*10 = 20.4 mm; postcoat adds no part height
    assert heights[-1] == pytest.approx(20.4)


# ---- (i) vision capture marks --------------------------------------------------------------------


def test_capture_stages_defaults_to_disabled() -> None:
    # Captures are OFF by default until an operator commissions the camera and capture pose.
    assert PrintSettings().capture_stages is False


def test_overhead_capture_moves_recoater_to_pose_then_settles() -> None:
    # Every enabled stage uses the same calibrated overhead pose, settles before the trigger, and
    # holds after it so the asynchronous browser exposure finishes before the next move.
    base = dataclasses.replace(one_layer(), capture_stages=True)

    fixed = compile_print(dataclasses.replace(base, capture_recoater_mm=0.0))
    i = next(k for k, s in enumerate(fixed) if s.label == "capture:post_jet")
    assert fixed[i - 1].kind != "dwell"  # no camera-settle dwell; the mark fires in place
    assert fixed[i + 1].kind == "dwell" and fixed[i + 1].label == "camera capture hold"

    over = compile_print(
        dataclasses.replace(
            base, capture_recoater_mm=475.0, capture_settle_s=0.3, capture_hold_s=1.8
        )
    )
    for stage in ("pre_jet", "post_jet", "post_heat"):
        j = next(k for k, s in enumerate(over) if s.label == f"capture:{stage}")
        assert (over[j - 3].kind, over[j - 3].axis, over[j - 3].value) == (
            "move_abs",
            RECOATER,
            475.0,
        )
        assert over[j - 2].kind == "wait"
        assert over[j - 1].kind == "dwell" and over[j - 1].value == 0.3
        assert over[j - 1].label == "camera settle"
        assert over[j + 1].kind == "dwell" and over[j + 1].value == 1.8
        assert over[j + 1].label == "camera capture hold"


def test_capture_marks_carry_the_printing_layer_index() -> None:
    # A capture mark must record the PRINTING layer (1..N), not the absolute layer_no (with
    # precoats). The Runs CAD slice + layer labels key off it: with 2 precoats + 3 printing layers,
    # the printing captures land at absolute layers 3,4,5 but printing layers 1,2,3.
    base = PrintSettings()
    p = dataclasses.replace(
        base,
        thin_precoat=dataclasses.replace(base.thin_precoat, n_layers=2),
        printing=dataclasses.replace(base.printing, n_layers=3),
        postcoat=dataclasses.replace(base.postcoat, n_layers=0),
        capture_stages=True,
    )
    post_jets = [s for s in compile_print(p) if s.label == "capture:post_jet"]
    assert [s.layer for s in post_jets] == [3, 4, 5]  # absolute layer_no (precoats + printing)
    assert [s.print_layer for s in post_jets] == [1, 2, 3]  # printing / CAD index
    # precoat/non-capture steps have no printing-layer index
    precoat_marks = [s for s in compile_print(p) if s.kind == "mark" and s.phase == "thin_precoat"]
    assert all(s.print_layer is None for s in precoat_marks)


def test_capture_marks_emitted_at_each_process_boundary() -> None:
    # one_layer() disables captures for the pinned-sequence tests above; re-enable it here.
    plan = dataclasses.replace(one_layer(), capture_stages=True)
    steps = compile_print(plan)
    labels = [s.label for s in steps if s.kind == "mark"]

    assert labels.count("capture:pre_jet") == 1
    assert labels.count("capture:post_jet") == 1
    assert labels.count("capture:post_heat") == 1
    assert (
        labels.index("capture:pre_jet")
        < labels.index("capture:post_jet")
        < labels.index("capture:post_heat")
    )

    def last_move(axis: int, before: int) -> float | None:
        moves = [s.value for s in steps[:before] if s.axis == axis and s.kind == "move_abs"]
        return moves[-1] if moves else None

    # pre_jet: the printhead has NOT moved — it sits home. The camera rides the recoater gantry, so
    # no printhead park is needed or wanted (a mid-bed park at 250 would block the spread).
    i_pre_jet = next(i for i, s in enumerate(steps) if s.label == "capture:pre_jet")
    assert last_move(PRINTHEAD, i_pre_jet) is None

    # post_jet: gantries parked — recoater retracted home for the jet pass, printhead back home.
    i_post_jet = next(i for i, s in enumerate(steps) if s.label == "capture:post_jet")
    assert last_move(RECOATER, i_post_jet) == plan.recoater_home_mm
    assert last_move(PRINTHEAD, i_post_jet) == plan.printhead_home_mm

    # post_heat: the recoater sits at the heater sweep end (600) after the dwell, printhead home.
    # There is NO end-of-layer reposition to 950 — the recoater moves out to the spread start only
    # at the next layer's start, after that layer's feed preload (anti-backlash bug fix).
    i_post_heat = next(i for i, s in enumerate(steps) if s.label == "capture:post_heat")
    assert last_move(RECOATER, i_post_heat) == plan.heater_end_mm
    assert last_move(PRINTHEAD, i_post_heat) == plan.printhead_home_mm

    # capture:post_heat still precedes the ordinary layer_end mark.
    assert labels.index("capture:post_heat") < labels.index("layer_end")


def test_capture_stages_enabled_defaults_to_all_three() -> None:
    # Per-stage capture selection (#2): the default keeps every stage on, so enabling captures
    # behaves exactly as before (all of pre_jet / post_jet / post_heat).
    assert PrintSettings().capture_stages_enabled == ("pre_jet", "post_jet", "post_heat")


def test_compile_emits_only_the_enabled_capture_stages() -> None:
    # With capture_stages on but only post_jet selected, compile must emit ONLY the post_jet mark
    # — no pre_jet, no post_heat. This lets an operator capture just one/two stages to save disk.
    plan = dataclasses.replace(
        one_layer(), capture_stages=True, capture_stages_enabled=("post_jet",)
    )
    labels = [s.label for s in compile_print(plan) if s.kind == "mark"]
    assert labels.count("capture:post_jet") == 1
    assert labels.count("capture:pre_jet") == 0
    assert labels.count("capture:post_heat") == 0


def test_compile_emits_no_capture_marks_when_enabled_set_empty() -> None:
    # Master on but nothing selected = no stage captures (belt-and-suspenders; UI won't allow it).
    plan = dataclasses.replace(one_layer(), capture_stages=True, capture_stages_enabled=())
    labels = [s.label for s in compile_print(plan) if s.kind == "mark"]
    assert not any(lbl.startswith("capture:") for lbl in labels)


def test_bounded_filters_capture_stages_enabled_to_valid_canonical_order() -> None:
    # Untrusted input: keep only real stage names, dedupe, and force canonical order regardless of
    # the order/junk supplied. An absent key keeps the default (all three).
    lim = SafetyLimits()
    p = PrintSettings.bounded(
        {"capture_stages_enabled": ["post_heat", "bogus", "pre_jet", "pre_jet"]}, lim
    )
    assert p.capture_stages_enabled == ("pre_jet", "post_heat")
    assert PrintSettings.bounded({}, lim).capture_stages_enabled == (
        "pre_jet",
        "post_jet",
        "post_heat",
    )


def test_fixed_camera_captures_add_no_axis_motion() -> None:
    # A zero capture pose means a fixed camera: triggers add timing holds but cannot alter any axis
    # or heater command. Recoater-mounted operation is covered by the calibrated-pose test above.
    def machine_actions(plan: PrintSettings) -> list[tuple[str, int | None, float | None]]:
        return [
            (s.kind, s.axis, s.value)
            for s in compile_print(plan)
            if s.axis is not None or s.kind == "heater"
        ]

    off = machine_actions(dataclasses.replace(one_layer(), capture_stages=False))
    on = machine_actions(
        dataclasses.replace(one_layer(), capture_stages=True, capture_recoater_mm=0.0)
    )
    assert on == off


def test_capture_marks_absent_when_disabled() -> None:
    plan = dataclasses.replace(one_layer(), capture_stages=False)
    steps = compile_print(plan)
    assert not any(s.label.startswith("capture:") for s in steps if s.kind == "mark")


def test_bounded_passes_through_capture_stages() -> None:
    # bounded() must not silently reset capture_stages to the dataclass default — an operator
    # toggling captures via PUT /api/print-settings must have that value stick either way.
    lim = SafetyLimits()
    assert PrintSettings.bounded({"capture_stages": False}, lim).capture_stages is False
    assert PrintSettings.bounded({"capture_stages": True}, lim).capture_stages is True
    assert PrintSettings.bounded({}, lim).capture_stages is False  # default unchanged (off)
    assert PrintSettings.bounded({"capture_hold_s": 99}, lim).capture_hold_s == 10.0
    assert PrintSettings.bounded({"capture_hold_s": -1}, lim).capture_hold_s == 0.0


def test_estimate_duration_is_positive_and_scales_with_layers() -> None:
    from vention_printer_interface.control.print_settings import estimate_duration_s

    one = one_layer()
    ten = dataclasses.replace(one, printing=dataclasses.replace(one.printing, n_layers=10))
    t1, t10 = estimate_duration_s(one), estimate_duration_s(ten)
    # more layers -> materially more time (fixed homing/finish overhead means < 10x, not < 1x).
    assert t1 > 0 and t10 > t1 * 3
    # the whole default V1 plan runs well under 2 h; primed-start setup only homes two gantries.
    total = estimate_duration_s(PrintSettings())
    assert 0 < total < 7200


def test_estimate_duration_is_deterministic_and_pins_frontend_parity() -> None:
    # #6: the estimate is a deterministic constant-velocity model. This golden pins BOTH that the
    # backend value is stable AND the exact number the frontend estimateDurationS must reproduce for
    # the default plan at the default operator wait floor (0.25) — they diverged when UI used 0.5.
    assert estimate_duration_s(PrintSettings(), 0.25) == 395.0  # default has 0.15 mm build backlash
    # Same plan is byte-identical run to run (pure function of the plan + wait floor).
    assert estimate_duration_s(PrintSettings(), 0.25) == estimate_duration_s(PrintSettings(), 0.25)
    # A larger wait floor only ever raises the estimate (waits take max(pending, floor)).
    assert estimate_duration_s(PrintSettings(), 0.5) >= estimate_duration_s(PrintSettings(), 0.25)
