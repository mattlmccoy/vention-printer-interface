"""Supervisory controller (spec §3): poll loop, ARM gate, E-STOP, protection, listeners.

Responsibilities (protection dominant):
1. Poll telemetry on a thread; every sample goes through ``safety.evaluate``. A trip stops all
   motion, forces the heater off and latches FAULT. Any read error is itself a protection event.
2. ARM gate: a connected controller is read-only until ``arm()``. Guarded: home, move, speed,
   accel, heater on. Never gated: stop_all, heater_off, estop, disarm.
3. All device IO is serialized behind ``_io_lock``.
The controller never turns the heater on by itself.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from vention_printer_interface.control.safety import SafetyDecision, SafetyLimits, evaluate
from vention_printer_interface.device.printer import PrinterDevice, Telemetry

log = logging.getLogger(__name__)
Listener = Callable[[dict[str, Any]], None]


class ControllerState(enum.StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    FAULT = "fault"
    CLOSED = "closed"


class Controller:
    def __init__(self, *, poll_interval_s: float = 0.2, limits: SafetyLimits | None = None) -> None:
        self.poll_interval_s = poll_interval_s
        self.limits = limits or SafetyLimits()
        self._device: PrinterDevice | None = None
        self.backend = "none"
        self.state = ControllerState.DISCONNECTED
        self.armed = False
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._listeners: list[Listener] = []
        self._telemetry: Telemetry | None = None
        self._last_read_done = time.monotonic()
        self._fault_reasons: tuple[str, ...] = ()
        self._warnings: tuple[str, ...] = ()
        self._heater_on_since: float | None = None
        self._move_pending = False
        self._read_error: str | None = None
        self._device_info: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle --------------------------------------------------------------------------
    def attach_device(self, device: PrinterDevice, *, backend: str) -> None:
        self.detach_device()
        with self._io_lock:
            try:
                info = device.identify()
            except Exception:
                device.close()
                raise
        with self._lock:
            self._device, self.backend, self._device_info = device, backend, info
            self.state, self.armed = ControllerState.CONNECTED, False
            self._fault_reasons, self._telemetry = (), None
            self._last_read_done = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vpi-poll", daemon=True)
        self._thread.start()

    def detach_device(self) -> None:
        thread = self._thread
        self._stop.set()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        dev = self._device
        if dev is not None:
            with self._io_lock:
                for step in (dev.stop_all, lambda: dev.heater_write(False), dev.close):
                    try:
                        step()
                    except Exception as exc:  # noqa: BLE001 - detach is best-effort, must finish
                        log.warning("detach step failed: %s", exc)
        with self._lock:
            self._device, self.backend, self._device_info = None, "none", {}
            self.state, self.armed = ControllerState.DISCONNECTED, False
            self._telemetry, self._fault_reasons, self._heater_on_since = None, (), None
            self._move_pending = False

    def stop(self) -> None:
        self.detach_device()
        self.state = ControllerState.CLOSED

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    # ---- poll loop --------------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.poll_interval_s)

    def _tick(self) -> None:
        dev = self._device
        if dev is None:
            return
        start = time.monotonic()
        age = start - self._last_read_done
        try:
            with self._io_lock:
                tel = dev.read_telemetry()
        except Exception as exc:  # noqa: BLE001 - any read error is a protection event
            with self._lock:
                self._read_error = str(exc)
            if self.state != ControllerState.FAULT:
                self._enter_fault((f"telemetry read failed: {exc}",))
            self._notify()
            return
        self._last_read_done = time.monotonic()
        if self.state == ControllerState.FAULT and tel.heater_on:
            # A fault action may have failed while the link was down; re-enforce the safe
            # state on every successful poll until the operator clears the fault.
            with self._io_lock:
                for step in (dev.stop_all, lambda: dev.heater_write(False)):
                    try:
                        step()
                    except Exception as exc:  # noqa: BLE001 - keep polling; retry next tick
                        log.warning("fault re-enforcement failed: %s", exc)
        with self._lock:
            self._read_error = None
            self._telemetry = tel
            if tel.heater_on and self._heater_on_since is None:
                self._heater_on_since = start
            if not tel.heater_on:
                self._heater_on_since = None
            heater_on_s = (start - self._heater_on_since) if self._heater_on_since else 0.0
            if all(tel.motion_complete.values()):
                self._move_pending = False
            decision: SafetyDecision = evaluate(
                tel, self.limits, age, heater_on_s, self._move_pending
            )
            self._warnings = decision.warnings
        if decision.trip and self.state != ControllerState.FAULT:
            self._enter_fault(decision.reasons)
        self._notify()

    def _enter_fault(self, reasons: tuple[str, ...]) -> None:
        log.error("FAULT: %s", "; ".join(reasons))
        dev = self._device
        if dev is not None:
            with self._io_lock:
                for step in (dev.stop_all, lambda: dev.heater_write(False)):
                    try:
                        step()
                    except Exception as exc:  # noqa: BLE001 - latch the fault regardless
                        log.warning("fault action failed: %s", exc)
        with self._lock:
            self.state, self.armed = ControllerState.FAULT, False
            self._fault_reasons, self._heater_on_since = reasons, None
            self._move_pending = False

    def clear_fault(self) -> None:
        with self._lock:
            if self.state != ControllerState.FAULT:
                return
            tel = self._telemetry
            if tel is None:
                raise RuntimeError("cannot clear fault: no telemetry")
            if self._read_error is not None:
                raise RuntimeError(f"cannot clear fault: last read failed: {self._read_error}")
            age = time.monotonic() - self._last_read_done
            d = evaluate(tel, self.limits, age, 0.0, False)
            if d.trip:
                raise RuntimeError("cannot clear fault: " + "; ".join(d.reasons))
            self.state, self._fault_reasons = ControllerState.CONNECTED, ()

    def _notify(self) -> None:
        snap = self.snapshot()
        for fn in list(self._listeners):
            try:
                fn(snap)
            except Exception as exc:  # noqa: BLE001 - a listener must never break the loop
                log.warning("listener failed: %s", exc)

    # ---- gates ------------------------------------------------------------------------------
    def _require_device(self) -> PrinterDevice:
        if self._device is None:
            raise RuntimeError("no device attached")
        return self._device

    def _require_armed(self) -> PrinterDevice:
        dev = self._require_device()
        if self.state == ControllerState.FAULT:
            raise RuntimeError("faulted: " + "; ".join(self._fault_reasons))
        if not self.armed:
            raise RuntimeError("not armed — press ARM to take control of the printer")
        return dev

    def arm(self) -> None:
        self._require_device()
        if self.state != ControllerState.CONNECTED:
            raise RuntimeError(f"cannot arm in state {self.state.value}")
        self.armed = True

    def disarm(self) -> None:
        self.heater_off()
        self.armed = False

    def set_limits(self, limits: SafetyLimits) -> None:
        self.limits = limits

    # ---- guarded actions --------------------------------------------------------------------
    def home_all(self) -> None:
        dev = self._require_armed()
        with self._io_lock:
            self._move_pending = True
            dev.home_all()

    def home(self, axis: int) -> None:
        dev = self._require_armed()
        with self._io_lock:
            self._move_pending = True
            dev.home(axis)

    def set_max_speed(self, axis: int, mm_s: float) -> float:
        dev = self._require_armed()
        v = self.limits.clamp_speed(axis, mm_s)
        with self._io_lock:
            dev.set_max_speed(axis, v)
        return v

    def set_max_accel(self, axis: int, mm_s2: float) -> float:
        dev = self._require_armed()
        v = self.limits.clamp_accel(axis, mm_s2)
        with self._io_lock:
            dev.set_max_accel(axis, v)
        return v

    def move_absolute(self, axis: int, mm: float) -> float:
        dev = self._require_armed()
        v = self.limits.clamp_position(axis, mm)
        with self._io_lock:
            self._move_pending = True
            dev.move_absolute(axis, v)
        return v

    def move_relative(self, axis: int, mm: float) -> float:
        """Relative moves are clamped by issuing an absolute move to the clamped target."""
        dev = self._require_armed()
        tel = self._telemetry
        here = tel.positions.get(axis, 0.0) if tel else 0.0
        target = self.limits.clamp_position(axis, here + mm)
        with self._io_lock:
            self._move_pending = True
            dev.move_absolute(axis, target)
        return target - here

    def heater_on(self) -> None:
        dev = self._require_armed()
        with self._io_lock:
            dev.heater_write(True)

    def estop_release(self) -> None:
        """Explicit operator action: release the software e-stop and re-energise drives."""
        dev = self._require_device()
        with self._io_lock:
            dev.estop_release()
            dev.estop_reset()

    # ---- safe-direction (ungated) -----------------------------------------------------------
    def stop_all(self) -> None:
        dev = self._require_device()
        with self._io_lock:
            dev.stop_all()

    def heater_off(self) -> None:
        dev = self._device
        if dev is None:
            return
        with self._io_lock:
            dev.heater_write(False)

    def estop(self) -> None:
        """Best-effort, bypasses every gate: stop, heater off, controller e-stop, disarm."""
        dev = self._device
        self.armed = False
        if dev is None:
            return
        with self._io_lock:
            steps = (
                dev.stop_all,
                lambda: dev.heater_write(False),
                lambda: dev.estop_trigger("vpi operator"),
            )
            for step in steps:
                try:
                    step()
                except Exception as exc:  # noqa: BLE001 - e-stop must complete every step
                    log.warning("e-stop step failed: %s", exc)

    # ---- snapshot ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tel = self._telemetry
            since = self._heater_on_since
            heater_on_s = (time.monotonic() - since) if since else 0.0
            return {
                "state": self.state.value,
                "backend": self.backend,
                "armed": self.armed,
                "fault_reasons": list(self._fault_reasons),
                "warnings": list(self._warnings),
                "read_error": self._read_error,
                "device": dict(self._device_info),
                "limits": self.limits.to_dict(),
                "heater": {
                    "on": bool(tel and tel.heater_on),
                    "on_s": round(heater_on_s, 1),
                    "max_on_s": self.limits.heater_max_on_s,
                },
                "telemetry": None
                if tel is None
                else {
                    "host_timestamp_ns": tel.host_timestamp_ns,
                    "positions": {str(k): v for k, v in tel.positions.items()},
                    "motion_complete": {str(k): v for k, v in tel.motion_complete.items()},
                    "estop_triggered": tel.estop_triggered,
                    "drives_ready": tel.drives_ready,
                    "health_ok": tel.health_ok,
                    "heater_on": tel.heater_on,
                },
            }
