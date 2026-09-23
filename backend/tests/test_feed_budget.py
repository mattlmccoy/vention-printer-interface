"""Feed-powder budget: does the feed column hold enough powder for the print?

Motivating incident (2026-09-22, run 20260922_175423_pyramid_graded_3d): a 184-layer job at
0.4 mm feed/layer needed ~74 mm of feed, the feed started at 20 mm, and the powder ran out at
layer ~52. The exhaustion guard in compile_print counted from feed_end_mm (145, a FULL column)
instead of the real feed position, so it never fired. Numbers below use binary-exact values
(0.5 mm steps) so layer counts can't drift with float rounding.
"""

import dataclasses

from vention_printer_interface.control.feed_budget import (
    feed_budget,
    live_feed_available_mm,
    print_feed_demand_mm,
)
from vention_printer_interface.control.print_settings import (
    PrintSettings,
    compile_print,
)


def _plan(
    n_print: int = 30, feed: float = 0.5, n_thin: int = 0, postcoat: bool = False
) -> PrintSettings:
    base = PrintSettings()
    return dataclasses.replace(
        base,
        thin_precoat=dataclasses.replace(
            base.thin_precoat, n_layers=n_thin, feed_thickness_mm=feed
        ),
        printing=dataclasses.replace(
            base.printing, n_layers=n_print, feed_thickness_mm=feed, layer_thickness_mm=0.25
        ),
        postcoat=dataclasses.replace(base.postcoat, n_layers=1, feed_thickness_mm=2.0),
        postcoat_enabled=postcoat,
        heater_enabled=False,
    )


def _layers_run(steps: tuple) -> int:  # type: ignore[type-arg]
    return sum(1 for s in steps if s.kind == "mark" and s.label == "layer_start")


# ---- compile_print honors the REAL feed position ---------------------------------------------


def test_compile_print_guard_counts_from_the_real_feed_position() -> None:
    plan = _plan(n_print=30, feed=0.5)  # feed_end_mm stays at the default 145 (a full column)
    assert _layers_run(compile_print(plan)) == 30  # default: assumes a full column (unchanged)
    steps = compile_print(plan, feed_start_mm=10.0)  # only 10 mm of powder actually in the feed
    # layer k+1 runs while 10 - 0.5*(k+1) > 0 -> 19 layers, then the safe stop
    assert _layers_run(steps) == 19
    assert steps[-1].kind == "mark" and steps[-1].label == "feed_exhausted"


# ---- demand ------------------------------------------------------------------------------------


def test_print_feed_demand_is_feed_per_layer_times_layers_for_enabled_phases() -> None:
    assert print_feed_demand_mm(_plan(n_print=30, feed=0.5, n_thin=2)) == 16.0  # 2*0.5 + 30*0.5
    assert print_feed_demand_mm(_plan(n_print=30, feed=0.5, postcoat=True)) == 17.0  # + 1*2.0
    # the pyramid job: 2 precoats + 184 printing layers at 0.4 mm feed
    base = PrintSettings()
    pyramid = dataclasses.replace(
        base,
        thin_precoat=dataclasses.replace(base.thin_precoat, n_layers=2, feed_thickness_mm=0.4),
        printing=dataclasses.replace(base.printing, n_layers=184, feed_thickness_mm=0.4),
        postcoat_enabled=False,
    )
    assert abs(print_feed_demand_mm(pyramid) - 74.4) < 1e-9


# ---- budget ------------------------------------------------------------------------------------


def test_budget_short_feed_reports_where_the_print_would_stop() -> None:
    b = feed_budget(_plan(n_print=30, feed=0.5), available_mm=10.0)
    assert b.sufficient is False
    assert (b.demand_mm, b.available_mm, b.layers_total, b.layers_supported) == (15.0, 10.0, 30, 19)


def test_budget_enough_feed_is_sufficient() -> None:
    b = feed_budget(_plan(n_print=30, feed=0.5), available_mm=16.0)
    assert b.sufficient is True
    assert b.layers_supported == 30


def test_budget_needs_strictly_more_than_the_demand() -> None:
    # The guard refuses a layer whose advance would REACH flush (<= 0), so exactly the demand is
    # one layer short. The budget must say so rather than promise a finish.
    b = feed_budget(_plan(n_print=30, feed=0.5), available_mm=15.0)
    assert b.sufficient is False and b.layers_supported == 29


def test_budget_unknown_feed_is_never_reported_as_sufficient() -> None:
    b = feed_budget(_plan(), available_mm=None)
    assert b.sufficient is None and b.layers_supported is None
    assert b.to_dict()["demand_mm"] == 15.0


# ---- reading the live feed position ------------------------------------------------------------


def test_live_feed_uses_a_referenced_position() -> None:
    snap = {"telemetry": {"positions": {"2": 20.0}, "referenced": {"2": True}}}
    assert live_feed_available_mm(snap) == (20.0, None)


def test_live_feed_unreferenced_is_unknown_with_a_reason() -> None:
    snap = {"telemetry": {"positions": {"2": 0.0}, "referenced": {"2": False}}}
    mm, why = live_feed_available_mm(snap)
    assert mm is None and why and "homed" in why


def test_live_feed_without_telemetry_is_unknown_with_a_reason() -> None:
    for snap in ({}, {"telemetry": None}, {"telemetry": {"positions": {}, "referenced": {}}}):
        mm, why = live_feed_available_mm(snap)
        assert mm is None and why
