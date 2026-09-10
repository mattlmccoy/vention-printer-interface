"""Supervisory controller (spec §3): poll loop, ARM gate, E-STOP, protection, listeners.

Responsibilities (protection dominant):
1. Poll telemetry on a thread; every sample goes through ``safety.evaluate``. A trip latches FAULT
   and disarms FIRST, then stops all motion and forces the heater off (review H1: no window where
   a command can slip in after the stop). Any read error is itself a protection event. While
   faulted, every successful poll re-enforces stop + heater-off until the operator clears.
2. ARM gate: a connected controller is read-only until ``arm()``, which needs a fresh, clean
   sample. Guarded: home, move, speed, accel, heater on. Never gated: stop_all, heater_off,
   estop, disarm.
3. All device IO is serialized behind ``_io_lock`` (except homing, whose reply may block until
   the axis has homed — UNVERIFIED — so it must not stall the poll loop).
4. The heater watchdog counts from the earlier of "commanded on" and "observed on" so it works
   even if the relay state is never echoed back (review C1).
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
# /health is slow on the real controller, so it is NOT polled in the protection loop by default
# (health_refresh_s=0). It is fetched once at connect; a slow refresh can be enabled explicitly.
ESTOP_READY_WAIT_S = 10.0  # SDK resetSystem waits for areSmartDrivesReady (MachineMotion.py:2459)
HOMING_WINDOW_S = 30.0  # position limits are suspended for this long after a home is issued
REFERENCE_MATCH_TOL_MM = 2.0  # a reconnect keeps reference only if positions return within this


def reconcile_reference(
    referenced: set[int],
    saved: dict[int, float],
    current: dict[int, float],
    tol: float,
) -> set[int]:
    """After telemetry recovers (a reconnect), keep an axis referenced only if its position came
    back within `tol` of the last good value. A real MM power-cycle collapses incremental drives
    to ~0, so those axes fail the match and drop; a mere disconnect leaves positions unchanged."""
    kept: set[int] = set()
    for axis in referenced:
        s, c = saved.get(axis), current.get(axis)
        if s is not None and c is not None and abs(c - s) <= tol:
            kept.add(axis)
    return kept


class ControllerState(enum.StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    FAULT = "fault"
    CLOSED = "closed"


class Controller:
    def __init__(
        self,
        *,
        poll_interval_s: float = 0.2,
        limits: SafetyLimits | None = None,
        health_refresh_s: float = 0.0,
    ) -> None:
        self.poll_interval_s = poll_interval_s
        self.health_refresh_s = health_refresh_s
        self._last_health = 0.0
        self._homing_until = 0.0
        self._home_issued_at = 0.0
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
        self._heater_on_since: float | None = None  # observed
        self._heater_cmd_on_since: float | None = None  # commanded
        self._move_pending = False
        self._read_error: str | None = None
        self._device_info: dict[str, Any] = {}
        self._safe_actions_at = 0.0  # a fault is clearable only from a sample taken after this
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ticks = 0
        # Incremental drives read ~0 after a power-cycle, not true position. An axis is "referenced"
        # only after a home settles, and reverts the moment telemetry contact is lost or e-stop
        # asserts. Unreferenced positions must never be presented as truth (data-contract §5).
        self._referenced_axes: set[int] = set()
        self._homing_axes: set[int] = set()
        self._reference_positions: dict[int, float] = {}  # last good positions, for reconnect match
        self._reference_suspect = False  # a read failed; reconcile reference on the next good read

    # ---- lifecycle --------------------------------------------------------------------------
    def attach_device(self, device: PrinterDevice, *, backend: str) -> None:
        self.detach_device()
        with self._io_lock:
            try:
                info = device.identify()
            except Exception:
                device.close()
                raise
        stop = threading.Event()
        with self._lock:
            self._device, self.backend, self._device_info = device, backend, info
            self.state, self.armed = ControllerState.CONNECTED, False
            self._fault_reasons, self._telemetry, self._read_error = (), None, None
            self._heater_on_since = self._heater_cmd_on_since = None
            self._move_pending, self._ticks = False, 0
            self._last_read_done = self._last_health = time.monotonic()
            self._homing_until = self._home_issued_at = 0.0
            self._referenced_axes, self._homing_axes = set(), set()  # a fresh link is unreferenced
            self._reference_positions, self._reference_suspect = {}, False
            self._stop = stop
        self._thread = threading.Thread(
            target=self._loop, args=(device, stop), name="vpi-poll", daemon=True
        )
        self._thread.start()

    def detach_device(self) -> None:
        thread = self._thread
        self._stop.set()  # the loop bound to THIS event exits; a stuck read cannot outlive it
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        dev = self._device
        with self._lock:
            self._device, self.backend, self._device_info = None, "none", {}
            self.state, self.armed = ControllerState.DISCONNECTED, False
            self._telemetry, self._fault_reasons = None, ()
            self._heater_on_since = self._heater_cmd_on_since = None
            self._move_pending, self._read_error = False, None
        if dev is not None:
            with self._io_lock:
                for step in (dev.stop_all, lambda: dev.heater_write(False), dev.close):
                    try:
                        step()
                    except Exception as exc:  # noqa: BLE001 - detach is best-effort, must finish
                        log.warning("detach step failed: %s", exc)

    def stop(self) -> None:
        self.detach_device()
        self.state = ControllerState.CLOSED

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    # ---- poll loop --------------------------------------------------------------------------
    def _loop(self, dev: PrinterDevice, stop: threading.Event) -> None:
        while not stop.is_set():
            self._tick(dev, stop)
            stop.wait(self.poll_interval_s)

    def _tick(self, dev: PrinterDevice, stop: threading.Event) -> None:
        if stop.is_set() or dev is not self._device:
            return
        previous_read = self._last_read_done
        self._ticks += 1
        refresh = (
            self.health_refresh_s > 0
            and time.monotonic() - self._last_health >= self.health_refresh_s
        )
        try:
            with self._io_lock:
                tel = dev.read_telemetry(refresh_health=refresh)
        except Exception as exc:  # noqa: BLE001 - any read error is a protection event
            if stop.is_set() or dev is not self._device:
                return  # orphaned thread: its device is gone, its result is meaningless
            with self._lock:
                self._read_error = str(exc)
                # Lost contact: don't drop reference yet — a reconnect where the MM kept power comes
                # back with positions unchanged. Reconcile on the next good read (drop only axes
                # whose position moved, i.e. a real power-cycle). Homing can't survive the gap.
                self._reference_suspect = True
                self._homing_axes.clear()
            if self.state != ControllerState.FAULT:
                self._enter_fault((f"telemetry read failed: {exc}",))
            self._notify()
            return
        if stop.is_set() or dev is not self._device:
            return
        now = time.monotonic()
        # A health refresh includes a slow /health call; don't judge that tick stale on its own
        # duration. Normal ticks measure age after the read (review H6).
        age = self.poll_interval_s if refresh else now - previous_read
        self._last_read_done = now
        if refresh:
            self._last_health = now
        with self._lock:
            self._read_error = None
            self._telemetry = tel
            if self._reference_suspect:  # first good read after a gap: keep only unmoved axes
                self._referenced_axes = reconcile_reference(
                    self._referenced_axes, self._reference_positions, tel.positions,
                    REFERENCE_MATCH_TOL_MM,
                )
                self._reference_suspect = False
            self._reference_positions = dict(tel.positions)
            if tel.heater_on and self._heater_on_since is None:
                self._heater_on_since = now
            if tel.heater_on is False:
                self._heater_on_since = None
                if not self._heater_cmd_on_since or now - self._heater_cmd_on_since > 1.0:
                    self._heater_cmd_on_since = None  # observed off after the command settled
            heater_on_s = self._heater_on_s(now)
            if tel.estop_triggered:
                self._referenced_axes.clear()  # e-stop cuts drive power -> re-home required
                self._homing_axes.clear()
            done = all(tel.motion_complete.values())
            if done:
                self._move_pending = False
            homing = now < self._homing_until
            # end the homing window early once motion has settled after the home was issued
            if homing and done and now - self._home_issued_at > 1.5:
                self._homing_until = 0.0
                homing = False
                # the home has settled: the axes it covered now read true position
                self._referenced_axes |= self._homing_axes
                self._homing_axes = set()
            decision: SafetyDecision = evaluate(
                tel, self.limits, age, heater_on_s, self._move_pending, home_in_progress=homing
            )
            self._warnings = decision.warnings
            faulted = self.state == ControllerState.FAULT
            needs_reenforce = faulted and (
                tel.heater_on is not False
                or self._heater_cmd_on_since is not None
                or not all(tel.motion_complete.values())
            )
        if decision.trip and not faulted:
            self._enter_fault(decision.reasons)
        elif needs_reenforce:
            self._safe_actions(dev, "fault re-enforcement")
        self._notify()

    def _heater_on_s(self, now: float) -> float:
        starts = [t for t in (self._heater_on_since, self._heater_cmd_on_since) if t is not None]
        return (now - min(starts)) if starts else 0.0

    def _safe_actions(self, dev: PrinterDevice, why: str) -> dict[str, str]:
        """stop_all + heater off, best effort, under the IO lock. Returns per-step outcome."""
        results: dict[str, str] = {}
        with self._io_lock:
            for name, step in (
                ("stop_all", dev.stop_all),
                ("heater_off", lambda: dev.heater_write(False)),
            ):
                try:
                    step()
                    results[name] = "ok"
                    if name == "heater_off":
                        with self._lock:
                            self._heater_cmd_on_since = None
                except Exception as exc:  # noqa: BLE001 - keep going: every step must be tried
                    results[name] = f"failed: {exc}"
                    log.warning("%s: %s failed: %s", why, name, exc)
            with self._lock:
                self._safe_actions_at = time.monotonic()
        return results

    def _enter_fault(self, reasons: tuple[str, ...]) -> None:
        log.error("FAULT: %s", "; ".join(reasons))
        with self._lock:
            self.state, self.armed = ControllerState.FAULT, False
            self._fault_reasons = reasons
            self._move_pending = False
            self._homing_until = 0.0
            dev = self._device
        if dev is not None:
            self._safe_actions(dev, "fault")

    def clear_fault(self) -> None:
        with self._lock:
            if self.state != ControllerState.FAULT:
                return
            tel = self._telemetry
            if tel is None:
                raise RuntimeError("cannot clear fault: no telemetry")
            if self._read_error is not None:
                raise RuntimeError(f"cannot clear fault: last read failed: {self._read_error}")
            if self._last_read_done <= self._safe_actions_at:
                raise RuntimeError("cannot clear fault: no sample yet since the fault actions")
            if tel.heater_on is not False or self._heater_cmd_on_since is not None:
                raise RuntimeError("cannot clear fault: heater is on or its state is unknown")
            age = time.monotonic() - self._last_read_done
            d = evaluate(tel, self.limits, age, 0.0, False)
            if d.trip:
                raise RuntimeError("cannot clear fault: " + "; ".join(d.reasons))
            self.state, self._fault_reasons, self.armed = ControllerState.CONNECTED, (), False

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
        with self._lock:
            dev = self._require_device()
            if self.state == ControllerState.FAULT:
                raise RuntimeError("faulted: " + "; ".join(self._fault_reasons))
            if not self.armed:
                raise RuntimeError("not armed — press ARM to take control of the printer")
            return dev

    def _fresh_sample(self) -> Telemetry:
        tel = self._telemetry
        if tel is None or self._read_error is not None:
            raise RuntimeError("no fresh telemetry from the controller yet")
        if time.monotonic() - self._last_read_done > self.limits.telemetry_timeout_s:
            raise RuntimeError("telemetry is stale")
        return tel

    def arm(self) -> None:
        with self._lock:
            self._require_device()
            if self.state != ControllerState.CONNECTED:
                raise RuntimeError(f"cannot arm in state {self.state.value}")
            tel = self._fresh_sample()
            d = evaluate(tel, self.limits, 0.0, self._heater_on_s(time.monotonic()), False)
            if d.trip:
                raise RuntimeError("cannot arm: " + "; ".join(d.reasons))
            self.armed = True

    def disarm(self) -> None:
        with self._lock:
            self.armed = False  # drop the gate FIRST; heater-off may fail (review H2)
        self.heater_off()

    def set_limits(self, limits: SafetyLimits) -> None:
        self.limits = limits

    # ---- guarded actions --------------------------------------------------------------------
    def _begin_homing(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._move_pending = True
            self._homing_until = now + HOMING_WINDOW_S
            self._home_issued_at = now

    def home_all(self) -> None:
        dev = self._require_armed()
        with self._lock:
            self._homing_axes = set(dev.axes)  # reference is granted when this home settles
        self._begin_homing()  # suspend position limits so the home can finish and re-zero
        dev.home_all()  # not under _io_lock: the reply may block until homed (see module doc)

    def home(self, axis: int) -> None:
        dev = self._require_armed()
        with self._lock:
            self._homing_axes = {axis}
        self._begin_homing()
        dev.home(axis)

    def set_max_speed(self, axis: int, mm_s: float) -> float:
        v = self.limits.clamp_speed(axis, mm_s)
        with self._io_lock:
            self._require_armed().set_max_speed(axis, v)
        return v

    def set_max_accel(self, axis: int, mm_s2: float) -> float:
        v = self.limits.clamp_accel(axis, mm_s2)
        with self._io_lock:
            self._require_armed().set_max_accel(axis, v)
        return v

    def move_absolute(self, axis: int, mm: float) -> float:
        v = self.limits.clamp_position(axis, mm)
        with self._io_lock:
            dev = self._require_armed()
            with self._lock:
                self._move_pending = True
            dev.move_absolute(axis, v)
        return v

    def move_relative(self, axis: int, mm: float) -> float:
        """Host-computed: an absolute move to (fresh position + mm), clamped. Requires a fresh
        sample and an idle axis, else the target would be computed from stale data (review H5)."""
        with self._io_lock:
            dev = self._require_armed()
            with self._lock:
                tel = self._fresh_sample()
                if not tel.motion_complete.get(axis, False):
                    raise RuntimeError(f"axis {axis} is moving; relative move refused")
                here = tel.positions[axis]
                target = self.limits.clamp_position(axis, here + mm)
                self._move_pending = True
            dev.move_absolute(axis, target)
        return target - here

    def heater_on(self) -> None:
        with self._io_lock:
            dev = self._require_armed()
            with self._lock:
                if self._heater_cmd_on_since is None:
                    self._heater_cmd_on_since = time.monotonic()
            dev.heater_write(True)

    def estop_release(self) -> None:
        """Explicit operator action: release the software e-stop, reset, wait for drives ready."""
        dev = self._require_device()
        with self._io_lock:
            dev.estop_release()
            dev.estop_reset()
            end = time.monotonic() + ESTOP_READY_WAIT_S
            while time.monotonic() < end:
                if dev.read_telemetry().drives_ready:
                    return
                time.sleep(0.2)
        raise RuntimeError(
            f"controller did not release the e-stop within {ESTOP_READY_WAIT_S:.0f}s — "
            "this firmware rejects a software release; twist out the physical E-STOP and press "
            "RESET on the MachineMotion, then Clear Fault"
        )

    def reset_drives(self) -> None:
        """Re-energize the drives via a software system reset (estop/systemreset), WITHOUT releasing
        the e-stop. Releasing an e-stop is physical-only (ISO 13850), but re-energizing the drives
        after the operator has already twisted out the physical E-STOP is a normal recovery step, so
        this lets them do it from software instead of walking over to the physical RESET button.
        Refuses while the e-stop is still engaged; may still be rejected by firmware that insists on
        the physical RESET, in which case the error says so."""
        dev = self._require_device()
        with self._io_lock:
            if dev.read_telemetry().estop_triggered:
                raise RuntimeError(
                    "E-STOP is still engaged — twist out the physical E-STOP first, "
                    "then reset the drives"
                )
            dev.estop_reset()
            end = time.monotonic() + ESTOP_READY_WAIT_S
            while time.monotonic() < end:
                if dev.read_telemetry().drives_ready:
                    return
                time.sleep(0.2)
        raise RuntimeError(
            f"drives did not re-energize within {ESTOP_READY_WAIT_S:.0f}s after the system reset — "
            "your firmware may require the physical RESET button on the MachineMotion; press it, "
            "then Clear Fault"
        )

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
            with self._lock:
                self._heater_cmd_on_since = None

    def estop(self) -> dict[str, Any]:
        """Bypasses every gate, safe in any state. Latches FAULT itself (review C3) and reports
        the outcome of every step instead of pretending success."""
        dev = self._device
        with self._lock:
            self.armed = False
        if dev is None:
            return {"ok": True, "steps": {}, "note": "no device attached"}
        self._enter_fault(("operator software E-STOP — all motion halted, heater off",))
        steps = self._safe_actions(dev, "e-stop")
        with self._io_lock:
            try:
                engaged = dev.estop_trigger("vpi operator")
                # Some firmware rejects a software e-stop over MQTT (returns false): motion is still
                # halted by stop_all above, but the controller's own safety e-stop does NOT engage.
                steps["estop_trigger"] = (
                    "ok"
                    if engaged
                    else "not engaged: controller rejected it (motion still halted)"
                )
            except Exception as exc:  # noqa: BLE001 - report, never raise from E-STOP
                steps["estop_trigger"] = f"failed: {exc}"
                log.error("e-stop trigger failed: %s", exc)
        return {"ok": all(v == "ok" for v in steps.values()), "steps": steps}

    # ---- reference persistence (survive a software reconnect while the MM keeps power) -------
    def restore_reference(
        self, saved_axes: set[int], saved_positions: dict[int, float], tol: float
    ) -> None:
        """Reconnect restore: keep reference for saved axes whose position is unchanged (the MM
        kept power); axes that moved (a power-cycle collapses to ~0) are dropped. No-op until the
        first telemetry read has landed."""
        with self._lock:
            tel = self._telemetry
            if tel is None:
                return
            self._referenced_axes = reconcile_reference(
                set(saved_axes), saved_positions, tel.positions, tol
            )
            self._reference_positions = dict(tel.positions)
            self._reference_suspect = False
        self._notify()

    def reference_state(self) -> tuple[set[int], dict[int, float]]:
        """Current (referenced axes, last positions) — for the app to persist to disk."""
        with self._lock:
            return set(self._referenced_axes), dict(self._reference_positions)

    # ---- snapshot ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tel = self._telemetry
            now = time.monotonic()
            heater_on_s = self._heater_on_s(now)
            return {
                "state": self.state.value,
                "backend": self.backend,
                "armed": self.armed,
                "homing": time.monotonic() < self._homing_until,
                "fault_reasons": list(self._fault_reasons),
                "warnings": list(self._warnings),
                "read_error": self._read_error,
                "device": dict(self._device_info),
                "limits": self.limits.to_dict(),
                "heater": {
                    "on": None if tel is None else tel.heater_on,
                    "commanded_on": self._heater_cmd_on_since is not None,
                    "on_s": round(heater_on_s, 1),
                    "max_on_s": self.limits.heater_max_on_s,
                },
                "telemetry": None
                if tel is None
                else {
                    "host_timestamp_ns": tel.host_timestamp_ns,
                    "positions": {str(k): v for k, v in tel.positions.items()},
                    "referenced": {str(k): (k in self._referenced_axes) for k in tel.positions},
                    "motion_complete": {str(k): v for k, v in tel.motion_complete.items()},
                    "estop_triggered": tel.estop_triggered,
                    "drives_ready": tel.drives_ready,
                    "health_ok": tel.health_ok,
                    "heater_on": tel.heater_on,
                },
            }
