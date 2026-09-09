"""compile_recipe must reproduce the V1.py order exactly (vention/python/V1.py lines 92-190)."""

import dataclasses

import pytest

from vention_printer_interface.control.recipe import (
    FEED,
    PART,
    PRINTHEAD,
    RECOATER,
    PhasePlan,
    RecipePlan,
    compile_recipe,
)
from vention_printer_interface.control.safety import SafetyLimits


def one_layer() -> RecipePlan:
    p = RecipePlan()
    return dataclasses.replace(
        p,
        precoat=dataclasses.replace(p.precoat, n_layers=0),
        printing=dataclasses.replace(p.printing, n_layers=1),
        postcoat=dataclasses.replace(p.postcoat, n_layers=0),
        heater_enabled=True,
    )


def test_defaults_match_v1() -> None:
    p = RecipePlan()
    assert (p.precoat.layer_thickness_mm, p.precoat.n_layers) == (5.0, 1)
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
    assert p.total_thickness_mm == 30.0 and p.total_layers == 12


def test_validate_defaults_ok_and_printability() -> None:
    assert RecipePlan().validate() == []
    p = dataclasses.replace(RecipePlan(), printing=PhasePlan(layer_thickness_mm=2, n_layers=100))
    reasons = p.validate()
    assert any("thickness" in r for r in reasons)
    p2 = dataclasses.replace(RecipePlan(), recoater_end_mm=5000)
    assert any("recoater_end_mm" in r for r in p2.validate())
    p3 = dataclasses.replace(RecipePlan(), printing=PhasePlan(layer_thickness_mm=0, n_layers=1))
    assert any("layer_thickness" in r for r in p3.validate())


def test_bounded_clamps_speeds_and_positions() -> None:
    lim = SafetyLimits()
    p = RecipePlan.bounded({"feed_fast_speed": 1000, "recoater_end_mm": 5000}, lim)
    assert p.feed_fast_speed == lim.max_speed[FEED]
    assert p.recoater_end_mm == lim.travel_max[RECOATER]
    p2 = RecipePlan.bounded({"printing": {"recoater_speed": 9999, "n_layers": 5}}, lim)
    assert p2.printing.recoater_speed == lim.max_speed[RECOATER] and p2.printing.n_layers == 5


def test_round_trip_dict() -> None:
    p = one_layer()
    assert RecipePlan.from_dict(p.to_dict()) == p


def test_compile_one_print_layer_matches_v1_order() -> None:
    steps = compile_recipe(one_layer())
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


def test_compile_precoat_has_no_printhead_or_heater_steps() -> None:
    p = dataclasses.replace(
        one_layer(),
        precoat=PhasePlan(layer_thickness_mm=5, n_layers=1),
        printing=PhasePlan(layer_thickness_mm=2, n_layers=0),
    )
    steps = [s for s in compile_recipe(p) if s.phase == "precoat"]
    assert steps and not any(s.axis == PRINTHEAD and s.kind.startswith("move") for s in steps)
    assert not any(s.kind == "heater" for s in steps)
    first_mark = next(s for s in steps if s.kind == "mark")
    assert first_mark.label == "layer_start" and first_mark.part_height_mm == 5.0


def test_compile_heater_disabled_emits_no_heater_steps_but_still_passes() -> None:
    p = dataclasses.replace(one_layer(), heater_enabled=False)
    steps = compile_recipe(p)
    assert not any(s.kind == "heater" for s in steps)
    assert sum(1 for s in steps if s.kind == "move_abs" and s.value == 600.0) == 1


def test_compile_multiple_heater_passes_and_layer_heights() -> None:
    p = dataclasses.replace(RecipePlan(), n_heater_passes=3)
    steps = compile_recipe(p)
    assert sum(1 for s in steps if s.kind == "move_abs" and s.value == 600.0) == 30
    # V1.py resets recoater speed at the top of print layers 2..N (the heater changed it)
    resets = [s for s in steps if s.kind == "set_speed" and s.axis == RECOATER and s.value == 100.0]
    assert len(resets) == 3 + 9  # three phase setups + 9 per-layer resets (print layers 2..10)
    heights = [s.part_height_mm for s in steps if s.label == "layer_end"]
    assert heights[0] == 5.0 and heights[1] == 7.0 and heights[-1] == 30.0
    assert [s.layer for s in steps if s.label == "layer_start"] == list(range(1, 13))


def test_steps_are_frozen() -> None:
    s = compile_recipe(one_layer())[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.kind = "x"  # type: ignore[misc]


def test_estimate_duration_is_positive_and_scales_with_layers() -> None:
    from vention_printer_interface.control.recipe import estimate_duration_s

    one = one_layer()
    ten = dataclasses.replace(one, printing=dataclasses.replace(one.printing, n_layers=10))
    t1, t10 = estimate_duration_s(one), estimate_duration_s(ten)
    assert t1 > 0 and t10 > t1 * 5
    # the default V1 plan: setup feed 145 mm at 5 mm/s = 29 s alone; whole print well under 2 h
    total = estimate_duration_s(RecipePlan())
    assert 29 < total < 7200
