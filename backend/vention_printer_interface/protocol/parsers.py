"""Parsers for MachineMotion replies (spec §2). Pure; raise ProtocolError on anything unexpected.

Shapes are transcribed from how MachineMotion.py v4.7 reads each reply; they are not yet
confirmed against our controller (see plan/notes.md "Data-contract status").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from vention_printer_interface.protocol.routes import AXIS_LETTERS


class ProtocolError(RuntimeError):
    """The controller replied with something the SDK would have rejected."""


def _text(payload: bytes | str) -> str:
    return payload.decode("utf-8") if isinstance(payload, bytes) else payload


def parse_json(payload: bytes | str) -> Any:
    try:
        return json.loads(_text(payload))
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON payload: {_text(payload)[:80]!r}") from exc


def parse_echo_ok(reply: str) -> str:
    """G-code replies must contain both "echo" and "ok" (MachineMotion.py:486-495)."""
    if "echo" in reply and "ok" in reply:
        return reply
    raise ProtocolError(f"gcode not acknowledged: {reply[:120]!r}")


def parse_positions(payload: bytes | str) -> dict[int, float]:
    """/smartDrives/position -> {axis: mm} (MachineMotion.py:1183-1194)."""
    text = _text(payload)
    if "Error" in text:
        raise ProtocolError(f"position query failed: {text[:120]!r}")
    data = parse_json(text)
    try:
        return {axis: float(data[letter]) for axis, letter in AXIS_LETTERS.items()}
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"position payload missing axes: {data!r}") from exc


def parse_actual_speed(payload: bytes | str) -> dict[int, float]:
    """/smartDrives/get/actualSpeed -> {axis: mm/s} (MachineMotion.py:1531-1537).

    The payload is ``{"actual speed": {"1": v, "2": v, ...}}`` keyed by axis NUMBER (unlike
    /smartDrives/position, which is keyed by the X/Y/Z/W letters).
    """
    text = _text(payload)
    if "Error" in text:
        raise ProtocolError(f"actual-speed query failed: {text[:120]!r}")
    data = parse_json(text)
    speeds = data.get("actual speed") if isinstance(data, dict) else None
    if not isinstance(speeds, dict):
        raise ProtocolError(f"actual-speed payload malformed: {data!r}")
    try:
        return {int(axis): float(v) for axis, v in speeds.items()}
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"actual-speed payload not numeric: {speeds!r}") from exc


def parse_complete(payload: bytes | str) -> bool:
    """/smartDrives/complete/<letter> -> {"complete": bool} (MachineMotion.py:1798-1799)."""
    data = parse_json(payload)
    if not isinstance(data, dict) or not isinstance(data.get("complete"), bool):
        raise ProtocolError(f"complete payload malformed: {data!r}")
    return bool(data["complete"])


def parse_motion_status(reply: str) -> bool:
    """V0 reply: True when all motion has completed (MachineMotion.py:1786-1787)."""
    parse_echo_ok(reply)
    return "COMPLETED" in reply


def parse_json_bool(payload: bytes | str) -> bool:
    data = parse_json(payload)
    if not isinstance(data, bool):
        raise ProtocolError(f"expected JSON bool, got {data!r}")
    return data


@dataclass(frozen=True)
class HealthInfo:
    version: tuple[int, int, int]
    estop_triggered: bool | None
    motion_controller_reachable: bool | None
    raw: dict[str, Any]

    @property
    def async_supported(self) -> bool:
        """Independent-axis routes need mm-vention-control >= 2.4 (MachineMotion.py:1443-1455)."""
        major, minor, _ = self.version
        return major > 2 or (major >= 2 and minor >= 4)


def parse_health(payload: bytes | str) -> HealthInfo:
    """GET /health (MachineMotion.py:1393-1441)."""
    data = parse_json(payload)
    if not isinstance(data, dict):
        raise ProtocolError(f"health payload malformed: {data!r}")
    version = (0, 0, 0)
    services = data.get("mqtt_services_running") or {}
    text = None
    if isinstance(services, dict):
        text = services.get("services/mm-vention-control/version")
    if isinstance(text, str):
        m = re.search(r"(\d+)\.(\d+)\.?(\d*)", text)
        if m:
            version = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    estop = data.get("estop_triggered")
    reachable = data.get("motion_controller_reachable")
    return HealthInfo(
        version=version,
        estop_triggered=estop if isinstance(estop, bool) else None,
        motion_controller_reachable=reachable if isinstance(reachable, bool) else None,
        raw=data,
    )


_ENDSTOP_KEYS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max", "w_min", "w_max")


def parse_endstops(reply: str) -> dict[str, str]:
    """M119 reply -> {"x_min": "open"|"TRIGGERED", ...} (MachineMotion.py:1204-1260)."""
    parse_echo_ok(reply)
    states: dict[str, str] = {}
    for key in _ENDSTOP_KEYS:
        m = re.search(rf"{key}:\s*(\S+)", reply)
        if m:
            states[key] = m.group(1)
    if not states:
        raise ProtocolError(f"no endstop states in reply: {reply[:120]!r}")
    return states
