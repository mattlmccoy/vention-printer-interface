"""Unit tests for the in-process settle poller (no hardware).

The critical case is the settle-race guard: right after a move is issued the controller can still
report ``motion_complete = True`` from the PREVIOUS move for a few polls. A naive settle would
accept that and return the stale PRE-move position. ``settle`` must wait until the move registers
(motion_complete goes False) or the start grace elapses before accepting a completed+stable reading.
"""

from __future__ import annotations

import pytest

from vention_printer_interface.control.settle import (
    READOUT_MM,
    settle,
    settle_ready,
    settle_update,
)


def _sample(axis: int, pos: float, complete: bool) -> dict:
    return {"telemetry": {"positions": {str(axis): pos}, "motion_complete": {str(axis): complete}}}


def test_settle_update_resets_while_incomplete() -> None:
    window, settled = settle_update([1.0, 1.0], 5.0, complete=False)
    assert window == [] and settled is None


def test_settle_update_latches_within_one_count() -> None:
    # Three readings spanning <= one 0.1 mm count while complete -> settled on the last.
    w, s = settle_update([], 30.0, complete=True, need=3)
    w, s = settle_update(w, 30.1, complete=True, need=3)
    w, s = settle_update(w, 30.0, complete=True, need=3)
    assert s == 30.0


def test_settle_update_not_settled_when_spread_exceeds_tol() -> None:
    w, s = settle_update([], 30.0, complete=True, need=3)
    w, s = settle_update(w, 30.5, complete=True, need=3)
    w, s = settle_update(w, 31.0, complete=True, need=3)
    assert s is None


def test_settle_ready_guards_until_move_registers() -> None:
    assert settle_ready(saw_incomplete=False, elapsed_s=0.0, start_grace_s=0.4) is False
    assert settle_ready(saw_incomplete=True, elapsed_s=0.0, start_grace_s=0.4) is True
    assert settle_ready(saw_incomplete=False, elapsed_s=0.5, start_grace_s=0.4) is True


def test_settle_ignores_stale_complete_and_returns_new_position() -> None:
    axis = 1
    # Stale "complete at the pre-move position 10.0", then the move registers (incomplete),
    # then it completes and holds at the NEW position 30.0.
    samples = [
        _sample(axis, 10.0, True),   # stale complete from the previous move
        _sample(axis, 10.0, True),   # still stale
        _sample(axis, 22.0, False),  # move registered — motion_complete went False
        _sample(axis, 30.0, True),
        _sample(axis, 30.0, True),
        _sample(axis, 30.0, True),
    ]
    it = iter(samples)
    clock = {"t": 0.0}

    def read() -> dict:
        return next(it)

    def now() -> float:
        return clock["t"]

    def sleep(_s: float) -> None:
        clock["t"] += 0.05

    got = settle(read, axis, poll_s=0.05, stable_needed=3, start_grace_s=0.4,
                 timeout_s=5.0, now=now, sleep=sleep)
    assert got == 30.0  # the NEW position, never the stale 10.0


def test_settle_times_out_when_never_stable() -> None:
    axis = 2
    clock = {"t": 0.0}

    def read() -> dict:
        return _sample(axis, clock["t"] * 100.0, False)  # perpetually moving

    def now() -> float:
        return clock["t"]

    def sleep(_s: float) -> None:
        clock["t"] += 0.05

    with pytest.raises(TimeoutError):
        settle(read, axis, timeout_s=0.3, now=now, sleep=sleep)


def test_readout_mm_constant() -> None:
    assert READOUT_MM == 0.1
