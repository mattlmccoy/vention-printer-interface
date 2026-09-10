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
)
from vention_printer_interface.control.safety import SafetyLimits


def one_layer() -> PrintSettings:
    """Printing-only, one layer, heater on."""
    p = PrintSettings()
    return dataclasses.replace(
        p,
        thin_precoat=dataclasses.replace(p.thin_precoat, n_layers=0),
        printing=dataclasses.replace(p.printing, n_layers=1),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
        heater_enabled=True,
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
    # No setup move of any axis (pistons already primed; gantries only homed).
    assert not any(s.kind in ("move_abs", "move_rel") for s in setup)


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
    all_steps = [s for s in compile_print(thin_only()) if s.phase == "thin_precoat"]
    steps = [s for s in all_steps if s.kind not in ("set_speed", "set_accel")]
    ks = [(s.kind, s.axis, s.value) for s in steps]
    body = [
        ("mark", None, None),
        ("move_abs", RECOATER, 950.0),
        ("wait", None, None),
        ("move_rel", FEED, -0.4),  # feed advance 0.4 (nominal)
        ("wait", None, None),
        ("dwell", None, 1.0),
        ("move_rel", PART, 0.2),  # part drop 0.2 (nominal layer) — the print's FIRST part drop
        ("wait", None, None),
        ("move_abs", RECOATER, 350.0),  # precoat return, NOT home
        ("wait", None, None),
        ("mark", None, None),
    ]
    assert ks == body
    assert not any(s.axis == PRINTHEAD and s.kind.startswith("move") for s in all_steps)
    assert steps[0].part_height_mm == pytest.approx(0.2)  # part grew by one nominal layer


# ---- (d) printing layer: full sequence + concurrency + heater + finish ---------------------------


def test_compile_one_printing_layer_full_sequence() -> None:
    steps = compile_print(one_layer())
    kinds = [(s.kind, s.axis, s.value) for s in steps]

    # (a) setup — gantry homes + initial profiles (4 home/wait + 8 set_* = 12 steps)
    assert kinds[0:4] == [
        ("home", PRINTHEAD, None),
        ("wait", None, None),
        ("home", RECOATER, None),
        ("wait", None, None),
    ]
    n_setup = sum(1 for s in steps if s.phase == "setup")
    assert n_setup == 12

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
        ("move_abs", RECOATER, 950.0),     # spread
        ("wait", None, None),
        ("move_rel", FEED, -0.4),          # feed advance (feed advances during printing)
        ("wait", None, None),
        ("dwell", None, 1.0),
        ("move_rel", PART, 2.0),           # part drop
        ("wait", None, None),
        ("move_abs", RECOATER, 5.0),       # recoater home  \  concurrent: two moves,
        ("move_abs", PRINTHEAD, 900.0),    # printhead jet  /  then ONE wait
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
        ("move_abs", RECOATER, 950.0),     # recoater back to end
        ("wait", None, None),
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


def test_printing_multipass_shuttles_to_midpoint_then_home() -> None:
    p = dataclasses.replace(one_layer(), n_jet_passes=3, heater_enabled=False)
    ks = kinds_of(p)
    ends = [k for k in ks if k == ("move_abs", PRINTHEAD, 900.0)]
    mids = [k for k in ks if k == ("move_abs", PRINTHEAD, 250.0)]
    homes = [k for k in ks if k == ("move_abs", PRINTHEAD, 5.0)]
    assert len(ends) == 3  # 3 jet passes out to the end
    assert len(mids) == 2  # between-pass returns stop at the midpoint (save travel)
    assert len(homes) == 1  # only the last pass returns fully home to clear the recoat
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
