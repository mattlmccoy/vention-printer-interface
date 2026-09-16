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
