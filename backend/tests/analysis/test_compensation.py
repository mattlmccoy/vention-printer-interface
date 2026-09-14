"""Structured scale/yaw compensation extraction (Lane A, Task 2).

NOTE ON THE PLAN'S TEST VALUES (documented deviation):
The plan's ``test_scale_and_yaw_from_metrics`` asserts the *un-deadbanded* scale for
``spacing_y_error_pct=0.045567`` while its ``test_deadband_and_missing`` deadbands a
0.01% error to 1.0 — but 0.045567% is itself *below* the plan's stated 0.05% deadband,
so both assertions cannot hold at a 0.05% deadband. The task's verified contract pins the
deadband at 0.05%, so we keep 0.05% and make the tests self-consistent with it:
0.045567% is therefore deadbanded (below 0.05%), and we exercise the raw scale formula
with errors clearly above the band.
"""

from __future__ import annotations

from vention_printer_interface.analysis.compensation import Compensation, to_compensation


def test_scale_and_yaw_from_metrics() -> None:
    # Both spacing errors are above the 0.05% deadband, so the raw scale formula applies.
    comp = to_compensation(
        dot={"spacing_x_error_pct": -0.437860, "spacing_y_error_pct": 0.200000},
        checkerboard={"angle_deg": 1.30, "checkerboard_angle_error_deg": 1.30},
    )
    assert isinstance(comp, Compensation)
    # scale = 1/(1+err/100): printed slightly small in X -> enlarge (>1)
    assert abs(comp.scale_x - (1 / (1 - 0.437860 / 100))) < 1e-6
    assert comp.scale_x > 1.0
    assert abs(comp.scale_y - (1 / (1 + 0.200000 / 100))) < 1e-6
    assert comp.scale_y < 1.0
    # yaw comes from the checkerboard angle only
    assert comp.yaw_deg is not None
    assert abs(comp.yaw_deg - 1.30) < 1e-6
    assert comp.human  # non-empty recommendation text
    assert comp.deadband_pct == 0.05


def test_deadband_zeros_small_errors() -> None:
    # 0.01% and 0.045567% are both inside the 0.05% deadband -> no correction.
    comp = to_compensation(
        dot={"spacing_x_error_pct": 0.01, "spacing_y_error_pct": 0.045567},
        checkerboard={},
    )
    assert comp.scale_x == 1.0
    assert comp.scale_y == 1.0


def test_missing_checkerboard_gives_no_yaw() -> None:
    comp = to_compensation(dot={"spacing_x_error_pct": 0.01}, checkerboard={})
    assert comp.scale_x == 1.0
    assert comp.scale_y == 1.0  # no spacing_y data -> no correction
    assert comp.yaw_deg is None  # no checkerboard -> no yaw


def test_missing_dot_gives_unit_scale() -> None:
    comp = to_compensation(dot=None, checkerboard={"checkerboard_angle_error_deg": 0.5})
    assert comp.scale_x == 1.0
    assert comp.scale_y == 1.0
    assert comp.yaw_deg is not None
    assert abs(comp.yaw_deg - 0.5) < 1e-6


def test_nonfinite_metrics_are_ignored() -> None:
    comp = to_compensation(
        dot={"spacing_x_error_pct": float("nan"), "spacing_y_error_pct": float("nan")},
        checkerboard={"found": 0, "checkerboard_angle_error_deg": float("nan")},
    )
    assert comp.scale_x == 1.0
    assert comp.scale_y == 1.0
    assert comp.yaw_deg is None
