"""Unit tests for the backlash routine state machine (no hardware, synchronous)."""

from __future__ import annotations

from vention_printer_interface.control.backlash_routine import BacklashRoutine


class FakeLashMover:
    def __init__(self, lash_mm: float, start_mm: float = 5.0) -> None:
        self.lash = lash_mm
        self.pos = start_mm
        self.commands: list[float] = []

    def move_abs(self, axis: int, mm: float) -> None:
        self.commands.append(mm)
        self.pos = mm if mm >= self.pos else mm - self.lash

    def settle(self, axis: int) -> float:
        return self.pos


def test_routine_runs_to_done_and_returns_home() -> None:
    mover = FakeLashMover(lash_mm=0.2, start_mm=5.0)
    r = BacklashRoutine(mover, axis=1, positions=[15.0, 30.0], d_mm=2.0, reps=3, return_to_mm=5.0)
    r.run()
    snap = r.snapshot()
    assert snap["state"] == "done"
    assert snap["progress"] == {"done": 2, "total": 2}
    assert snap["result"]["recommended_mm"] == 0.2
    assert len(snap["result"]["positions"]) == 2
    assert mover.commands[-1] == 5.0  # returned to the start position


def test_routine_reports_error_state_on_mover_failure() -> None:
    class Boom(FakeLashMover):
        def settle(self, axis: int) -> float:
            raise TimeoutError("axis did not settle")

    r = BacklashRoutine(Boom(0.1), axis=1, positions=[15.0], d_mm=2.0, reps=1, return_to_mm=5.0)
    r.run()
    snap = r.snapshot()
    assert snap["state"] == "error"
    assert "settle" in snap["error"]


def test_routine_cancel_stops_and_marks_cancelled() -> None:
    mover = FakeLashMover(lash_mm=0.2)
    r = BacklashRoutine(mover, axis=2, positions=[15.0, 30.0, 45.0], d_mm=2.0, reps=2,
                        return_to_mm=5.0)
    r.cancel()  # cancel before it starts -> no positions completed
    r.run()
    snap = r.snapshot()
    assert snap["state"] == "cancelled"
    assert snap["result"]["positions"] == []
    assert mover.commands[-1] == 5.0  # still returns home after a cancel


def test_snapshot_before_run_is_idle() -> None:
    r = BacklashRoutine(FakeLashMover(0.0), axis=1, positions=[15.0], d_mm=2.0, reps=1,
                        return_to_mm=5.0)
    assert r.snapshot()["state"] == "idle"
