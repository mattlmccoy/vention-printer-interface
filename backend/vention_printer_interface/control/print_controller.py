"""Print step machine (spec §4): runs compiled steps through the guarded Controller.

Ticked from the Controller listener (poll thread). One step in flight at a time; non-blocking
steps (speed, accel, move issue, heater, mark) are issued back to back until a ``wait`` or
``dwell`` step, which completes only when every axis reports motion complete AND at least
``min_wait_s`` has passed since the move was issued (the controller may not have registered the
move on the very next poll — the V1.py sleep quirk). A wait that exceeds ``step_timeout_s`` is a
protection event: stop all, heater off, FAULT. A controller FAULT or disarm aborts the print.
The heater is switched only through ``Controller.heater_on/off`` (armed-gated), and fires only
when the plan's ``heater_enabled`` is set.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.print_settings import (
    PART,
    PrintSettings,
    Step,
    compile_print,
)

log = logging.getLogger(__name__)
EventHook = Callable[[str, dict[str, Any]], None]


class PrintState(enum.StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ABORTED = "aborted"
    FAULT = "fault"


class PrintController:
    def __init__(
        self,
        controller: Controller,
        *,
        min_wait_s: float = 0.5,
        step_timeout_s: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._c = controller
        self.min_wait_s = min_wait_s
        self.step_timeout_s = step_timeout_s
        self._clock = clock
        self._lock = threading.RLock()
        self.on_event: EventHook | None = None
        self._reset(None)

    def _reset(
        self,
        plan: PrintSettings | None,
        steps: tuple[Step, ...] | None = None,
        feed_start_mm: float | None = None,
    ) -> None:
        self.plan = plan
        self.macro: str | None = None
        self.steps: tuple[Step, ...] = (
            steps if steps is not None
            else (compile_print(plan, feed_start_mm=feed_start_mm) if plan else ())
        )
        self.part_zero_mm: float | None = None
        self.state = PrintState.IDLE
        self.step_index = 0  # next step to issue
        self.single_step = False
        self.reason = ""
        self._pause_requested = False
        self._step_granted = False
        self._in_flight: Step | None = None
        self._issued_at = 0.0
        # Whether we've SEEN the move(s) preceding the in-flight wait actually run (motion_complete
        # went False). Lets a wait end as soon as the move finishes, instead of always sitting out
        # the min_wait_s floor. Reset whenever a wait/dwell goes in-flight.
        self._saw_incomplete = False
        self._started_at = 0.0
        self._finished_at: float | None = None
        self._layer = 0
        self._phase = ""
        self._height = 0.0

    # ---- operator actions -------------------------------------------------------------------
    def start(
        self, plan: PrintSettings, single_step: bool = False, feed_start_mm: float | None = None
    ) -> None:
        """Start ``plan``. ``feed_start_mm`` is the powder actually in the feed column (the
        referenced feed depth); the feed-exhaustion guard counts down from it so the print stops
        safely when the powder runs out. None keeps the old full-column assumption."""
        with self._lock:
            if self.state in (PrintState.RUNNING, PrintState.PAUSED):
                raise RuntimeError("a print is already running")
            reasons = plan.validate(self._c.limits)
            if reasons:
                raise RuntimeError("print settings invalid: " + "; ".join(reasons))
            self._c._require_armed()
            self._reset(plan, feed_start_mm=feed_start_mm)
            self.single_step = single_step
            self.part_zero_mm = self._part_position()
            self.state = PrintState.RUNNING
            self._started_at = self._clock()
        self._emit("print_started", {"n_steps": len(self.steps)})

    def start_macro(self, name: str, steps: tuple[Step, ...]) -> None:
        """Run a park macro on the same machine (armed-gated, pausable, abortable)."""
        with self._lock:
            if self.state in (PrintState.RUNNING, PrintState.PAUSED):
                raise RuntimeError("a print or macro is already running")
            if not steps:
                raise RuntimeError("macro has no steps")
            self._c._require_armed()
            self._reset(None, steps)
            self.macro = name
            self.state = PrintState.RUNNING
            self._started_at = self._clock()
        self._emit("macro_started", {"macro": name, "n_steps": len(steps)})

    def _part_position(self) -> float | None:
        tel = self._c.snapshot().get("telemetry")
        if not tel:
            return None
        value = tel["positions"].get(str(PART))
        return float(value) if isinstance(value, int | float) else None

    def pause(self) -> None:
        with self._lock:
            if self.state == PrintState.RUNNING:
                self._pause_requested = True

    def resume(self) -> None:
        with self._lock:
            if self.state != PrintState.PAUSED:
                return
            self._c._require_armed()
            self.single_step = False
            self._pause_requested = False
            self.state = PrintState.RUNNING
        self._emit("print_resumed", {})

    def step(self) -> None:
        """Single-step mode: allow the next step group to run, then pause again."""
        with self._lock:
            if self.state != PrintState.PAUSED:
                return
            self._c._require_armed()
            self._step_granted = True
            self.state = PrintState.RUNNING

    def set_single_step(self, on: bool) -> None:
        """Toggle single-step mode during a run (Feature 2).

        Turning it ON pauses after the current step completes (``_advance``'s pause logic acts on
        ``single_step``). Turning it OFF while paused leaves single-step and resumes continuous
        running, mirroring ``resume``; turning it OFF while running just clears the flag.
        """
        resumed = False
        with self._lock:
            self.single_step = on
            if not on and self.state == PrintState.PAUSED:
                self._c._require_armed()
                self._pause_requested = False
                self._step_granted = False
                self.state = PrintState.RUNNING
                resumed = True
        if resumed:
            self._emit("print_resumed", {})

    def seek(self, index: int) -> None:
        """Jump to a compiled step (Feature 3). Paused-only: the routine continues from ``index``
        on the next resume, so the operator owns the resulting machine state."""
        with self._lock:
            if self.state != PrintState.PAUSED:
                raise RuntimeError("pause the print before jumping to a step")
            self.step_index = max(0, min(int(index), len(self.steps)))
            self._in_flight = None
            new_index = self.step_index
        # Record the jump so post-run analysis knows this was a debug seek (its first executed layer
        # has no valid cumulative baseline -> its accuracy is suppressed, not a false huge error).
        self._emit("print_seeked", {"index": new_index})

    def abort(self, reason: str = "operator abort") -> None:
        self._stop_safe()
        with self._lock:
            if self.state not in (PrintState.RUNNING, PrintState.PAUSED):
                return
            self.state, self.reason = PrintState.ABORTED, reason
            self._finished_at = self._clock()
        self._emit("print_aborted", {"reason": reason})

    def _fault(self, reason: str) -> None:
        self._stop_safe()
        with self._lock:
            self.state, self.reason = PrintState.FAULT, reason
            self._finished_at = self._clock()
        self._emit("print_fault", {"reason": reason})

    def _stop_safe(self) -> None:
        for fn in (self._c.stop_all, self._c.heater_off):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - best effort; keep going
                log.warning("print stop step failed: %s", exc)

    # ---- tick (poll thread) -----------------------------------------------------------------
    def tick(self, snapshot: dict[str, Any]) -> None:
        emit: tuple[str, dict[str, Any]] | None
        with self._lock:
            if self.state != PrintState.RUNNING:
                return
            if snapshot["state"] != ControllerState.CONNECTED.value or not snapshot["armed"]:
                self.state = PrintState.ABORTED
                self.reason = "controller " + (
                    "fault: " + "; ".join(snapshot["fault_reasons"])
                    if snapshot["state"] == ControllerState.FAULT.value
                    else "disarmed / disconnected"
                )
                self._finished_at = self._clock()
                emit = ("print_aborted", {"reason": self.reason})
            else:
                emit = self._advance(snapshot)
        if emit:
            self._emit(*emit)

    def _advance(self, snapshot: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        now = self._clock()
        inflight = self._in_flight
        if inflight is not None:
            if not self._blocking_done(inflight, snapshot, now):
                if now - self._issued_at > self.step_timeout_s:
                    self.state, self.reason = (
                        PrintState.FAULT,
                        (
                            f"timeout: step {inflight.index} ({inflight.kind}) not complete after "
                            f"{self.step_timeout_s:.0f}s"
                        ),
                    )
                    self._finished_at = now
                    self._stop_safe()
                    return ("print_fault", {"reason": self.reason})
                return None
            self._in_flight = None
            if inflight.phase == "setup" and inflight.index == 1 and self.macro is None:
                self.part_zero_mm = (
                    self._part_position()
                )  # after home: the build piston's true zero
            if self._pause_requested or (self.single_step and not self._step_granted):
                self._pause_requested, self._step_granted = False, False
                self.state = PrintState.PAUSED
                return ("print_paused", {"step_index": self.step_index})
            self._step_granted = False
        # Issue steps until a blocking one is in flight (or the print ends).
        while self.step_index < len(self.steps):
            step = self.steps[self.step_index]
            self.step_index += 1
            event = self._issue(step, now)
            if step.kind in ("wait", "dwell"):
                self._in_flight, self._issued_at = step, now
                self._saw_incomplete = False  # haven't seen the preceding move run yet
                return event
            if step.kind == "hold":
                self.state = PrintState.PAUSED
                return ("hold", {"step_index": self.step_index, "message": step.label})
            if event:
                return event
        self.state = PrintState.DONE
        self._finished_at = now
        if self.macro:
            return ("macro_done", {"macro": self.macro})
        return ("print_done", {"layers": self._layer, "part_height_mm": self._height})

    def _blocking_done(self, step: Step, snapshot: dict[str, Any], now: float) -> bool:
        if step.kind == "dwell":
            return now - self._issued_at >= float(step.value or 0.0)
        tel = snapshot.get("telemetry") or {}
        complete = tel.get("motion_complete") or {}
        all_complete = bool(complete) and all(complete.values())
        if not all_complete:
            self._saw_incomplete = True  # the preceding move has registered and is running
            return False
        # Every axis reports complete. Accept as soon as we've SEEN the move run (fast path — the
        # common case), OR once min_wait_s has elapsed. The floor is the fallback for a no-op move
        # that never leaves the complete state, and the guard against a stale "complete" that
        # predates the move being registered on the controller.
        return self._saw_incomplete or now - self._issued_at >= self.min_wait_s

    def _issue(self, step: Step, now: float) -> tuple[str, dict[str, Any]] | None:
        self._phase, self._layer, self._height = step.phase, step.layer, step.part_height_mm
        try:
            if step.kind == "home_all":
                self._c.home_all()
            elif step.kind == "home":
                self._c.home(step.axis or 0)
            elif step.kind == "set_speed":
                self._c.set_max_speed(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "set_accel":
                self._c.set_max_accel(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "move_abs":
                self._c.move_absolute(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "move_rel":
                self._c.move_relative(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "seat_part":
                # Absolute build-height seat: value is the cumulative commanded height from the
                # primed datum; command move_absolute(datum + value). part_zero_mm set at start().
                base = self.part_zero_mm if self.part_zero_mm is not None else 0.0
                self._c.move_absolute(step.axis or PART, base + float(step.value or 0.0))
            elif step.kind == "heater":
                if step.value:
                    self._c.heater_on()
                    return ("heater_on", {"step": step.index})
                self._c.heater_off()
                return ("heater_off", {"step": step.index})
            elif step.kind == "mark":
                data = {
                    "layer": step.layer,
                    "phase": step.phase,
                    "part_height_mm": step.part_height_mm,
                    "elapsed_s": round(now - self._started_at, 3),
                }
                if step.print_layer is not None:
                    # Printing (CAD) layer index for capture marks — excludes precoats; the Runs CAD
                    # slice + layer labels key off this, not the absolute `layer`.
                    data["print_layer"] = step.print_layer
                if step.label and step.label.startswith("capture:"):
                    label = step.label  # vision capture marks pass through unchanged
                elif step.label == "layer_start":
                    label = "layer_started"
                else:
                    label = "layer_completed"
                return (label, data)
            elif step.kind == "hold":
                return None
        except Exception as exc:  # noqa: BLE001 - any issue failure is a print fault
            self.state, self.reason = PrintState.FAULT, f"step {step.index} failed: {exc}"
            self._finished_at = now
            self._stop_safe()
            return ("print_fault", {"reason": self.reason})
        return None

    def _emit(self, label: str, data: dict[str, Any]) -> None:
        hook = self.on_event
        if hook is None:
            return
        try:
            hook(label, data)
        except Exception as exc:  # noqa: BLE001 - an event sink must never break the print
            log.warning("print event hook failed: %s", exc)

    # ---- snapshot ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            end = self._finished_at or self._clock()
            elapsed = (end - self._started_at) if self._started_at else 0.0
            cur = self._in_flight
            if cur is None and 0 < self.step_index <= len(self.steps):
                cur = self.steps[self.step_index - 1]
            here = self._part_position()
            measured = (
                round(here - self.part_zero_mm, 3)
                if here is not None and self.part_zero_mm is not None
                else None
            )
            return {
                "state": self.state.value,
                "macro": self.macro,
                "part_zero_mm": self.part_zero_mm,
                "part_height_measured_mm": measured,
                "step_index": self.step_index,
                "n_steps": len(self.steps),
                "phase": self._phase,
                "layer": self._layer,
                "n_layers": self.plan.total_layers if self.plan else 0,
                "part_height_mm": self._height,
                "elapsed_s": round(elapsed, 1),
                "single_step": self.single_step,
                "reason": self.reason,
                "current_step": None
                if cur is None
                else {
                    "index": cur.index,
                    "kind": cur.kind,
                    "axis": cur.axis,
                    "value": cur.value,
                    "label": cur.label,
                },
                "plan": self.plan.to_dict() if self.plan else None,
            }
