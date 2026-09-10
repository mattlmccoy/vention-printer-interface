"""In-process MachineMotion simulator (spec §2).

Answers the same HTTP routes and MQTT topics as the controller so the whole stack runs without
hardware. It is a *model* of the MachineMotion 2, not a capture of the physical unit: axis
kinematics are constant-velocity at maxSpeed (acceleration is stored, not integrated), homing
takes travel/homing_speed, and a system reset re-energises the drives after 3 s
(MachineMotion.py:2462). Move targets are NOT clamped (the real drive accepts any target); the
axis stops at the end sensor instead, so soft-limit protection can be exercised end to end.
Fault knobs: ``unreachable``, ``slow_completion_s`` (report complete=false for this long after
arrival, reproducing the V1.py sleep quirk), ``stall_axis``, ``estop_on_boot``,
``read_delay_s`` (every HTTP reply is delayed), ``health_reachable`` (/health reports the motion
controller unreachable), ``suppress_output_echo`` (broker never echoes digital-output writes —
what a mis-subscribed real transport would look like).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from vention_printer_interface.device import register_transport
from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import routes as r

# From vention/json/configuration.json + V1.py measured extents (mm) and homingSpeed (mm/s).
DEFAULT_AXES: dict[int, tuple[str, float, float]] = {
    1: ("Build Piston", 145.0, 68.8),
    2: ("Feed Piston", 145.0, 68.8),
    3: ("Printhead Gantry", 970.0, 66.3),
    4: ("Recoater Gantry", 972.0, 66.3),
}
RESET_READY_DELAY_S = 3.0
SIM_VERSION = "2.14.1"
_STEP_S = 0.01


@dataclass
class SimAxis:
    name: str
    travel_mm: float
    homing_speed: float
    position: float = 50.0  # unknown-until-homed; arbitrary non-zero
    target: float | None = None
    max_speed: float = 50.0
    max_accel: float = 100.0
    homed: bool = False
    arrived_at: float | None = None
    speed_override: float | None = None

    def step(self, dt: float, now: float) -> None:
        if self.target is None:
            return
        speed = self.speed_override or self.max_speed
        delta = self.target - self.position
        move = speed * dt
        if abs(delta) <= move:
            self.position = self.target
            self.target = None
            self.speed_override = None
            self.arrived_at = now
        else:
            self.position += move if delta > 0 else -move
        # End sensors: the carriage physically stops at the travel limits.
        if self.position <= 0.0 or self.position >= self.travel_mm:
            self.position = min(max(self.position, 0.0), self.travel_mm)
            if self.target is not None and not 0.0 <= self.target <= self.travel_mm:
                self.target, self.speed_override, self.arrived_at = None, None, now


@dataclass
class SimulatedMachine:
    axes: dict[int, SimAxis]
    estop: bool = False
    drives_ready: bool = True
    ready_at: float | None = None
    io_outputs: dict[str, str] = field(default_factory=dict)


class SimulatedTransport(Transport):
    name = "simulated"

    def __init__(
        self,
        *,
        realtime: bool = True,
        unreachable: bool = False,
        slow_completion_s: float = 0.0,
        stall_axis: int | None = None,
        estop_on_boot: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._realtime = realtime
        self._unreachable = unreachable
        self._slow_completion_s = slow_completion_s
        self._stall_axis = stall_axis
        self.read_delay_s = 0.0
        self.health_reachable = True
        self.suppress_output_echo = False
        self._clock = clock
        self._t = 0.0
        self._last_wall = clock()
        self._lock = threading.RLock()
        self.machine = SimulatedMachine(
            axes={n: SimAxis(name, travel, hs) for n, (name, travel, hs) in DEFAULT_AXES.items()}
        )
        self._topics: dict[str, str] = {
            r.TOPIC_ESTOP_STATUS: "false",
            r.TOPIC_DRIVES_READY: "true",
            r.io_available_topic(1): "true",
        }
        if estop_on_boot:
            self.machine.estop, self.machine.drives_ready = True, False
            self._topics[r.TOPIC_ESTOP_STATUS] = "true"
            self._topics[r.TOPIC_DRIVES_READY] = "false"

    # ---- time -------------------------------------------------------------------------------
    def advance(self, dt: float) -> None:
        """Step the model by dt seconds (tests). In realtime mode this is called implicitly."""
        with self._lock:
            steps = max(1, int(dt / _STEP_S))
            sub = dt / steps
            for _ in range(steps):
                self._t += sub
                for n, axis in self.machine.axes.items():
                    if n == self._stall_axis:
                        continue
                    axis.step(sub, self._t)
                m = self.machine
                if m.ready_at is not None and self._t >= m.ready_at:
                    m.drives_ready, m.ready_at = True, None
                    self._topics[r.TOPIC_DRIVES_READY] = "true"

    def _sync(self) -> None:
        if self._realtime:
            now = self._clock()
            dt, self._last_wall = now - self._last_wall, now
            if dt > 0:
                self.advance(dt)

    # ---- HTTP -------------------------------------------------------------------------------
    def http_get(self, path: str, *, timeout_s: float | None = None) -> bytes:
        self._check_reachable()
        if self.read_delay_s:
            time.sleep(self.read_delay_s)
        with self._lock:
            self._sync()
            url = urlparse(path)
            if url.path == r.HEALTH_PATH:
                return json.dumps(
                    {
                        "mqtt_services_running": {
                            "services/mm-vention-control/version": SIM_VERSION
                        },
                        "estop_triggered": self.machine.estop,
                        "motion_controller_reachable": self.health_reachable,
                        "time_now": self._t,
                    }
                ).encode()
            if url.path == r.POSITION_PATH:
                return json.dumps(
                    {r.AXIS_LETTERS[n]: round(a.position, 4) for n, a in self.machine.axes.items()}
                ).encode()
            if url.path == "/gcode":
                return self._gcode(parse_qs(url.query).get("gcode", [""])[0]).encode()
            m = re.fullmatch(r"/smartDrives/complete/([XYZW])", url.path)
            if m:
                return json.dumps({"complete": self._complete(r.LETTER_AXES[m.group(1)])}).encode()
            m = re.fullmatch(r"/smartDrives/maxSpeed/(\d)", url.path)
            if m:
                axis = self.machine.axes[int(m.group(1))]
                return json.dumps({"maxSpeed": axis.max_speed}).encode()
            m = re.fullmatch(r"/smartDrives/maxAcceleration/(\d)", url.path)
            if m:
                axis = self.machine.axes[int(m.group(1))]
                return json.dumps({"maxAcceleration": axis.max_accel}).encode()
            if url.path == "/smartDrives/configuration":
                axis = self.machine.axes[int(parse_qs(url.query)["drive"][0])]
                return json.dumps(
                    {"friendlyName": axis.name, "homingSpeed": axis.homing_speed, "simulated": True}
                ).encode()
            raise TransportError(f"request http://sim{path} failed with status 404")

    def http_post_json(self, path: str, body: dict[str, float]) -> bytes:
        self._check_reachable()
        with self._lock:
            self._sync()
            m = re.fullmatch(r"/smartDrives/maxSpeed/(\d)", path)
            if m:
                self.machine.axes[int(m.group(1))].max_speed = float(body["maxSpeed"])
                return b"{}"
            m = re.fullmatch(r"/smartDrives/maxAcceleration/(\d)", path)
            if m:
                self.machine.axes[int(m.group(1))].max_accel = float(body["maxAcceleration"])
                return b"{}"
            if path in (r.MOVE_ABSOLUTE_PATH, r.MOVE_RELATIVE_PATH):
                self._require_motion_allowed()
                for key, value in body.items():
                    axis = self.machine.axes[int(key)]
                    target = value if path == r.MOVE_ABSOLUTE_PATH else axis.position + value
                    axis.target = float(target)  # not clamped: the real drive accepts any target
                    axis.arrived_at = None
                return b"{}"
            raise TransportError(f"request http://sim{path} failed with status 404")

    def _axes_from(self, parts: list[str]) -> list[int]:
        return [r.LETTER_AXES[p] for p in parts] or list(self.machine.axes)

    def _gcode(self, gcode: str) -> str:
        parts = gcode.split()
        cmd = parts[0] if parts else ""
        if cmd == "G28":
            self._require_motion_allowed()
            for n in self._axes_from(parts[1:]):
                a = self.machine.axes[n]
                a.target, a.speed_override, a.homed, a.arrived_at = 0.0, a.homing_speed, True, None
            return f"echo:{gcode}\nok\n"
        if cmd == "M410":
            for n in self._axes_from(parts[1:]):
                a = self.machine.axes[n]
                a.target, a.speed_override, a.arrived_at = None, None, self._t
            return f"echo:{gcode}\nok\n"
        if cmd == "V0":
            busy = any(not self._complete(n) for n in self.machine.axes)
            state = "IN_PROGRESS" if busy else "COMPLETED"
            return f"echo:V0\nMotion Status = {state}\nok\n"
        if cmd == "M119":
            lines = []
            for n, a in self.machine.axes.items():
                letter = r.AXIS_LETTERS[n].lower()
                lines.append(f"{letter}_min: {'TRIGGERED' if a.position <= 0.0 else 'open'}")
                at_max = a.position >= a.travel_mm
                lines.append(f"{letter}_max: {'TRIGGERED' if at_max else 'open'}")
            return "echo:M119\n" + "\n".join(lines) + "\nok\n"
        if cmd == "M114":
            return "echo:M114\nX:0.00 Y:0.00 Z:0.00 E:0.00\nok\n"
        return f"echo:{gcode}\nError:Unknown command\n"

    def _complete(self, n: int) -> bool:
        a = self.machine.axes[n]
        if a.target is not None:
            return False
        if a.arrived_at is not None and self._t - a.arrived_at < self._slow_completion_s:
            return False
        return True

    def _require_motion_allowed(self) -> None:
        if self.machine.estop or not self.machine.drives_ready:
            raise TransportError("request failed with status 500: drives not ready (e-stop)")

    def _check_reachable(self) -> None:
        if self._unreachable:
            raise TransportError("Could not GET: connection refused (simulated unreachable)")

    # ---- MQTT -------------------------------------------------------------------------------
    def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        self._check_reachable()
        with self._lock:
            if topic.startswith("devices/io-expander/") and "/digital-output/" in topic:
                self.machine.io_outputs[topic] = payload
                if not self.suppress_output_echo:
                    self._topics[topic] = payload  # the broker echo of a retained publish
                return
            if topic == r.TOPIC_ESTOP_TRIGGER_REQUEST:
                self.machine.estop, self.machine.drives_ready = True, False
                for a in self.machine.axes.values():
                    a.target, a.speed_override = None, None
                self._topics[r.TOPIC_ESTOP_STATUS] = "true"
                self._topics[r.TOPIC_DRIVES_READY] = "false"
                self._topics[r.TOPIC_ESTOP_TRIGGER_RESPONSE] = "true"
                return
            if topic == r.TOPIC_ESTOP_RELEASE_REQUEST:
                self.machine.estop = False
                self._topics[r.TOPIC_ESTOP_STATUS] = "false"
                self._topics[r.TOPIC_ESTOP_RELEASE_RESPONSE] = "true"
                return
            if topic == r.TOPIC_ESTOP_RESET_REQUEST:
                self.machine.ready_at = self._t + RESET_READY_DELAY_S
                self._topics[r.TOPIC_ESTOP_RESET_RESPONSE] = "true"
                return
            self._topics[topic] = payload

    def mqtt_latest(self, topic: str) -> str | None:
        with self._lock:
            self._sync()
            return self._topics.get(topic)

    def mqtt_request(
        self, request_topic: str, response_topic: str, payload: str, timeout_s: float
    ) -> str:
        with self._lock:
            self._topics.pop(response_topic, None)
            self.mqtt_publish(request_topic, payload)
            reply = self._topics.get(response_topic)
        if reply is None:
            raise TransportError(f"no response on {response_topic} within {timeout_s}s")
        return reply

    def close(self) -> None:
        return None


register_transport("simulated")(SimulatedTransport)
