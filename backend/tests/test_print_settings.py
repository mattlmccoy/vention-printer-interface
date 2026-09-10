"""compile_print must reproduce the V1.py order exactly (vention/python/V1.py lines 92-190)."""

import dataclasses

import pytest

from vention_printer_interface.control.print_settings import (
    FEED,
    PART,
    PRINTHEAD,
    RECOATER,
    PhasePlan,
    PrintSettings,
    compile_print,
)
from vention_printer_interface.control.safety import SafetyLimits


def one_layer() -> PrintSettings:
    p = PrintSettings()
    return dataclasses.replace(
        p,
        thick_precoat=dataclasses.replace(p.thick_precoat, n_layers=0),
        thin_precoat=dataclasses.replace(p.thin_precoat, n_layers=0),
        printing=dataclasses.replace(p.printing, n_layers=1),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
        heater_enabled=True,
    )


def test_defaults_match_v1() -> None:
    p = PrintSettings()
    assert (p.thick_precoat.layer_thickness_mm, p.thick_precoat.n_layers) == (5.0, 3)
    assert (p.thin_precoat.layer_thickness_mm, p.thin_precoat.n_layers) == (0.2, 2)
    assert (p.printing.layer_thickness_mm, p.printing.n_layers) == (2.0, 10)
    assert (p.postcoat.layer_thickness_mm, p.postcoat.n_layers) == (5.0, 1)
    assert p.printing.part_speed == 2.5 and p.printing.part_accel == 15
    assert p.printing.recoater_speed == 100 and p.printing.recoater_accel == 500
    assert (p.feed_end_mm, p.recoater_end_mm, p.printhead_end_mm, p.heater_end_mm) == (
        145,
        930,
        840,
        600,
    )
    assert p.heater_speed == 50 and p.heater_accel == 250 and p.n_heater_passes == 1
    assert p.heater_enabled is False  # heater is opt-in
    assert p.n_jet_passes == 1 and p.pre_heater_drop_mm == 0.0 and p.postcoat_enabled is True
    # thick 5.0*3 + thin 0.2*2 + printing 2.0*10 + postcoat 5.0*1 = 40.4 mm over 16 layers
    assert p.total_thickness_mm == pytest.approx(40.4) and p.total_layers == 16


def test_new_fields_defaults() -> None:
    p = PrintSettings()
    assert p.thick_precoat.n_layers == 3 and p.thick_precoat.layer_thickness_mm == 5.0
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


def test_compile_one_print_layer_matches_v1_order() -> None:
    steps = compile_print(one_layer())
    kinds = [(s.kind, s.axis, s.value) for s in steps]
    setup = [
        ("home_all", None, None),
        ("wait", None, None),
        ("set_speed", FEED, 5.0),  # V1 used 1000 mm/s; bounded default is the feed limit
        ("set_accel", FEED, 30.0),
        ("move_abs", FEED, 145.0),
        ("wait", None, None),
    ]
    assert kinds[: len(setup)] == setup
    i = len(setup)
    phase_setup = kinds[i : i + 8]
    assert phase_setup == [
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
        ("mark", None, None),
        ("move_rel", PART, 2.0),
        ("wait", None, None),
        ("move_abs", RECOATER, 930.0),
        ("wait", None, None),
        ("move_rel", FEED, -2.0),
        ("wait", None, None),
        ("dwell", None, 1.0),
        ("move_abs", RECOATER, 5.0),
        ("wait", None, None),
        ("move_abs", PRINTHEAD, 840.0),
        ("wait", None, None),
        ("move_abs", PRINTHEAD, 5.0),
        ("wait", None, None),
        ("set_speed", RECOATER, 50.0),
        ("set_accel", RECOATER, 250.0),
        ("heater", None, 1.0),
        ("move_abs", RECOATER, 600.0),
        ("wait", None, None),
        ("move_abs", RECOATER, 5.0),
        ("wait", None, None),
        ("heater", None, 0.0),
        ("mark", None, None),
    ]
    assert kinds[i : i + len(layer)] == layer
    assert len(steps) == i + len(layer)
    assert steps[i].label == "layer_start" and steps[-1].label == "layer_end"
    assert steps[i].phase == "printing" and steps[i].layer == 1
    assert steps[i].part_height_mm == 2.0
    assert [s.index for s in steps] == list(range(len(steps)))


def test_printing_layer_multipass_and_pre_heater_drop() -> None:
    import dataclasses

    from vention_printer_interface.control.print_settings import PhasePlan
    p = dataclasses.replace(PrintSettings(),
        thick_precoat=PhasePlan(n_layers=0), thin_precoat=PhasePlan(n_layers=0),
        printing=PhasePlan(layer_thickness_mm=0.2, n_layers=1), postcoat=PhasePlan(n_layers=0),
        n_jet_passes=2, pre_heater_drop_mm=0.1, heater_enabled=True)
    ks = [(s.kind, s.axis, s.value) for s in compile_print(p)]
    jet = [i for i, k in enumerate(ks) if k == ("move_abs", PRINTHEAD, p.printhead_end_mm)]
    assert len(jet) == 2  # two jet passes
    i_drop = ks.index(("move_rel", PART, p.pre_heater_drop_mm))
    i_heater_on = next(i for i, k in enumerate(ks) if k[0] == "heater" and k[2] == 1.0)
    i_up = next(i for i, k in enumerate(ks)
               if k == ("move_rel", PART, -p.pre_heater_drop_mm) and i > i_heater_on)
    assert max(jet) < i_drop < i_heater_on < i_up  # jets → drop → heat → raise back up


def test_compile_precoat_has_no_printhead_or_heater_steps() -> None:
    p = dataclasses.replace(
        one_layer(),
        thick_precoat=PhasePlan(layer_thickness_mm=5, n_layers=1),
        printing=PhasePlan(layer_thickness_mm=2, n_layers=0),
    )
    steps = [s for s in compile_print(p) if s.phase == "thick_precoat"]
    assert steps and not any(s.axis == PRINTHEAD and s.kind.startswith("move") for s in steps)
    assert not any(s.kind == "heater" for s in steps)
    first_mark = next(s for s in steps if s.kind == "mark")
    # thick_precoat holds the build/part piston fixed, so the part height does not grow.
    assert first_mark.label == "layer_start" and first_mark.part_height_mm == 0.0
    # its body spreads then raises the feed piston by the layer thickness; the part never moves.
    assert not any(s.kind == "move_rel" and s.axis == PART for s in steps)
    assert ("move_abs", RECOATER, 930.0) in [(s.kind, s.axis, s.value) for s in steps]
    assert ("move_rel", FEED, -5.0) in [(s.kind, s.axis, s.value) for s in steps]


def test_compile_heater_disabled_emits_no_heater_steps_but_still_passes() -> None:
    p = dataclasses.replace(one_layer(), heater_enabled=False)
    steps = compile_print(p)
    assert not any(s.kind == "heater" for s in steps)
    assert sum(1 for s in steps if s.kind == "move_abs" and s.value == 600.0) == 1


def test_compile_multiple_heater_passes_and_layer_heights() -> None:
    p = dataclasses.replace(PrintSettings(), n_heater_passes=3)
    steps = compile_print(p)
    # printing has 10 layers x 3 heater passes = 30 moves to heater_end (precoats never heat)
    assert sum(1 for s in steps if s.kind == "move_abs" and s.value == 600.0) == 30
    # V1.py resets recoater speed at the top of print layers 2..N (the heater changed it)
    resets = [s for s in steps if s.kind == "set_speed" and s.axis == RECOATER and s.value == 100.0]
    # four non-empty phase setups (thick/thin precoat, printing, postcoat) + 9 per-layer resets
    assert len(resets) == 4 + 9
    # thick_precoat holds the build/part piston fixed, so its 3 layers add no part height; the
    # part height only grows through thin (0.2*2) + printing (2.0*10) + postcoat (5.0*1) = 25.4 mm.
    heights = [s.part_height_mm for s in steps if s.label == "layer_end"]
    assert heights[:3] == [0.0, 0.0, 0.0]  # 3 thick_precoat layers: part piston fixed
    assert heights[3] == pytest.approx(0.2)  # first thin_precoat layer (part down 0.2 mm)
    assert heights[4] == pytest.approx(0.4)  # second thin_precoat layer
    assert heights[5] == pytest.approx(2.4)  # first printing layer (+2.0 mm)
    assert heights[-1] == pytest.approx(25.4)  # last postcoat layer, part stack
    # 16 layers total still numbered 1..16: thick 3 + thin 2 + printing 10 + postcoat 1
    assert [s.layer for s in steps if s.label == "layer_start"] == list(range(1, 17))


def test_thick_precoat_layer_holds_part_and_spreads() -> None:
    p = dataclasses.replace(
        PrintSettings(),
        thick_precoat=PhasePlan(layer_thickness_mm=5.0, n_layers=1),
        thin_precoat=PhasePlan(n_layers=0),
        printing=PhasePlan(n_layers=0),
        postcoat=PhasePlan(n_layers=0),
    )
    steps = [s for s in compile_print(p) if s.phase == "thick_precoat"]
    ks = [(s.kind, s.axis, s.value) for s in steps]
    assert not any(k == "move_rel" and a == PART for (k, a, v) in ks)  # part piston fixed
    assert ("move_abs", RECOATER, p.recoater_end_mm) in ks             # spread
    assert ("move_rel", FEED, -5.0) in ks                              # feed up by the thick layer


def test_postcoat_toggle_off_emits_no_postcoat_steps() -> None:
    import dataclasses
    p_on = PrintSettings()
    p_off = dataclasses.replace(p_on, postcoat_enabled=False)
    assert any(s.phase == "postcoat" for s in compile_print(p_on))
    assert not any(s.phase == "postcoat" for s in compile_print(p_off))


def test_steps_are_frozen() -> None:
    s = compile_print(one_layer())[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.kind = "x"  # type: ignore[misc]


def test_estimate_duration_is_positive_and_scales_with_layers() -> None:
    from vention_printer_interface.control.print_settings import estimate_duration_s

    one = one_layer()
    ten = dataclasses.replace(one, printing=dataclasses.replace(one.printing, n_layers=10))
    t1, t10 = estimate_duration_s(one), estimate_duration_s(ten)
    assert t1 > 0 and t10 > t1 * 5
    # the default V1 plan: setup feed 145 mm at 5 mm/s = 29 s alone; whole print well under 2 h
    total = estimate_duration_s(PrintSettings())
    assert 29 < total < 7200
