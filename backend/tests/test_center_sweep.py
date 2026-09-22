"""Unit tests for camera-center-sweep pose selection (pure, no hardware)."""

from __future__ import annotations

from vention_printer_interface.vision.center_sweep import CenterResult, best_center_pose


def test_picks_the_min_offset_pose_with_subsample() -> None:
    # V-shaped piston-center offset (px) vs recoater pose (mm); minimum near 12.
    samples = [(8.0, 30.0), (10.0, 12.0), (12.0, 1.0), (14.0, 13.0), (16.0, 31.0)]
    r = best_center_pose(samples, start_pose_mm=8.0)
    assert isinstance(r, CenterResult)
    assert 11.5 <= r.pose_mm <= 12.5  # parabola vertex refines below the 2 mm step
    assert r.improved is True


def test_no_improvement_when_flat() -> None:
    samples = [(8.0, 5.0), (10.0, 5.0), (12.0, 5.0)]
    r = best_center_pose(samples, start_pose_mm=10.0)
    assert r.improved is False  # already as centred as any pose


def test_offset_px_is_reported_at_the_chosen_pose() -> None:
    samples = [(8.0, 30.0), (10.0, 12.0), (12.0, 1.0), (14.0, 13.0)]
    r = best_center_pose(samples, start_pose_mm=8.0)
    assert r.offset_px <= 1.0 + 1e-9  # at/below the best sampled offset
