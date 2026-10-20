"""Automatic calibration: the recoater positions a sweep visits (vision/autocal_plan.py).

Spec docs/superpowers/specs/2026-10-20-auto-calibration-design.md §5–6: positions centred on the
capture pose, inside the operator's safety window (default 0–523 mm), every one approached from the
same side (descending mm, after one pre-approach move above the first)."""

from __future__ import annotations

import pytest

from vention_printer_interface.vision.autocal_plan import plan_sweep


def test_poses_are_descending_and_include_the_capture_pose() -> None:
    p = plan_sweep(463.3, 0.0, 523.0, step_mm=5.0, max_offset_mm=20.0)
    assert p.poses == [483.3, 478.3, 473.3, 468.3, 463.3, 458.3, 453.3, 448.3, 443.3]
    assert p.pre_approach_mm == 488.3
    assert p.capture_mm == 463.3


def test_window_clips_and_pre_approach_stays_inside() -> None:
    p = plan_sweep(520.0, 0.0, 523.0, step_mm=5.0, max_offset_mm=20.0)
    assert max(p.poses) <= 523.0 and p.pre_approach_mm <= 523.0
    assert 520.0 in p.poses and min(p.poses) == 500.0


def test_capture_pose_outside_window_is_refused() -> None:
    with pytest.raises(ValueError, match="capture pose"):
        plan_sweep(600.0, 0.0, 523.0)


def test_inverted_or_empty_window_is_refused() -> None:
    with pytest.raises(ValueError, match="window"):
        plan_sweep(100.0, 200.0, 50.0)


def test_non_positive_step_is_refused() -> None:
    with pytest.raises(ValueError, match="step"):
        plan_sweep(100.0, 0.0, 523.0, step_mm=0)
