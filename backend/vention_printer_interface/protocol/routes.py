"""MachineMotion 2 HTTP routes, MQTT topics and G-code strings (spec §2).

Transcribed from Vention's SDK, ``MachineMotion.py`` v4.7 (copy under ``plan/reference/``);
each constant cites the SDK line it comes from. Routes marked UNVERIFIED come from Vention's
public docs and have not been captured from our controller yet (see ``plan/notes.md``).
This module only builds strings and dicts. Nothing here opens a socket.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlencode

HTTP_PORT = 8000  # MachineMotion.py:432  (GCode.libPort = ":8000")
MQTT_PORT = 1883  # paho default; MachineMotion.py:818 connects with no port/auth

DEFAULT_IP_ETHERNET = "192.168.0.2"  # MachineMotion.py:84 + json/configuration.json
DEFAULT_IP_USB = "192.168.7.2"  # MachineMotion.py:82-83

AXIS_LETTERS: Mapping[int, str] = {1: "X", 2: "Y", 3: "Z", 4: "W"}  # MachineMotion.py:443
LETTER_AXES: Mapping[str, int] = {v: k for k, v in AXIS_LETTERS.items()}


def axis_letter(axis: int) -> str:
    """Map API axis 1..4 to controller letter (MachineMotion.py:439-455)."""
    try:
        return AXIS_LETTERS[axis]
    except KeyError as exc:
        raise ValueError(f"axis must be 1..4, got {axis!r}") from exc


def _check_axes(targets: Mapping[int, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for axis, value in targets.items():
        axis_letter(axis)
        out[str(axis)] = float(value)
    return out


# ---- HTTP ------------------------------------------------------------------------------------
HEALTH_PATH = "/health"  # MachineMotion.py:1398
POSITION_PATH = "/smartDrives/position"  # MachineMotion.py:536 -> {"X","Y","Z","W"} mm
ACTUAL_SPEED_PATH = "/smartDrives/get/actualSpeed"  # MachineMotion.py:1532
MOVE_ABSOLUTE_PATH = "/smartDrives/motion/moveAbsolute"  # MachineMotion.py:1623
MOVE_RELATIVE_PATH = "/smartDrives/motion/moveRelative"  # MachineMotion.py:1691


def gcode_path(gcode: str) -> str:
    """GET path for a raw G-code command (MachineMotion.py:477)."""
    return f"/gcode?{urlencode({'gcode': gcode})}"


def move_absolute(targets: Mapping[int, float]) -> tuple[str, dict[str, float]]:
    """POST json body keyed by numeric axis (MachineMotion.py:1620-1624)."""
    return MOVE_ABSOLUTE_PATH, _check_axes(targets)


def move_relative(targets: Mapping[int, float]) -> tuple[str, dict[str, float]]:
    """POST json body keyed by numeric axis (MachineMotion.py:1688-1692)."""
    return MOVE_RELATIVE_PATH, _check_axes(targets)


def max_speed_path(axis: int) -> str:
    """MachineMotion.py:1478 / 1504 (POST sets, GET reads)."""
    axis_letter(axis)
    return f"/smartDrives/maxSpeed/{axis}"


def max_speed_body(mm_per_s: float) -> dict[str, float]:
    return {"maxSpeed": float(mm_per_s)}  # MachineMotion.py:1479


def max_accel_path(axis: int) -> str:
    """MachineMotion.py:1565 / 1592."""
    axis_letter(axis)
    return f"/smartDrives/maxAcceleration/{axis}"


def max_accel_body(mm_per_s2: float) -> dict[str, float]:
    return {"maxAcceleration": float(mm_per_s2)}  # MachineMotion.py:1566


def complete_path(axis: int) -> str:
    """Per-axis motion-complete flag, keyed by LETTER (MachineMotion.py:1795)."""
    return f"/smartDrives/complete/{axis_letter(axis)}"


def drive_config_path(drive: int) -> str:
    """Actuator configuration for one drive; read-only use (MachineMotion.py:519)."""
    axis_letter(drive)
    return f"/smartDrives/configuration?{urlencode({'drive': drive})}"


# ---- G-code sent through /gcode --------------------------------------------------------------
GCODE_HOME_ALL = "G28"  # MachineMotion.py:1369
GCODE_STOP_ALL = "M410"  # MachineMotion.py:1339 (hard stop, not a safety-rated E-STOP)
GCODE_MOTION_STATUS = "V0"  # MachineMotion.py:1786 ("COMPLETED" in reply)
GCODE_ENDSTOPS = "M119"  # MachineMotion.py:1229
GCODE_DESIRED_POSITION = "M114"  # MachineMotion.py:1114 (deprecated; probe only)


def gcode_home(axis: int) -> str:
    return f"{GCODE_HOME_ALL} {axis_letter(axis)}"  # MachineMotion.py:1387


def gcode_stop(axes: Iterable[int]) -> str:
    letters = " ".join(axis_letter(a) for a in axes)  # MachineMotion.py:1359
    return f"{GCODE_STOP_ALL} {letters}" if letters else GCODE_STOP_ALL


# ---- MQTT ------------------------------------------------------------------------------------
TOPIC_ESTOP_STATUS = "estop/status"  # MachineMotion.py:199 (JSON bool)
TOPIC_ESTOP_TRIGGER_REQUEST = "estop/trigger/request"  # :200 (payload = free-text reason)
TOPIC_ESTOP_TRIGGER_RESPONSE = "estop/trigger/response"  # :201 (JSON bool)
TOPIC_ESTOP_RELEASE_REQUEST = "estop/release/request"  # :202
TOPIC_ESTOP_RELEASE_RESPONSE = "estop/release/response"  # :203
TOPIC_ESTOP_RESET_REQUEST = "estop/systemreset/request"  # :204
TOPIC_ESTOP_RESET_RESPONSE = "estop/systemreset/response"  # :205
TOPIC_DRIVES_READY = "smartDrives/areReady"  # :210 (JSON bool)
TOPIC_DEVICES_AVAILABLE = "devices/+/+/available"  # :2764
TOPIC_IO_INPUTS = "devices/+/+/digital-input/#"  # :2765
TOPIC_DRIVE_MOTION_COMPLETE = "drive/+/motionComplete"  # Vention docs, UNVERIFIED on our unit
TOPIC_DRIVE_ERROR = "drive/+/error"  # Vention docs, UNVERIFIED on our unit
MQTT_RESPONSE_TIMEOUT_S = 10.0  # MachineMotion.py:212

SUBSCRIPTIONS: tuple[str, ...] = (
    TOPIC_ESTOP_STATUS,
    TOPIC_DRIVES_READY,
    TOPIC_DEVICES_AVAILABLE,
    TOPIC_IO_INPUTS,
    TOPIC_DRIVE_MOTION_COMPLETE,
    TOPIC_DRIVE_ERROR,
)


def _check_io(device_id: int, pin: int) -> None:
    if not 1 <= device_id <= 8 or not 0 <= pin <= 3:  # MachineMotion.py:224-228
        raise ValueError(f"device_id 1..8 and pin 0..3 required, got {device_id},{pin}")


def io_output_topic(device_id: int, pin: int) -> str:
    """Digital output write topic; payload "1"/"0", retained (MachineMotion.py:2140-2147)."""
    _check_io(device_id, pin)
    return f"devices/io-expander/{device_id}/digital-output/{pin}"


def io_input_topic(device_id: int, pin: int) -> str:
    """Digital input status topic (MachineMotion.py:2765, 2846-2860)."""
    _check_io(device_id, pin)
    return f"devices/io-expander/{device_id}/digital-input/{pin}"


def io_available_topic(device_id: int) -> str:
    """IO module presence topic (MachineMotion.py:2764, 2830-2838)."""
    return f"devices/io-expander/{device_id}/available"
