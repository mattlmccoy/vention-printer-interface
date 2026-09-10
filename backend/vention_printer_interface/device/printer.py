"""PrinterDevice: high-level, one method per controller capability (spec §1).

Wraps a Transport; never decides policy (that is the Controller). There is deliberately no method
that writes drive configuration or motor current — those routes exist in the SDK but are out of
scope (spec Non-goals), so they cannot be called by accident.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import parsers as p
from vention_printer_interface.protocol import routes as r

# Extents (mm) measured on our printer (vention/python/V1.py constants); names from
# vention/json/configuration.json. Names/homing speed are overridden by
# /smartDrives/configuration when it answers (its shape is UNVERIFIED).
KNOWN_AXES: dict[int, tuple[str, float, float]] = {
    1: ("Part Piston", 145.0, 68.8),
    2: ("Feed Piston", 145.0, 68.8),
    3: ("Printhead Gantry", 970.0, 66.3),
    4: ("Recoater Gantry", 972.0, 66.3),
}


@dataclass(frozen=True)
class AxisConfig:
    number: int
    name: str
    travel_mm: float
    homing_speed: float


_HEALTH_TIMEOUT_S = 12.0  # matches machinemotion.HEALTH_TIMEOUT_S
HOMING_TIMEOUT_S = 330.0  # the SDK gives G28 DEFAULT_TIMEOUT*5 (MachineMotion.py:1369); UNVERIFIED
# whether the controller blocks the reply until homing completes.


@dataclass(frozen=True)
class Telemetry:
    """One poll. Tri-state fields are None when the status has NOT been observed — never assume
    healthy (review C1/C2)."""

    host_timestamp_ns: int
    positions: dict[int, float]
    motion_complete: dict[int, bool]
    estop_triggered: bool | None
    drives_ready: bool | None
    health_ok: bool
    heater_on: bool | None


class PrinterDevice:
    def __init__(self, transport: Transport, *, heater_io: tuple[int, int] | None = None) -> None:
        self._t = transport
        self.heater_io = heater_io
        self.axes: dict[int, AxisConfig] = {
            n: AxisConfig(n, name, travel, hs) for n, (name, travel, hs) in KNOWN_AXES.items()
        }
        self._health: p.HealthInfo | None = None

    @property
    def transport_name(self) -> str:
        return self._t.name

    # ---- identity ---------------------------------------------------------------------------
    def health(self) -> p.HealthInfo:
        # /health can block several seconds on a real controller (a failing io-expander-hub
        # subscribe), so it gets its own long timeout and is fetched sparingly (at connect).
        self._health = p.parse_health(self._t.http_get(r.HEALTH_PATH, timeout_s=_HEALTH_TIMEOUT_S))
        return self._health

    def identify(self) -> dict[str, Any]:
        h = self.health()
        for n in list(self.axes):
            try:
                cfg = p.parse_json(self._t.http_get(r.drive_config_path(n)))
            except (TransportError, p.ProtocolError):
                continue
            if isinstance(cfg, dict) and isinstance(cfg.get("friendlyName"), str):
                base = self.axes[n]
                homing = cfg.get("homingSpeed", base.homing_speed)
                homing = float(homing) if isinstance(homing, int | float) else base.homing_speed
                self.axes[n] = AxisConfig(n, cfg["friendlyName"], base.travel_mm, homing)
        return {
            "transport": self._t.name,
            "version": ".".join(map(str, h.version)),
            "async_supported": h.async_supported,
            "estop_triggered": h.estop_triggered,
            "motion_controller_reachable": h.motion_controller_reachable,
            "axes": {str(n): asdict(a) for n, a in self.axes.items()},
            "heater_io": list(self.heater_io) if self.heater_io else None,
        }

    # ---- telemetry --------------------------------------------------------------------------
    def read_telemetry(self, *, refresh_health: bool = False) -> Telemetry:
        if refresh_health or self._health is None:
            self.health()
        positions = p.parse_positions(self._t.http_get(r.POSITION_PATH))
        complete = {n: p.parse_complete(self._t.http_get(r.complete_path(n))) for n in self.axes}
        estop_raw = self._t.mqtt_latest(r.TOPIC_ESTOP_STATUS)
        ready_raw = self._t.mqtt_latest(r.TOPIC_DRIVES_READY)
        estop = p.parse_json_bool(estop_raw) if estop_raw is not None else None
        ready = p.parse_json_bool(ready_raw) if ready_raw is not None else None
        health = self._health
        health_ok = health is not None and health.motion_controller_reachable is not False
        if health is not None and health.estop_triggered:
            estop = True  # /health cross-check (MachineMotion.py:1418) dominates a stale MQTT value
        return Telemetry(
            host_timestamp_ns=time.time_ns(),
            positions=positions,
            motion_complete=complete,
            estop_triggered=estop,
            drives_ready=ready,
            health_ok=health_ok,
            heater_on=self.heater_read(),
        )

    def endstops(self) -> dict[str, str]:
        return p.parse_endstops(self._t.http_get(r.gcode_path(r.GCODE_ENDSTOPS)).decode())

    # ---- motion -----------------------------------------------------------------------------
    def _gcode(self, gcode: str, *, timeout_s: float | None = None) -> str:
        return p.parse_echo_ok(self._t.http_get(r.gcode_path(gcode), timeout_s=timeout_s).decode())

    def home_all(self) -> None:
        """G28. On any failure send M410 like the SDK does (MachineMotion.py:1370-1372)."""
        try:
            self._gcode(r.GCODE_HOME_ALL, timeout_s=HOMING_TIMEOUT_S)
        except Exception:
            self.stop_all()
            raise

    def home(self, axis: int) -> None:
        try:
            self._gcode(r.gcode_home(axis), timeout_s=HOMING_TIMEOUT_S)
        except Exception:
            self.stop_all()
            raise

    def stop_all(self) -> None:
        self._gcode(r.GCODE_STOP_ALL)

    def stop(self, axes: list[int]) -> None:
        self._gcode(r.gcode_stop(axes))

    def set_max_speed(self, axis: int, mm_s: float) -> None:
        self._t.http_post_json(r.max_speed_path(axis), r.max_speed_body(mm_s))

    def set_max_accel(self, axis: int, mm_s2: float) -> None:
        self._t.http_post_json(r.max_accel_path(axis), r.max_accel_body(mm_s2))

    def move_absolute(self, axis: int, mm: float) -> None:
        self._t.http_post_json(*r.move_absolute({axis: mm}))

    def move_relative(self, axis: int, mm: float) -> None:
        self._t.http_post_json(*r.move_relative({axis: mm}))

    def motion_completed(self) -> bool:
        reply = self._t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode()
        return p.parse_motion_status(reply)

    # ---- e-stop (MQTT round trips, MachineMotion.py:2350-2499) ------------------------------
    def _mqtt_bool(self, req: str, resp: str, payload: str) -> bool:
        return p.parse_json_bool(
            self._t.mqtt_request(req, resp, payload, r.MQTT_RESPONSE_TIMEOUT_S)
        )

    def estop_trigger(self, reason: str = "vpi") -> bool:
        return self._mqtt_bool(
            r.TOPIC_ESTOP_TRIGGER_REQUEST, r.TOPIC_ESTOP_TRIGGER_RESPONSE, reason
        )

    def estop_release(self) -> bool:
        return self._mqtt_bool(r.TOPIC_ESTOP_RELEASE_REQUEST, r.TOPIC_ESTOP_RELEASE_RESPONSE, "")

    def estop_reset(self) -> bool:
        return self._mqtt_bool(r.TOPIC_ESTOP_RESET_REQUEST, r.TOPIC_ESTOP_RESET_RESPONSE, "")

    # ---- heater relay on an IO module ------------------------------------------------------
    def heater_write(self, on: bool) -> None:
        if self.heater_io is None:
            raise TransportError("heater IO module/pin not configured")
        dev, pin = self.heater_io
        self._t.mqtt_publish(r.io_output_topic(dev, pin), "1" if on else "0", retain=True)

    def heater_read(self) -> bool | None:
        """Observed relay state from the broker's retained echo; None = never observed."""
        if self.heater_io is None:
            return None
        dev, pin = self.heater_io
        raw = self._t.mqtt_latest(r.io_output_topic(dev, pin))
        if raw is None:
            return None
        return raw.strip() in ("1", "true")

    def close(self) -> None:
        self._t.close()
