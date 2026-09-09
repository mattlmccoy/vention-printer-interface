"""Recipe step machine (spec §4): runs compiled steps through the guarded Controller.

Ticked from the Controller listener (poll thread). One step in flight at a time; non-blocking
steps (speed, accel, move issue, heater, mark) are issued back to back until a ``wait`` or
``dwell`` step, which completes only when every axis reports motion complete AND at least
``min_wait_s`` has passed since the move was issued (the controller may not have registered the
move on the very next poll — the V1.py sleep quirk). A wait that exceeds ``step_timeout_s`` is a
protection event: stop all, heater off, FAULT. A controller FAULT or disarm aborts the recipe.
The heater is switched only through ``Controller.heater_on/off`` (armed-gated) and never in a
dry run.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.recipe import RecipePlan, Step, compile_recipe

log = logging.getLogger(__name__)
EventHook = Callable[[str, dict[str, Any]], None]


class RecipeState(enum.StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    ABORTED = "aborted"
    FAULT = "fault"


class RecipeController:
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

    def _reset(self, plan: RecipePlan | None) -> None:
        self.plan = plan
        self.steps: tuple[Step, ...] = compile_recipe(plan) if plan else ()
        self.state = RecipeState.IDLE
        self.step_index = 0  # next step to issue
        self.dry_run = False
        self.single_step = False
        self.reason = ""
        self._pause_requested = False
        self._step_granted = False
        self._in_flight: Step | None = None
        self._issued_at = 0.0
        self._started_at = 0.0
        self._finished_at: float | None = None
        self._layer = 0
        self._phase = ""
        self._height = 0.0

    # ---- operator actions -------------------------------------------------------------------
    def start(self, plan: RecipePlan, dry_run: bool = False, single_step: bool = False) -> None:
        with self._lock:
            if self.state in (RecipeState.RUNNING, RecipeState.PAUSED):
                raise RuntimeError("recipe already running")
            reasons = plan.validate(self._c.limits)
            if reasons:
                raise RuntimeError("recipe invalid: " + "; ".join(reasons))
            self._c._require_armed()
            self._reset(plan)
            self.dry_run, self.single_step = dry_run, single_step
            self.state = RecipeState.RUNNING
            self._started_at = self._clock()
        self._emit("recipe_started", {"n_steps": len(self.steps), "dry_run": dry_run})

    def pause(self) -> None:
        with self._lock:
            if self.state == RecipeState.RUNNING:
                self._pause_requested = True

    def resume(self) -> None:
        with self._lock:
            if self.state != RecipeState.PAUSED:
                return
            self._c._require_armed()
            self.single_step = False
            self._pause_requested = False
            self.state = RecipeState.RUNNING
        self._emit("recipe_resumed", {})

    def step(self) -> None:
        """Single-step mode: allow the next step group to run, then pause again."""
        with self._lock:
            if self.state != RecipeState.PAUSED:
                return
            self._c._require_armed()
            self._step_granted = True
            self.state = RecipeState.RUNNING

    def abort(self, reason: str = "operator abort") -> None:
        self._stop_safe()
        with self._lock:
            if self.state not in (RecipeState.RUNNING, RecipeState.PAUSED):
                return
            self.state, self.reason = RecipeState.ABORTED, reason
            self._finished_at = self._clock()
        self._emit("recipe_aborted", {"reason": reason})

    def _fault(self, reason: str) -> None:
        self._stop_safe()
        with self._lock:
            self.state, self.reason = RecipeState.FAULT, reason
            self._finished_at = self._clock()
        self._emit("recipe_fault", {"reason": reason})

    def _stop_safe(self) -> None:
        for fn in (self._c.stop_all, self._c.heater_off):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - best effort; keep going
                log.warning("recipe stop step failed: %s", exc)

    # ---- tick (poll thread) -----------------------------------------------------------------
    def tick(self, snapshot: dict[str, Any]) -> None:
        emit: tuple[str, dict[str, Any]] | None
        with self._lock:
            if self.state != RecipeState.RUNNING:
                return
            if snapshot["state"] != ControllerState.CONNECTED.value or not snapshot["armed"]:
                self.state = RecipeState.ABORTED
                self.reason = "controller " + (
                    "fault: " + "; ".join(snapshot["fault_reasons"])
                    if snapshot["state"] == ControllerState.FAULT.value
                    else "disarmed / disconnected"
                )
                self._finished_at = self._clock()
                emit = ("recipe_aborted", {"reason": self.reason})
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
                        RecipeState.FAULT,
                        (
                            f"timeout: step {inflight.index} ({inflight.kind}) not complete after "
                            f"{self.step_timeout_s:.0f}s"
                        ),
                    )
                    self._finished_at = now
                    self._stop_safe()
                    return ("recipe_fault", {"reason": self.reason})
                return None
            self._in_flight = None
            if self._pause_requested or (self.single_step and not self._step_granted):
                self._pause_requested, self._step_granted = False, False
                self.state = RecipeState.PAUSED
                return ("recipe_paused", {"step_index": self.step_index})
            self._step_granted = False
        # Issue steps until a blocking one is in flight (or the recipe ends).
        while self.step_index < len(self.steps):
            step = self.steps[self.step_index]
            self.step_index += 1
            event = self._issue(step, now)
            if step.kind in ("wait", "dwell"):
                self._in_flight, self._issued_at = step, now
                return event
            if event:
                return event
        self.state = RecipeState.DONE
        self._finished_at = now
        return ("recipe_done", {"layers": self._layer, "part_height_mm": self._height})

    def _blocking_done(self, step: Step, snapshot: dict[str, Any], now: float) -> bool:
        if step.kind == "dwell":
            return now - self._issued_at >= float(step.value or 0.0)
        tel = snapshot.get("telemetry") or {}
        complete = tel.get("motion_complete") or {}
        return (
            now - self._issued_at >= self.min_wait_s and bool(complete) and all(complete.values())
        )

    def _issue(self, step: Step, now: float) -> tuple[str, dict[str, Any]] | None:
        self._phase, self._layer, self._height = step.phase, step.layer, step.part_height_mm
        try:
            if step.kind == "home_all":
                self._c.home_all()
            elif step.kind == "set_speed":
                self._c.set_max_speed(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "set_accel":
                self._c.set_max_accel(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "move_abs":
                self._c.move_absolute(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "move_rel":
                self._c.move_relative(step.axis or 0, float(step.value or 0.0))
            elif step.kind == "heater":
                if self.dry_run:
                    return None
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
                label = "layer_started" if step.label == "layer_start" else "layer_completed"
                return (label, data)
        except Exception as exc:  # noqa: BLE001 - any issue failure is a recipe fault
            self.state, self.reason = RecipeState.FAULT, f"step {step.index} failed: {exc}"
            self._finished_at = now
            self._stop_safe()
            return ("recipe_fault", {"reason": self.reason})
        return None

    def _emit(self, label: str, data: dict[str, Any]) -> None:
        hook = self.on_event
        if hook is None:
            return
        try:
            hook(label, data)
        except Exception as exc:  # noqa: BLE001 - an event sink must never break the recipe
            log.warning("recipe event hook failed: %s", exc)

    # ---- snapshot ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            end = self._finished_at or self._clock()
            elapsed = (end - self._started_at) if self._started_at else 0.0
            cur = self._in_flight
            if cur is None and 0 < self.step_index <= len(self.steps):
                cur = self.steps[self.step_index - 1]
            return {
                "state": self.state.value,
                "step_index": self.step_index,
                "n_steps": len(self.steps),
                "phase": self._phase,
                "layer": self._layer,
                "n_layers": self.plan.total_layers if self.plan else 0,
                "part_height_mm": self._height,
                "elapsed_s": round(elapsed, 1),
                "dry_run": self.dry_run,
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
