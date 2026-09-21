import importlib.util
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "piston_sweep", Path(__file__).resolve().parents[1] / "scripts" / "piston_sweep.py"
)
assert _spec and _spec.loader
piston_sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(piston_sweep)


def _row(step_size: float, direction: str, prev_cmd: float, target: float, actual_step: float,
         prev_actual: float) -> dict[str, Any]:
    step_cmd = round(target - prev_cmd, 4)
    return {
        "step_size": step_size, "direction": direction,
        "commanded_mm": round(target, 4),
        "step_cmd_mm": step_cmd, "step_actual_mm": round(actual_step, 4),
        "step_err_mm": round(actual_step - step_cmd, 4),
    }


def test_settle_update_latches_on_a_steady_at_rest_position() -> None:
    su = piston_sweep.settle_update
    # not complete → never settled; the window resets so a pre-completion reading can't count.
    w, done = su([131.9], 132.0, complete=False, need=3)
    assert done is None and w == []
    w, done = [], None
    for pos in (132.0, 132.0, 132.0):
        w, done = su(w, pos, complete=True, need=3)
    assert done == 132.0


def test_settle_update_tolerates_a_one_count_dither_at_rest() -> None:
    # A ±0.1 mm (one readout count) flicker at rest MUST latch — the old exact-equality (1e-4 mm)
    # check never would, so it spun until the 30 s timeout on a boundary-parked position.
    su = piston_sweep.settle_update
    w, done = [], None
    for pos in (132.1, 132.0, 132.1):
        w, done = su(w, pos, complete=True, need=3)
    assert done is not None


def test_settle_update_keeps_waiting_while_still_travelling() -> None:
    su = piston_sweep.settle_update
    w, done = [], None
    for pos in (130.0, 131.0, 132.0):  # >1 count between samples: still moving
        w, done = su(w, pos, complete=True, need=3)
    assert done is None


def test_wall_reached_trips_only_when_advance_stops() -> None:
    wr = piston_sweep.wall_reached
    assert wr([], 0.2) is False
    assert wr([0.2], 0.2) is False                 # need two samples
    assert wr([0.2, 0.2], 0.2) is False            # tracking cleanly
    assert wr([0.2, 0.1], 0.2) is False            # still advancing (sum 0.3 >= 0.1)
    assert wr([0.1, 0.0], 0.2) is True             # last two sum 0.1 < half a step → wall
    assert wr([0.0, 0.0], 0.2) is True             # dead against the stop


def test_settle_ready_waits_for_the_move_to_register() -> None:
    # The bug: right after a move is issued, motion_complete is still True from the PREVIOUS move for
    # a few polls, so settle would return the STALE pre-move position. settle_ready gates acceptance
    # until we've SEEN motion_complete go False (the move registered) OR the start grace elapsed (a
    # no-op move that's already at target).
    sr = piston_sweep.settle_ready
    assert sr(saw_incomplete=False, elapsed_s=0.1, start_grace_s=0.4) is False  # too early, no move yet
    assert sr(saw_incomplete=True, elapsed_s=0.1, start_grace_s=0.4) is True    # move registered
    assert sr(saw_incomplete=False, elapsed_s=0.5, start_grace_s=0.4) is True   # no-op grace elapsed


def test_median_is_robust_to_an_outlier_rep() -> None:
    md = piston_sweep.median
    assert md([-0.4, -0.6, -0.7, 0.2, -0.1]) == -0.4   # the +0.2 outlier doesn't move the middle
    assert md([-0.6]) == -0.6
    assert md([-0.6, -0.4]) == -0.5                     # even count → mean of the two middles
    assert md([]) == 0.0


def test_backlash_from_pair_is_the_bidirectional_gap() -> None:
    bp = piston_sweep.backlash_from_pair
    # target reached descending settles 0.15 mm deeper than reached ascending → 0.15 mm lash
    assert bp(132.0, 131.85) == 0.15
    assert bp(70.0, 70.0) == 0.0


def test_build_targets_down_and_up_cover_the_span() -> None:
    down = piston_sweep.build_targets(5.0, 1.0, 0.2, "down")
    assert down == [5.2, 5.4, 5.6, 5.8, 6.0]           # descends away from start
    up = piston_sweep.build_targets(5.0, 1.0, 0.2, "up")
    assert up == [5.8, 5.6, 5.4, 5.2, 5.0]             # climbs back to start


def test_analyze_flags_a_deterministic_dropped_step() -> None:
    # Every pass: the 0.2 mm step FROM 5.4 mm drops to 0 (piston does not move), and the next step
    # doubles to 0.4 — the exact "zero then double" pattern, recurring at the same position.
    rows: list[dict[str, Any]] = []
    for _pass in range(3):
        prev_cmd, prev_actual = 5.2, 5.2
        for target in (5.4, 5.6, 5.8):
            if abs(prev_cmd - 5.4) < 1e-9:      # the step FROM 5.4 -> 5.6 is dropped
                actual_step = 0.0
            elif abs(prev_cmd - 5.6) < 1e-9:    # the step FROM 5.6 -> 5.8 doubles to catch up
                actual_step = 0.4
            else:
                actual_step = 0.2
            rows.append(_row(0.2, "down", prev_cmd, target, actual_step, prev_actual))
            prev_cmd, prev_actual = target, prev_actual + actual_step
    out = piston_sweep.analyze_sweep(rows)
    assert "DETERMINISTIC" in out["verdict"]
    dloc = out["deterministic_error_locations"]
    locs = {(d["from_mm"], round(d["mean_err_mm"], 2)) for d in dloc}
    assert (5.4, -0.2) in locs   # the dropped step, recurring
    assert (5.6, 0.2) in locs    # the doubled step, recurring
    assert out["by_step_size"]["0.2"]["all"]["frac_bad"] > 0.0


def test_analyze_clean_sweep_reports_no_error() -> None:
    rows = []
    for _pass in range(3):
        prev_cmd, prev_actual = 5.0, 5.0
        for target in (5.2, 5.4, 5.6):
            rows.append(_row(0.2, "down", prev_cmd, target, 0.2, prev_actual))
            prev_cmd, prev_actual = target, prev_actual + 0.2
    out = piston_sweep.analyze_sweep(rows)
    assert out["deterministic_error_locations"] == []
    assert out["by_step_size"]["0.2"]["all"]["frac_bad"] == 0.0
