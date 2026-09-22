"""Unit tests for the piston backlash-calibration core (no hardware).

The measurement is validated against a fake mover that simulates a piston with a KNOWN constant
lash L: a target reached while the position is increasing (approached from below, "descending" in
piston terms) settles exactly on the command; a target reached while the position is decreasing
(approached from above, "ascending") undershoots by L. So backlash_from_pair recovers L, and the
recommended comp is L snapped to the 0.1 mm readout.
"""

from __future__ import annotations

import pytest

from vention_printer_interface.control.backlash_cal import (
    READOUT_MM,
    backlash_from_pair,
    default_positions,
    measure_backlash,
    median,
    preflight_problems,
    recommend_comp,
    validate_probe,
)


def _ok_snapshot(axis: int = 1) -> dict:
    return {
        "state": "connected",
        "armed": True,
        "read_error": None,
        "heater": {"on": False},
        "telemetry": {
            "positions": {str(axis): 20.0},
            "referenced": {str(axis): True},
        },
    }


class FakeLashMover:
    """A piston with constant lash L. Records every commanded move so tests can assert the
    approach pattern. settle() returns the direction-dependent settled position."""

    def __init__(self, lash_mm: float, start_mm: float = 0.0) -> None:
        self.lash = lash_mm
        self.pos = start_mm
        self.commands: list[float] = []
        self._cancel_after: int | None = None

    def move_abs(self, axis: int, mm: float) -> None:
        self.commands.append(mm)
        increasing = mm >= self.pos
        # Arrived from below -> lands on command; from above -> undershoots by the lash L.
        self.pos = mm if increasing else mm - self.lash

    def settle(self, axis: int) -> float:
        return self.pos


def test_median_even_and_odd() -> None:
    assert median([]) == 0.0
    assert median([2.0]) == 2.0
    assert median([1.0, 3.0]) == 2.0
    assert median([5.0, 1.0, 3.0]) == 3.0


def test_backlash_from_pair_is_descending_minus_ascending() -> None:
    # a_desc reached from below, a_asc reached from above: gap = lost motion.
    assert backlash_from_pair(30.0, 29.8) == 0.2
    assert backlash_from_pair(30.0, 30.0) == 0.0


def test_recommend_comp_snaps_to_readout() -> None:
    # median of per-position |lash| medians, snapped to 0.1 mm.
    assert recommend_comp([0.18, 0.22, 0.2]) == 0.2
    assert recommend_comp([]) == 0.0
    assert recommend_comp([0.0, 0.0]) == 0.0


def test_recommend_comp_floors_to_one_count_when_any_lash_seen() -> None:
    # A tiny but non-zero lash must not round down to 0 (would disable comp on a real cylinder).
    assert recommend_comp([0.03, 0.02]) == READOUT_MM


def test_measure_backlash_recovers_known_constant_lash() -> None:
    mover = FakeLashMover(lash_mm=0.2)
    result = measure_backlash(mover, axis=1, positions=[15.0, 30.0, 45.0], d_mm=2.0, reps=4)
    assert result.axis == 1
    assert not result.cancelled
    assert [round(p.ref_mm, 4) for p in result.positions] == [15.0, 30.0, 45.0]
    for p in result.positions:
        assert p.backlash_mag_median_mm == 0.2
    assert result.recommended_mm == 0.2


def test_measure_backlash_reports_progress_with_the_completed_position() -> None:
    seen: list[tuple[int, int, float]] = []
    mover = FakeLashMover(lash_mm=0.1)
    measure_backlash(
        mover, axis=2, positions=[10.0, 20.0], d_mm=2.0, reps=2,
        # on_progress now carries the just-completed PositionResult (for live plotting).
        on_progress=lambda done, total, pos: seen.append((done, total, pos.ref_mm)),
    )
    assert seen[-1][0] == seen[-1][1] == 2
    assert [s[2] for s in seen[:2]] == [10.0, 20.0]


def test_default_positions_for_72mm_matches_confirm_recipe() -> None:
    assert default_positions(72.0) == [14.4, 28.8, 43.2, 54.0]


def test_default_positions_clamps_and_dedups_for_small_travel() -> None:
    pos = default_positions(10.0)
    assert pos == sorted(set(pos))  # unique, ascending
    assert all(3.0 <= p <= 7.0 for p in pos)  # inside [edge, max-edge]


def test_validate_probe_accepts_points_with_room_for_dither() -> None:
    validate_probe(72.0, [14.4, 54.0], 2.0)  # does not raise


def test_validate_probe_rejects_dither_past_the_max() -> None:
    with pytest.raises(ValueError):
        validate_probe(72.0, [71.0], 2.0)  # 71 + 2 = 73 > 72


def test_validate_probe_rejects_dither_below_zero() -> None:
    with pytest.raises(ValueError):
        validate_probe(72.0, [1.0], 2.0)  # 1 - 2 = -1 < 0


def test_validate_probe_rejects_empty_or_nonpositive_dither() -> None:
    with pytest.raises(ValueError):
        validate_probe(72.0, [], 2.0)
    with pytest.raises(ValueError):
        validate_probe(72.0, [30.0], 0.0)


def test_preflight_passes_on_a_healthy_armed_referenced_axis() -> None:
    assert preflight_problems(_ok_snapshot(1), axis=1, print_running=False) == []


def test_preflight_flags_each_unsafe_condition() -> None:
    s = _ok_snapshot(1)
    s["armed"] = False
    assert any("arm" in p.lower() for p in preflight_problems(s, 1, False))

    s = _ok_snapshot(1)
    s["telemetry"]["referenced"]["1"] = False
    assert any("referenc" in p.lower() for p in preflight_problems(s, 1, False))

    s = _ok_snapshot(1)
    s["heater"]["on"] = True
    assert any("heater" in p.lower() for p in preflight_problems(s, 1, False))

    s = _ok_snapshot(1)
    s["state"] = "disconnected"
    assert any("connect" in p.lower() for p in preflight_problems(s, 1, False))

    s = _ok_snapshot(1)
    s["read_error"] = "timeout"
    assert any("read" in p.lower() for p in preflight_problems(s, 1, False))

    assert any("print" in p.lower() for p in preflight_problems(_ok_snapshot(1), 1, True))


def test_measure_backlash_stops_when_cancelled() -> None:
    mover = FakeLashMover(lash_mm=0.2)
    calls = {"n": 0}

    def cancel_after_first() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # let the first position through, cancel before the second

    result = measure_backlash(
        mover, axis=1, positions=[15.0, 30.0, 45.0], d_mm=2.0, reps=2,
        is_cancelled=cancel_after_first,
    )
    assert result.cancelled
    assert len(result.positions) == 1  # only the first ref completed
