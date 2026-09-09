from vention_printer_interface.control.macros import MACROS, macro_steps
from vention_printer_interface.control.print_settings import FEED, PART
from vention_printer_interface.control.safety import SafetyLimits


def test_load_cart_homes_then_lowers_both_pistons() -> None:
    steps = macro_steps("load_cart", SafetyLimits())
    kinds = [(s.kind, s.axis, s.value) for s in steps]
    assert kinds[0] == ("home_all", None, None) and kinds[1] == ("wait", None, None)
    moves = [k for k in kinds if k[0] == "move_abs"]
    assert (("move_abs", FEED, 145.0) in moves) and (("move_abs", PART, 145.0) in moves)
    assert kinds[-1] == ("wait", None, None)
    assert all(s.phase == "load_cart" for s in steps)


def test_clear_bed_is_home_all_only() -> None:
    steps = macro_steps("clear_bed", SafetyLimits())
    assert [s.kind for s in steps] == ["home_all", "wait"]


def test_unknown_macro() -> None:
    try:
        macro_steps("nope", SafetyLimits())
    except KeyError as exc:
        assert "load_cart" in str(exc)
    else:
        raise AssertionError
    assert set(MACROS) == {"load_cart", "clear_bed"}


def test_load_cart_respects_tightened_travel() -> None:
    steps = macro_steps("load_cart", SafetyLimits.bounded(travel_max={"1": 100, "2": 120}))
    moves = {s.axis: s.value for s in steps if s.kind == "move_abs"}
    assert moves == {PART: 100.0, FEED: 120.0}
