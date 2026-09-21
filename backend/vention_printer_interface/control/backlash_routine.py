"""Backlash-calibration routine: a small, thread-safe state machine around ``measure_backlash``.

Runs the (long, blocking) measurement while exposing a pollable snapshot for the UI. Always returns
the piston to its start position when it finishes — whether it completed, was cancelled, or errored
mid-way. The measurement itself is hardware-independent (driven through the ``Mover`` protocol); the
operator supplies a mover backed by the real controller, tests supply a fake one.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Any

from .backlash_cal import BacklashResult, Mover, measure_backlash


class BacklashRoutine:
    def __init__(
        self,
        mover: Mover,
        axis: int,
        positions: list[float],
        d_mm: float,
        reps: int,
        return_to_mm: float,
    ) -> None:
        self._mover = mover
        self._axis = axis
        self._positions = positions
        self._d_mm = d_mm
        self._reps = reps
        self._return_to_mm = return_to_mm
        self._lock = threading.Lock()
        self._state = "idle"  # idle | running | done | cancelled | error
        self._done = 0
        self._total = len(positions)
        self._current_ref: float | None = None
        self._result: BacklashResult | None = None
        self._error: str | None = None
        self._cancel = threading.Event()

    # -- control -------------------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    def start_thread(self) -> None:
        threading.Thread(target=self.run, daemon=True, name=f"backlash-cal-a{self._axis}").start()

    def run(self) -> None:
        with self._lock:
            self._state = "running"
        try:
            result = measure_backlash(
                self._mover,
                self._axis,
                self._positions,
                self._d_mm,
                self._reps,
                on_progress=self._on_progress,
                is_cancelled=self._cancel.is_set,
            )
            self._return_home()
            with self._lock:
                self._result = result
                self._state = "cancelled" if result.cancelled else "done"
        except Exception as exc:  # a stall/timeout or lost telemetry — surface it, don't crash
            self._safe_return_home()
            with self._lock:
                self._error = str(exc)
                self._state = "error"

    # -- internals -----------------------------------------------------------------------------
    def _on_progress(self, done: int, total: int, ref_mm: float) -> None:
        with self._lock:
            self._done = done
            self._total = total
            self._current_ref = ref_mm

    def _return_home(self) -> None:
        self._mover.move_abs(self._axis, self._return_to_mm)
        self._mover.settle(self._axis)

    def _safe_return_home(self) -> None:
        try:
            self._return_home()
        except Exception:
            pass  # already erroring; don't mask the original cause

    # -- reporting -----------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "axis": self._axis,
                "progress": {"done": self._done, "total": self._total},
                "current_ref_mm": self._current_ref,
                "result": None if self._result is None else _result_dict(self._result),
                "error": self._error,
            }


def _result_dict(result: BacklashResult) -> dict[str, Any]:
    return {
        "axis": result.axis,
        "recommended_mm": result.recommended_mm,
        "cancelled": result.cancelled,
        "positions": [asdict(p) for p in result.positions],
    }
