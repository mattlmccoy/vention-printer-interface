# Vention Printer Interface — Plan 1: backend core, probe, serve

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `uv`-managed Python package `vention_printer_interface` that talks to a MachineMotion 2 over HTTP + MQTT (or a byte-faithful simulator), with a supervisory controller (ARM gate, E-STOP, pure protection), heater watchdog, run recorder, FastAPI + `/ws/telemetry`, and three CLIs (`vpi-probe`, `vpi-serve`, `vpi-monitor`).

**Architecture:** `protocol/` builds requests and parses replies (pure). `device/` is a `Transport` ABC (HTTP + MQTT verbs) with a registry of `simulated` and `machinemotion`, wrapped by `PrinterDevice` (one method per capability). `control/` holds a pure `evaluate()` and a polling `Controller` with listeners; `api/` exposes it. Only `device/machinemotion.py` opens sockets.

**Tech Stack:** Python 3.11+, uv, hatchling, httpx, paho-mqtt 2.x, FastAPI, uvicorn, pytest, ruff, mypy strict. Mirrors `../TC-POWER/backend` conventions.

**Spec:** `docs/superpowers/specs/2026-09-08-vention-printer-interface-design.md`. Recipe engine is Plan 2; frontend is Plan 3.

---

## File structure

```
backend/
  pyproject.toml
  vention_printer_interface/
    __init__.py                 __version__
    protocol/__init__.py
    protocol/routes.py          HTTP paths, MQTT topics, G-code strings, axis map   (pure, cited)
    protocol/parsers.py         reply parsers + ProtocolError                        (pure)
    device/__init__.py          register_transport / create_transport
    device/base.py              Transport ABC, TransportError
    device/simulated.py         SimulatedTransport + SimulatedMachine model
    device/machinemotion.py     MachineMotionTransport (httpx + paho)
    device/printer.py           PrinterDevice, Telemetry, AxisConfig
    control/safety.py           HARD_BOUNDS, SafetyLimits, SafetyDecision, evaluate()
    control/controller.py       Controller
    control/heater.py           HeaterController (watchdog)
    control/limits_store.py     load_limits / save_limits
    recording/recorder.py       Recorder
    api/app.py                  create_app, cross-origin policy, routes, /ws/telemetry
    api/server.py               vpi-serve
    probe.py                    vpi-probe (read-only)
    monitor.py                  vpi-monitor
  tests/
    conftest.py, test_routes.py, test_parsers.py, test_registry.py, test_simulated.py,
    test_printer.py, test_safety.py, test_controller.py, test_heater.py,
    test_limits_store.py, test_recorder.py, test_api.py, test_cors.py, test_probe.py
```

Conventions (from siblings): every module docstring names its purpose and spec section; `# MachineMotion.py:<line>` citations on every protocol constant; `# noqa: BLE001 - <reason>` on broad excepts; no print in library code (logging). Line length 100.

---

### Task 1: Scaffold the backend package

**Files:**
- Create: `backend/pyproject.toml`, `backend/vention_printer_interface/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_version.py`, `.gitignore`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_version.py`:
```python
from vention_printer_interface import __version__


def test_version_is_semver() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
```

- [ ] **Step 2: Create pyproject and package**

`backend/pyproject.toml`:
```toml
[project]
name = "vention-printer-interface"
version = "0.1.0"
description = "Operator backend + UI for the Vention MachineMotion 2 binder-jet printer (family of the FLIR Research Interface and T&C Power Interface)"
readme = "../README.md"
requires-python = ">=3.11,<3.14"
license = { text = "MIT" }
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "websockets>=12",
  "httpx>=0.27",
  "paho-mqtt>=2.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
# vpi- = Vention Printer Interface. Mirrors FLIR's fri- and T&C's tcp- entry points.
vpi-serve = "vention_printer_interface.api.server:main"
vpi-probe = "vention_printer_interface.probe:main"
vpi-monitor = "vention_printer_interface.monitor:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["vention_printer_interface"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
asyncio_mode = "auto"
markers = ["hardware: requires a reachable MachineMotion controller (deselected by default)"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "W"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

`backend/vention_printer_interface/__init__.py`:
```python
"""Vention Printer Interface.

Simulator-first, safety-first operator for the MachineMotion 2 binder-jet printer. A connected
controller is read-only until ARMed; the heater output turns on only by explicit operator action
and is forced off on any fault, disconnect, E-STOP, or watchdog expiry. Only
``device/machinemotion.py`` opens sockets to the controller.
"""

__version__ = "0.1.0"
```

`backend/tests/conftest.py`:
```python
"""Test configuration: hardware tests are skipped unless --hardware is passed."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--hardware", action="store_true", default=False,
                     help="run tests that need a reachable MachineMotion controller")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs --hardware and a reachable controller")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
```

`.gitignore` (repo root):
```
# secrets
.env
.env.*
!.env.example
# python
__pycache__/
*.pyc
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
# uv.lock IS committed (reproducible operator installs)
# experiment run data — keep out of git by default
backend/experiments/
backend/operator.log
# probe captures may contain controller serials; commit only reviewed copies under plan/
probe_output*/
# frontend
frontend/node_modules/
frontend/dist/
frontend/dist-site/
# reference downloads (not our code)
plan/reference/
# not for a public repo
.claude/
.DS_Store
```

- [ ] **Step 3: Install and run**

Run: `cd backend && uv sync --extra dev && uv run pytest -v`
Expected: `test_version_is_semver PASSED`

- [ ] **Step 4: Commit**
```bash
git add -A && git commit -m "chore: scaffold backend package with uv, pytest, ruff, mypy"
```

---

### Task 2: Protocol routes (pure)

**Files:**
- Create: `backend/vention_printer_interface/protocol/__init__.py` (empty docstring), `backend/vention_printer_interface/protocol/routes.py`
- Test: `backend/tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Routes are transcribed from the Vention SDK (MachineMotion.py v4.7); assertions cite lines."""

import pytest

from vention_printer_interface.protocol import routes as r


def test_axis_letters_map_1_to_4() -> None:
    assert [r.axis_letter(i) for i in (1, 2, 3, 4)] == ["X", "Y", "Z", "W"]  # :439-455


@pytest.mark.parametrize("bad", [0, 5, -1])
def test_axis_letter_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError):
        r.axis_letter(bad)


def test_gcode_path_urlencodes() -> None:
    assert r.gcode_path("G28 X") == "/gcode?gcode=G28+X"  # :477


def test_move_absolute_uses_numeric_axis_keys() -> None:
    path, body = r.move_absolute({1: 145.0, 4: 5})
    assert path == "/smartDrives/motion/moveAbsolute"  # :1623
    assert body == {"1": 145.0, "4": 5.0}


def test_move_relative_path() -> None:
    path, body = r.move_relative({2: -2.0})
    assert path == "/smartDrives/motion/moveRelative"  # :1691
    assert body == {"2": -2.0}


def test_speed_and_accel_routes() -> None:
    assert r.max_speed_path(3) == "/smartDrives/maxSpeed/3"  # :1478
    assert r.max_speed_body(100) == {"maxSpeed": 100.0}
    assert r.max_accel_path(3) == "/smartDrives/maxAcceleration/3"  # :1565
    assert r.max_accel_body(500) == {"maxAcceleration": 500.0}


def test_complete_path_uses_letter() -> None:
    assert r.complete_path(4) == "/smartDrives/complete/W"  # :1795


def test_static_paths() -> None:
    assert r.HEALTH_PATH == "/health"  # :1398
    assert r.POSITION_PATH == "/smartDrives/position"  # :536
    assert r.drive_config_path(2) == "/smartDrives/configuration?drive=2"  # :519


def test_gcode_strings() -> None:
    assert r.GCODE_HOME_ALL == "G28"  # :1369
    assert r.gcode_home(3) == "G28 Z"  # :1387
    assert r.GCODE_STOP_ALL == "M410"  # :1339
    assert r.gcode_stop([1, 3]) == "M410 X Z"  # :1359
    assert r.GCODE_MOTION_STATUS == "V0"  # :1786
    assert r.GCODE_ENDSTOPS == "M119"  # :1229


def test_mqtt_topics() -> None:
    assert r.TOPIC_ESTOP_STATUS == "estop/status"  # :199
    assert r.TOPIC_ESTOP_TRIGGER_REQUEST == "estop/trigger/request"
    assert r.TOPIC_ESTOP_TRIGGER_RESPONSE == "estop/trigger/response"
    assert r.TOPIC_ESTOP_RELEASE_REQUEST == "estop/release/request"
    assert r.TOPIC_ESTOP_RELEASE_RESPONSE == "estop/release/response"
    assert r.TOPIC_ESTOP_RESET_REQUEST == "estop/systemreset/request"
    assert r.TOPIC_ESTOP_RESET_RESPONSE == "estop/systemreset/response"
    assert r.TOPIC_DRIVES_READY == "smartDrives/areReady"  # :210
    assert r.io_output_topic(1, 2) == "devices/io-expander/1/digital-output/2"  # :2140
    assert r.io_input_topic(1, 0) == "devices/io-expander/1/digital-input/0"
    assert "devices/+/+/available" in r.SUBSCRIPTIONS  # :2764
    assert "drive/+/motionComplete" in r.SUBSCRIPTIONS  # vendor docs, UNVERIFIED
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_routes.py -q`
Expected: ImportError / ModuleNotFoundError for `vention_printer_interface.protocol.routes`.

- [ ] **Step 3: Implement**

`protocol/__init__.py`:
```python
"""Pure protocol layer: builds MachineMotion requests and parses replies. No IO here."""
```

`protocol/routes.py`:
```python
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
    return "/gcode?%s" % urlencode({"gcode": gcode})


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
    return "/smartDrives/configuration?%s" % urlencode({"drive": drive})


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


def io_output_topic(device_id: int, pin: int) -> str:
    """Digital output write topic; payload "1"/"0", retained (MachineMotion.py:2140-2147)."""
    if not 1 <= device_id <= 8 or not 0 <= pin <= 3:  # MachineMotion.py:224-228
        raise ValueError(f"device_id 1..8 and pin 0..3 required, got {device_id},{pin}")
    return f"devices/io-expander/{device_id}/digital-output/{pin}"


def io_input_topic(device_id: int, pin: int) -> str:
    """Digital input status topic (MachineMotion.py:2765, 2846-2860)."""
    if not 1 <= device_id <= 8 or not 0 <= pin <= 3:
        raise ValueError(f"device_id 1..8 and pin 0..3 required, got {device_id},{pin}")
    return f"devices/io-expander/{device_id}/digital-input/{pin}"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_routes.py -q` → all pass. Then `uv run ruff check . && uv run mypy vention_printer_interface` → clean.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "feat(protocol): MachineMotion routes, topics and G-code strings with SDK citations"
```

---

### Task 3: Protocol parsers (pure)

**Files:**
- Create: `backend/vention_printer_interface/protocol/parsers.py`
- Test: `backend/tests/test_parsers.py`

- [ ] **Step 1: Failing tests**

```python
"""Fixtures here are SDK-DERIVED (shapes read from MachineMotion.py), not captured from our unit.
Replace with plan/probe_report.json samples once vpi-probe has run (data-contract rule)."""

import json

import pytest

from vention_printer_interface.protocol import parsers as p


def test_parse_echo_ok_accepts_marlin_style_reply() -> None:
    assert p.parse_echo_ok("echo:G28\nok\n") == "echo:G28\nok\n"  # MachineMotion.py:487


def test_parse_echo_ok_rejects_error() -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_echo_ok("Error: unknown command")


def test_parse_positions_reads_xyzw() -> None:
    raw = json.dumps({"X": 1.5, "Y": 2.0, "Z": 3.25, "W": 4.0}).encode()
    assert p.parse_positions(raw) == {1: 1.5, 2: 2.0, 3: 3.25, 4: 4.0}  # :1180-1185


def test_parse_positions_rejects_error_string() -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_positions(b"Error in gCode execution")  # :1174


def test_parse_complete() -> None:
    assert p.parse_complete(b'{"complete": true}') is True  # :1798-1799
    assert p.parse_complete(b'{"complete": false}') is False


def test_parse_motion_status() -> None:
    assert p.parse_motion_status("echo:V0\nMotion Status = COMPLETED\nok") is True  # :1787
    assert p.parse_motion_status("echo:V0\nMotion Status = IN_PROGRESS\nok") is False


def test_parse_health_version() -> None:
    raw = json.dumps({
        "mqtt_services_running": {"services/mm-vention-control/version": "2.14.1"},
        "estop_triggered": False,
        "motion_controller_reachable": True,
    }).encode()
    h = p.parse_health(raw)
    assert h.version == (2, 14, 1)  # :1420-1441
    assert h.estop_triggered is False
    assert h.motion_controller_reachable is True
    assert h.async_supported is True  # :1443-1455 (>= 2.4)


def test_parse_health_without_version_is_zero() -> None:
    h = p.parse_health(b"{}")
    assert h.version == (0, 0, 0)
    assert h.async_supported is False


def test_parse_json_bool() -> None:
    assert p.parse_json_bool(b"true") is True
    assert p.parse_json_bool("false") is False
    with pytest.raises(p.ProtocolError):
        p.parse_json_bool(b"maybe")


def test_parse_endstops() -> None:
    reply = "echo:M119\nx_min: open\nx_max: TRIGGERED\ny_min: open\ny_max: open\nz_min: open\nz_max: open\nw_min: open\nw_max: open\nok\n"
    states = p.parse_endstops(reply)  # :1229-1260
    assert states["x_max"] == "TRIGGERED"
    assert states["w_min"] == "open"
```

- [ ] **Step 2: Run** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `protocol/parsers.py`:
```python
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


def _json(payload: bytes | str) -> Any:
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
    """/smartDrives/position -> {axis: mm} (MachineMotion.py:1171-1185)."""
    text = _text(payload)
    if "Error" in text:
        raise ProtocolError(f"position query failed: {text[:120]!r}")
    data = _json(text)
    try:
        return {axis: float(data[letter]) for axis, letter in AXIS_LETTERS.items()}
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"position payload missing axes: {data!r}") from exc


def parse_complete(payload: bytes | str) -> bool:
    """/smartDrives/complete/<letter> -> {"complete": bool} (MachineMotion.py:1798-1799)."""
    data = _json(payload)
    if not isinstance(data, dict) or not isinstance(data.get("complete"), bool):
        raise ProtocolError(f"complete payload malformed: {data!r}")
    return data["complete"]


def parse_motion_status(reply: str) -> bool:
    """V0 reply: True when all motion has completed (MachineMotion.py:1786-1787)."""
    parse_echo_ok(reply)
    return "COMPLETED" in reply


def parse_json_bool(payload: bytes | str) -> bool:
    data = _json(payload)
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
    data = _json(payload)
    if not isinstance(data, dict):
        raise ProtocolError(f"health payload malformed: {data!r}")
    version = (0, 0, 0)
    services = data.get("mqtt_services_running") or {}
    text = services.get("services/mm-vention-control/version") if isinstance(services, dict) else None
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
```

- [ ] **Step 4: Run** `uv run pytest tests/test_parsers.py -q` → pass; ruff + mypy clean.
- [ ] **Step 5: Commit** `git commit -am "feat(protocol): reply parsers with SDK-derived fixtures"`

---

### Task 4: Transport ABC and registry

**Files:**
- Create: `device/base.py`, `device/__init__.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Failing test**
```python
import pytest

from vention_printer_interface.device import create_transport, register_transport
from vention_printer_interface.device.base import Transport


def test_unknown_transport_lists_known_names() -> None:
    with pytest.raises(KeyError) as exc:
        create_transport("nope")
    assert "simulated" in str(exc.value)


def test_register_and_create_custom() -> None:
    class Fake(Transport):
        name = "fake"

        def http_get(self, path: str) -> bytes:
            return b""

        def http_post_json(self, path: str, body: dict[str, float]) -> bytes:
            return b""

        def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
            pass

        def mqtt_latest(self, topic: str) -> str | None:
            return None

        def mqtt_request(self, request_topic: str, response_topic: str, payload: str,
                         timeout_s: float) -> str:
            return "true"

        def close(self) -> None:
            pass

    register_transport("fake-test")(Fake)
    assert isinstance(create_transport("fake-test"), Fake)
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement**

`device/base.py`:
```python
"""Transport abstraction (spec §1-2): the MachineMotion's two pipes, HTTP and MQTT.

The same PrinterDevice/Controller logic runs over the in-process simulator and the real
controller. `mqtt_latest` returns the cached last payload of a subscribed topic (the SDK keeps
the same caches: MachineMotion.py:2802-2899). `mqtt_request` publishes and waits for the next
message on a response topic (the SDK's threaded MQTTsubscribe.simple pattern, :2350-2389).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TransportError(RuntimeError):
    """The controller could not be reached or replied with a non-200 status."""


class Transport(ABC):
    name: str = "transport"

    @abstractmethod
    def http_get(self, path: str) -> bytes: ...

    @abstractmethod
    def http_post_json(self, path: str, body: dict[str, float]) -> bytes: ...

    @abstractmethod
    def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None: ...

    @abstractmethod
    def mqtt_latest(self, topic: str) -> str | None: ...

    @abstractmethod
    def mqtt_request(self, request_topic: str, response_topic: str, payload: str,
                     timeout_s: float) -> str: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

`device/__init__.py`:
```python
"""Transport registry — mirrors the FLIR camera registry and the T&C transport registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vention_printer_interface.device.base import Transport, TransportError

_REGISTRY: dict[str, Callable[..., Transport]] = {}


def register_transport(name: str) -> Callable[[Callable[..., Transport]], Callable[..., Transport]]:
    def deco(factory: Callable[..., Transport]) -> Callable[..., Transport]:
        _REGISTRY[name] = factory
        return factory

    return deco


def create_transport(name: str, **kwargs: Any) -> Transport:
    try:
        factory = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown transport {name!r}; known: {sorted(_REGISTRY)}") from exc
    return factory(**kwargs)


def registered_transports() -> list[str]:
    return sorted(_REGISTRY)


__all__ = ["Transport", "TransportError", "create_transport", "register_transport",
           "registered_transports"]

# Self-register built-ins (import for side effect; after the registry exists).
from vention_printer_interface.device import machinemotion as _machinemotion  # noqa: E402,F401
from vention_printer_interface.device import simulated as _simulated  # noqa: E402,F401
```
(The two imports fail until Tasks 5 and 6 exist. Create `device/simulated.py` and `device/machinemotion.py` as empty docstring files in this task so the package imports; they are filled in next.)

- [ ] **Step 4: Run** `uv run pytest tests/test_registry.py -q` → the "unknown" test passes once the empty modules exist; the custom-register test passes.
- [ ] **Step 5: Commit** `git commit -am "feat(device): Transport ABC and registry"`

---

### Task 5: Simulated transport with a machine model

**Files:**
- Create: `device/simulated.py`
- Test: `tests/test_simulated.py`

Model (YAGNI): each axis moves toward its target at `max_speed` (constant velocity; acceleration is recorded but not integrated — documented). Time comes from an injectable monotonic clock; tests call `advance(dt)`.

- [ ] **Step 1: Failing tests**
```python
import json

import pytest

from vention_printer_interface.device import create_transport
from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.simulated import SimulatedTransport
from vention_printer_interface.protocol import routes as r


def make() -> SimulatedTransport:
    return SimulatedTransport(realtime=False)


def test_registered_under_simulated() -> None:
    assert isinstance(create_transport("simulated", realtime=False), SimulatedTransport)


def test_health_reports_version_and_estop() -> None:
    t = make()
    h = json.loads(t.http_get(r.HEALTH_PATH))
    assert h["mqtt_services_running"]["services/mm-vention-control/version"] == "2.14.1"
    assert h["estop_triggered"] is False


def test_positions_start_unknown_until_homed_then_zero() -> None:
    t = make()
    pos = json.loads(t.http_get(r.POSITION_PATH))
    assert set(pos) == {"X", "Y", "Z", "W"}
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL))
    t.advance(60)
    assert json.loads(t.http_get(r.POSITION_PATH)) == {"X": 0, "Y": 0, "Z": 0, "W": 0}


def test_move_absolute_integrates_at_max_speed() -> None:
    t = make()
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL)); t.advance(60)
    t.http_post_json(r.max_speed_path(3), r.max_speed_body(100))
    path, body = r.move_absolute({3: 200})
    t.http_post_json(path, body)
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is False
    t.advance(1.0)
    assert json.loads(t.http_get(r.POSITION_PATH))["Z"] == pytest.approx(100)
    t.advance(1.5)
    assert json.loads(t.http_get(r.POSITION_PATH))["Z"] == pytest.approx(200)
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is True
    assert "COMPLETED" in t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode()


def test_move_relative_and_clamp_to_travel() -> None:
    t = make()
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL)); t.advance(60)
    t.http_post_json(r.max_speed_path(2), r.max_speed_body(1000))
    path, body = r.move_relative({2: 500})  # feed travel is 145 mm
    t.http_post_json(path, body)
    t.advance(5)
    assert json.loads(t.http_get(r.POSITION_PATH))["Y"] == pytest.approx(145)


def test_stop_all_halts_motion() -> None:
    t = make()
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL)); t.advance(60)
    t.http_post_json(r.max_speed_path(4), r.max_speed_body(100))
    t.http_post_json(*r.move_absolute({4: 500}))
    t.advance(1)
    t.http_get(r.gcode_path(r.GCODE_STOP_ALL))
    t.advance(5)
    assert json.loads(t.http_get(r.POSITION_PATH))["W"] == pytest.approx(100)


def test_estop_round_trip_over_mqtt() -> None:
    t = make()
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "false"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "true"
    assert t.mqtt_request(r.TOPIC_ESTOP_TRIGGER_REQUEST, r.TOPIC_ESTOP_TRIGGER_RESPONSE, "test", 1) == "true"
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "false"
    with pytest.raises(TransportError):
        t.http_post_json(*r.move_absolute({1: 10}))  # refused while e-stopped
    assert t.mqtt_request(r.TOPIC_ESTOP_RELEASE_REQUEST, r.TOPIC_ESTOP_RELEASE_RESPONSE, "", 1) == "true"
    assert t.mqtt_request(r.TOPIC_ESTOP_RESET_REQUEST, r.TOPIC_ESTOP_RESET_RESPONSE, "", 1) == "true"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "false"
    t.advance(3.1)
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "true"


def test_io_output_is_retained_and_readable() -> None:
    t = make()
    t.mqtt_publish(r.io_output_topic(1, 2), "1", retain=True)
    assert t.mqtt_latest(r.io_output_topic(1, 2)) == "1"
    assert t.mqtt_latest("devices/io-expander/1/available") == "true"


def test_unreachable_knob() -> None:
    t = SimulatedTransport(realtime=False, unreachable=True)
    with pytest.raises(TransportError):
        t.http_get(r.HEALTH_PATH)


def test_endstops_reflect_home() -> None:
    t = make()
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL)); t.advance(60)
    reply = t.http_get(r.gcode_path(r.GCODE_ENDSTOPS)).decode()
    assert "x_min: TRIGGERED" in reply
```

- [ ] **Step 2: Run** → failures (empty module).

- [ ] **Step 3: Implement** `device/simulated.py`:
```python
"""In-process MachineMotion simulator (spec §2).

Answers the same HTTP routes and MQTT topics as the controller so the whole stack runs without
hardware. It is a *model* of the MachineMotion 2, not a capture of the physical unit: axis
kinematics are constant-velocity at maxSpeed (acceleration is stored, not integrated), homing
takes travel/homing_speed, and a system reset re-energises the drives after 3 s
(MachineMotion.py:2470). Fault knobs: ``unreachable``, ``slow_completion_s`` (report
complete=false for this long after arrival, reproducing the V1.py sleep quirk), ``stall_axis``.
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
    1: ("Part Piston", 145.0, 68.8),
    2: ("Feed Piston", 145.0, 68.8),
    3: ("Printhead Gantry", 840.0, 66.3),
    4: ("Recoater Gantry", 930.0, 66.3),
}
RESET_READY_DELAY_S = 3.0
SIM_VERSION = "2.14.1"


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


@dataclass
class SimulatedMachine:
    axes: dict[int, SimAxis]
    estop: bool = False
    drives_ready: bool = True
    ready_at: float | None = None
    io_outputs: dict[str, str] = field(default_factory=dict)

    def moving(self) -> bool:
        return any(a.target is not None for a in self.axes.values())


class SimulatedTransport(Transport):
    name = "simulated"

    def __init__(self, *, realtime: bool = True, unreachable: bool = False,
                 slow_completion_s: float = 0.0, stall_axis: int | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._realtime = realtime
        self._unreachable = unreachable
        self._slow_completion_s = slow_completion_s
        self._stall_axis = stall_axis
        self._clock = clock
        self._t = 0.0
        self._last_wall = clock()
        self._lock = threading.RLock()
        self.machine = SimulatedMachine(
            axes={n: SimAxis(name, travel, hs) for n, (name, travel, hs) in DEFAULT_AXES.items()})
        self._topics: dict[str, str] = {
            r.TOPIC_ESTOP_STATUS: "false",
            r.TOPIC_DRIVES_READY: "true",
            "devices/io-expander/1/available": "true",
        }

    # ---- time -------------------------------------------------------------------------------
    def advance(self, dt: float) -> None:
        """Step the model by dt seconds (tests). In realtime mode this is called implicitly."""
        with self._lock:
            steps = max(1, int(dt / 0.01))
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
    def http_get(self, path: str) -> bytes:
        self._check_reachable()
        with self._lock:
            self._sync()
            url = urlparse(path)
            if url.path == r.HEALTH_PATH:
                return json.dumps({
                    "mqtt_services_running": {"services/mm-vention-control/version": SIM_VERSION},
                    "estop_triggered": self.machine.estop,
                    "motion_controller_reachable": True,
                    "time_now": self._t,
                }).encode()
            if url.path == r.POSITION_PATH:
                return json.dumps({r.AXIS_LETTERS[n]: round(a.position, 4)
                                   for n, a in self.machine.axes.items()}).encode()
            if url.path == "/gcode":
                return self._gcode(parse_qs(url.query).get("gcode", [""])[0]).encode()
            m = re.fullmatch(r"/smartDrives/complete/([XYZW])", url.path)
            if m:
                n = {v: k for k, v in r.AXIS_LETTERS.items()}[m.group(1)]
                return json.dumps({"complete": self._complete(n)}).encode()
            m = re.fullmatch(r"/smartDrives/maxSpeed/(\d)", url.path)
            if m:
                return json.dumps({"maxSpeed": self.machine.axes[int(m.group(1))].max_speed}).encode()
            m = re.fullmatch(r"/smartDrives/maxAcceleration/(\d)", url.path)
            if m:
                return json.dumps({"maxAcceleration": self.machine.axes[int(m.group(1))].max_accel}).encode()
            if url.path == "/smartDrives/configuration":
                n = int(parse_qs(url.query)["drive"][0])
                a = self.machine.axes[n]
                return json.dumps({"friendlyName": a.name, "homingSpeed": a.homing_speed,
                                   "simulated": True}).encode()
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
                    axis.target = min(max(0.0, float(target)), axis.travel_mm)
                    axis.arrived_at = None
                return b"{}"
            raise TransportError(f"request http://sim{path} failed with status 404")

    def _gcode(self, gcode: str) -> str:
        parts = gcode.split()
        cmd = parts[0] if parts else ""
        if cmd == "G28":
            self._require_motion_allowed()
            axes = [{v: k for k, v in r.AXIS_LETTERS.items()}[p] for p in parts[1:]] or list(self.machine.axes)
            for n in axes:
                a = self.machine.axes[n]
                a.target, a.speed_override, a.homed, a.arrived_at = 0.0, a.homing_speed, True, None
            return f"echo:{gcode}\nok\n"
        if cmd == "M410":
            axes = [{v: k for k, v in r.AXIS_LETTERS.items()}[p] for p in parts[1:]] or list(self.machine.axes)
            for n in axes:
                a = self.machine.axes[n]
                a.target, a.speed_override, a.arrived_at = None, None, self._t
            return f"echo:{gcode}\nok\n"
        if cmd == "V0":
            state = "IN_PROGRESS" if any(not self._complete(n) for n in self.machine.axes) else "COMPLETED"
            return f"echo:V0\nMotion Status = {state}\nok\n"
        if cmd == "M119":
            lines = []
            for n, a in self.machine.axes.items():
                letter = r.AXIS_LETTERS[n].lower()
                lines.append(f"{letter}_min: {'TRIGGERED' if a.position <= 0.0 else 'open'}")
                lines.append(f"{letter}_max: {'TRIGGERED' if a.position >= a.travel_mm else 'open'}")
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
                self._topics[topic] = payload
                self.machine.io_outputs[topic] = payload
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

    def mqtt_request(self, request_topic: str, response_topic: str, payload: str,
                     timeout_s: float) -> str:
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
```
(Remove the bottom-of-file import of `simulated` from `device/__init__.py` only if it causes a circular import at runtime; the pattern above — module imports registry, registry imports module last — matches TC-POWER and works.)

- [ ] **Step 4: Run** `uv run pytest tests/test_simulated.py -q` → all pass; ruff + mypy clean.
- [ ] **Step 5: Commit** `git commit -am "feat(device): simulated MachineMotion transport with kinematic model and fault knobs"`

---

### Task 6: Real MachineMotion transport (httpx + paho)

**Files:**
- Create: `device/machinemotion.py`
- Test: `tests/test_machinemotion.py` (unit: HTTP path via `httpx.MockTransport`; MQTT cache via a fake client) and a `@pytest.mark.hardware` smoke test.

- [ ] **Step 1: Failing tests**
```python
import json

import httpx
import pytest

from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.machinemotion import MachineMotionTransport
from vention_printer_interface.protocol import routes as r


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == r.HEALTH_PATH:
        return httpx.Response(200, json={"estop_triggered": False})
    if request.url.path == r.MOVE_ABSOLUTE_PATH:
        assert json.loads(request.content) == {"1": 10.0}
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, text="{}")
    return httpx.Response(500, text="boom")


def make() -> MachineMotionTransport:
    return MachineMotionTransport("192.0.2.1", http=httpx.Client(
        base_url="http://192.0.2.1:8000", transport=httpx.MockTransport(handler)), mqtt=None)


def test_http_get_returns_bytes() -> None:
    assert json.loads(make().http_get(r.HEALTH_PATH))["estop_triggered"] is False


def test_http_post_json_sends_json() -> None:
    assert make().http_post_json(*r.move_absolute({1: 10})) == b"{}"


def test_non_200_raises_transport_error_with_path() -> None:
    with pytest.raises(TransportError, match="/smartDrives/position"):
        make().http_get(r.POSITION_PATH)


def test_mqtt_cache_updates_from_messages() -> None:
    t = make()
    t._on_message(None, None, _Msg(r.TOPIC_ESTOP_STATUS, b"true"))
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"


class _Msg:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic, self.payload = topic, payload


@pytest.mark.hardware
def test_real_controller_health() -> None:
    t = MachineMotionTransport(r.DEFAULT_IP_ETHERNET)
    try:
        assert b"mqtt_services_running" in t.http_get(r.HEALTH_PATH)
    finally:
        t.close()
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `device/machinemotion.py`:
```python
"""Real MachineMotion 2 transport: HTTP on :8000 and MQTT on :1883 (spec §2).

The ONLY module that opens sockets to the controller. HTTP mirrors HTTPSend
(MachineMotion.py:364-410: GET, or POST with Content-type application/json); MQTT mirrors the
SDK client (:813-819 connect with no auth, :2762-2771 subscriptions, :2802-2899 caches).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx

from vention_printer_interface.device import register_transport
from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import routes as r

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 5.0  # the SDK uses 65 s (:355); we poll, so fail fast and let protection act


class MachineMotionTransport(Transport):
    name = "machinemotion"

    def __init__(self, ip: str, *, http: httpx.Client | None = None, mqtt: Any = "auto",
                 mqtt_connect_timeout_s: float = 5.0) -> None:
        self.ip = ip
        self._http = http or httpx.Client(base_url=f"http://{ip}:{r.HTTP_PORT}", timeout=HTTP_TIMEOUT_S)
        self._cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()
        self._cond = threading.Condition(self._cache_lock)
        self._mqtt: Any = None
        if mqtt == "auto":
            self._mqtt = self._connect_mqtt(mqtt_connect_timeout_s)
        elif mqtt is not None:
            self._mqtt = mqtt

    def _connect_mqtt(self, timeout_s: float) -> Any:
        import paho.mqtt.client as mqtt  # local import: keeps import-time deps light

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        try:
            client.connect(self.ip, r.MQTT_PORT, keepalive=30)
        except OSError as exc:
            raise TransportError(f"MQTT connect to {self.ip}:{r.MQTT_PORT} failed: {exc}") from exc
        client.loop_start()
        return client

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any, *args: Any) -> None:
        for topic in r.SUBSCRIPTIONS:
            client.subscribe(topic)
        log.info("MQTT connected to %s; subscribed %d topics", self.ip, len(r.SUBSCRIPTIONS))

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        with self._cond:
            self._cache[msg.topic] = payload
            self._cond.notify_all()

    # ---- HTTP -------------------------------------------------------------------------------
    def http_get(self, path: str) -> bytes:
        return self._request("GET", path, None)

    def http_post_json(self, path: str, body: dict[str, float]) -> bytes:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: dict[str, float] | None) -> bytes:
        try:
            if body is None:
                resp = self._http.request(method, path)
            else:
                resp = self._http.request(method, path, content=json.dumps(body),
                                          headers={"Content-type": "application/json"})
        except httpx.HTTPError as exc:
            raise TransportError(f"Could not {method} {path}: {exc}") from exc
        if resp.status_code != 200:
            raise TransportError(
                f"request http://{self.ip}:{r.HTTP_PORT}{path} failed with status "
                f"{resp.status_code}: {resp.text[:120]}")
        return resp.content

    # ---- MQTT -------------------------------------------------------------------------------
    def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        if self._mqtt is None:
            raise TransportError("MQTT not connected")
        self._mqtt.publish(topic, payload, retain=retain)

    def mqtt_latest(self, topic: str) -> str | None:
        with self._cache_lock:
            return self._cache.get(topic)

    def mqtt_request(self, request_topic: str, response_topic: str, payload: str,
                     timeout_s: float) -> str:
        if self._mqtt is None:
            raise TransportError("MQTT not connected")
        with self._cond:
            self._cache.pop(response_topic, None)
            self._mqtt.subscribe(response_topic)
            self._mqtt.publish(request_topic, payload)
            if not self._cond.wait_for(lambda: response_topic in self._cache, timeout=timeout_s):
                raise TransportError(f"no response on {response_topic} within {timeout_s}s")
            return self._cache[response_topic]

    def close(self) -> None:
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._mqtt = None
        self._http.close()


register_transport("machinemotion")(MachineMotionTransport)
```

- [ ] **Step 4: Run** `uv run pytest tests/test_machinemotion.py -q` (hardware test skipped) → pass; ruff + mypy clean.
- [ ] **Step 5: Commit** `git commit -am "feat(device): real MachineMotion transport over httpx and paho-mqtt"`

---

### Task 7: PrinterDevice — one method per capability

**Files:**
- Create: `device/printer.py`
- Test: `tests/test_printer.py`

- [ ] **Step 1: Failing tests**
```python
import pytest

from vention_printer_interface.device.printer import AxisConfig, PrinterDevice, Telemetry
from vention_printer_interface.device.simulated import SimulatedTransport


def make() -> tuple[PrinterDevice, SimulatedTransport]:
    t = SimulatedTransport(realtime=False)
    return PrinterDevice(t, heater_io=(1, 2)), t


def test_identify_reads_version_and_axes() -> None:
    d, _ = make()
    info = d.identify()
    assert info["version"] == "2.14.1"
    assert info["async_supported"] is True
    assert [a.name for a in d.axes.values()] == ["Part Piston", "Feed Piston", "Printhead Gantry", "Recoater Gantry"]


def test_read_telemetry_shape() -> None:
    d, t = make()
    d.home_all(); t.advance(60)
    tel = d.read_telemetry()
    assert isinstance(tel, Telemetry)
    assert tel.positions == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    assert tel.motion_complete == {1: True, 2: True, 3: True, 4: True}
    assert tel.estop_triggered is False and tel.drives_ready is True
    assert tel.heater_on is False


def test_move_and_speed() -> None:
    d, t = make()
    d.home_all(); t.advance(60)
    d.set_max_speed(3, 100); d.set_max_accel(3, 500)
    d.move_absolute(3, 50); t.advance(1)
    assert d.read_telemetry().positions[3] == pytest.approx(50)
    d.move_relative(3, -20); t.advance(1)
    assert d.read_telemetry().positions[3] == pytest.approx(30)


def test_heater_write_and_read() -> None:
    d, _ = make()
    d.heater_write(True)
    assert d.read_telemetry().heater_on is True
    d.heater_write(False)
    assert d.read_telemetry().heater_on is False


def test_estop_cycle() -> None:
    d, t = make()
    assert d.estop_trigger("test") is True
    assert d.read_telemetry().estop_triggered is True
    assert d.estop_release() is True
    assert d.estop_reset() is True
    t.advance(3.1)
    assert d.read_telemetry().drives_ready is True


def test_axis_config_frozen() -> None:
    a = AxisConfig(number=1, name="Part Piston", travel_mm=145.0, homing_speed=68.8)
    with pytest.raises(AttributeError):
        a.name = "x"  # type: ignore[misc]
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `device/printer.py`:
```python
"""PrinterDevice: high-level, one method per controller capability (spec §1).

Wraps a Transport; never decides policy (that is the Controller). There is deliberately no method
that writes drive configuration or motor current — those routes exist in the SDK but are out of
scope (spec Non-goals), so they cannot be called by accident.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import parsers as p
from vention_printer_interface.protocol import routes as r

# Extents (mm) measured on our printer (vention/python/V1.py constants); names from
# vention/json/configuration.json. Overridden by /smartDrives/configuration when it answers.
KNOWN_AXES: dict[int, tuple[str, float, float]] = {
    1: ("Part Piston", 145.0, 68.8),
    2: ("Feed Piston", 145.0, 68.8),
    3: ("Printhead Gantry", 840.0, 66.3),
    4: ("Recoater Gantry", 930.0, 66.3),
}


@dataclass(frozen=True)
class AxisConfig:
    number: int
    name: str
    travel_mm: float
    homing_speed: float


@dataclass(frozen=True)
class Telemetry:
    host_timestamp_ns: int
    positions: dict[int, float]
    motion_complete: dict[int, bool]
    estop_triggered: bool
    drives_ready: bool
    health_ok: bool
    heater_on: bool


class PrinterDevice:
    def __init__(self, transport: Transport, *, heater_io: tuple[int, int] | None = None) -> None:
        self._t = transport
        self.heater_io = heater_io
        self.axes: dict[int, AxisConfig] = {
            n: AxisConfig(n, name, travel, hs) for n, (name, travel, hs) in KNOWN_AXES.items()}
        self._health: p.HealthInfo | None = None

    @property
    def transport_name(self) -> str:
        return self._t.name

    # ---- identity ---------------------------------------------------------------------------
    def health(self) -> p.HealthInfo:
        self._health = p.parse_health(self._t.http_get(r.HEALTH_PATH))
        return self._health

    def identify(self) -> dict[str, Any]:
        h = self.health()
        for n in list(self.axes):
            try:
                cfg = p._json(self._t.http_get(r.drive_config_path(n)))  # shape UNVERIFIED
            except (TransportError, p.ProtocolError):
                continue
            if isinstance(cfg, dict) and isinstance(cfg.get("friendlyName"), str):
                base = self.axes[n]
                self.axes[n] = AxisConfig(n, cfg["friendlyName"], base.travel_mm,
                                          float(cfg.get("homingSpeed", base.homing_speed)))
        return {
            "transport": self._t.name,
            "version": ".".join(map(str, h.version)),
            "async_supported": h.async_supported,
            "estop_triggered": h.estop_triggered,
            "motion_controller_reachable": h.motion_controller_reachable,
            "axes": {n: a.__dict__ for n, a in self.axes.items()},
            "heater_io": self.heater_io,
        }

    # ---- telemetry --------------------------------------------------------------------------
    def read_telemetry(self) -> Telemetry:
        positions = p.parse_positions(self._t.http_get(r.POSITION_PATH))
        complete = {n: p.parse_complete(self._t.http_get(r.complete_path(n))) for n in self.axes}
        estop_raw = self._t.mqtt_latest(r.TOPIC_ESTOP_STATUS)
        ready_raw = self._t.mqtt_latest(r.TOPIC_DRIVES_READY)
        estop = p.parse_json_bool(estop_raw) if estop_raw is not None else False
        ready = p.parse_json_bool(ready_raw) if ready_raw is not None else True
        health_ok = self._health is not None and self._health.motion_controller_reachable is not False
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
    def _gcode(self, gcode: str) -> str:
        return p.parse_echo_ok(self._t.http_get(r.gcode_path(gcode)).decode())

    def home_all(self) -> None:
        self._gcode(r.GCODE_HOME_ALL)

    def home(self, axis: int) -> None:
        self._gcode(r.gcode_home(axis))

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
        return p.parse_motion_status(self._t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode())

    # ---- e-stop (MQTT round trips, MachineMotion.py:2350-2499) ------------------------------
    def estop_trigger(self, reason: str = "vpi") -> bool:
        return p.parse_json_bool(self._t.mqtt_request(
            r.TOPIC_ESTOP_TRIGGER_REQUEST, r.TOPIC_ESTOP_TRIGGER_RESPONSE, reason, r.MQTT_RESPONSE_TIMEOUT_S))

    def estop_release(self) -> bool:
        return p.parse_json_bool(self._t.mqtt_request(
            r.TOPIC_ESTOP_RELEASE_REQUEST, r.TOPIC_ESTOP_RELEASE_RESPONSE, "", r.MQTT_RESPONSE_TIMEOUT_S))

    def estop_reset(self) -> bool:
        return p.parse_json_bool(self._t.mqtt_request(
            r.TOPIC_ESTOP_RESET_REQUEST, r.TOPIC_ESTOP_RESET_RESPONSE, "", r.MQTT_RESPONSE_TIMEOUT_S))

    # ---- heater relay on an IO module ------------------------------------------------------
    def heater_write(self, on: bool) -> None:
        if self.heater_io is None:
            raise TransportError("heater IO module/pin not configured")
        dev, pin = self.heater_io
        self._t.mqtt_publish(r.io_output_topic(dev, pin), "1" if on else "0", retain=True)

    def heater_read(self) -> bool:
        if self.heater_io is None:
            return False
        dev, pin = self.heater_io
        return self._t.mqtt_latest(r.io_output_topic(dev, pin)) == "1"

    def close(self) -> None:
        self._t.close()
```
Also make `parsers._json` public: rename to `parse_json` and update `identify()` to call `p.parse_json`. Keep `_json` as an alias inside parsers for internal use.

- [ ] **Step 4: Run** `uv run pytest -q` → all pass; lint clean.
- [ ] **Step 5: Commit** `git commit -am "feat(device): PrinterDevice with telemetry, motion, e-stop and heater IO"`

---

### Task 8: Pure protection evaluator

**Files:**
- Create: `control/__init__.py` (docstring), `control/safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Failing tests**
```python
import time

import pytest

from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits, evaluate
from vention_printer_interface.device.printer import Telemetry


def tel(**kw: object) -> Telemetry:
    base = dict(host_timestamp_ns=time.time_ns(), positions={1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0},
                motion_complete={1: True, 2: True, 3: True, 4: True}, estop_triggered=False,
                drives_ready=True, health_ok=True, heater_on=False)
    base.update(kw)
    return Telemetry(**base)  # type: ignore[arg-type]


def test_clean_sample_no_trip() -> None:
    d = evaluate(tel(), SafetyLimits(), telemetry_age_s=0.1, heater_on_s=0.0, move_pending=False)
    assert d.trip is False and d.reasons == () and d.warnings == ()


def test_stale_telemetry_trips() -> None:
    d = evaluate(tel(), SafetyLimits(), telemetry_age_s=10, heater_on_s=0, move_pending=False)
    assert d.trip and "stale" in d.reasons[0]


def test_estop_trips() -> None:
    d = evaluate(tel(estop_triggered=True), SafetyLimits(), 0.1, 0, False)
    assert d.trip and "e-stop" in d.reasons[0]


def test_drives_not_ready_trips_only_when_move_pending() -> None:
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, False).trip is False
    assert evaluate(tel(drives_ready=False), SafetyLimits(), 0.1, 0, True).trip is True


def test_soft_travel_limit_trips_and_warns() -> None:
    lim = SafetyLimits()
    assert evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 931}), lim, 0.1, 0, False).trip
    w = evaluate(tel(positions={1: 10, 2: 10, 3: 10, 4: 927}), lim, 0.1, 0, False)
    assert not w.trip and any("near" in x for x in w.warnings)


def test_heater_watchdog() -> None:
    lim = SafetyLimits(heater_max_on_s=10)
    assert evaluate(tel(heater_on=True), lim, 0.1, 11, False).trip
    assert not evaluate(tel(heater_on=True), lim, 0.1, 9, False).trip


def test_health_not_ok_trips() -> None:
    assert evaluate(tel(health_ok=False), SafetyLimits(), 0.1, 0, False).trip


def test_bounded_is_tighten_only() -> None:
    lim = SafetyLimits.bounded(heater_max_on_s=99999, max_speed={3: 100000})
    assert lim.heater_max_on_s == HARD_BOUNDS["heater_max_on_s"][1]
    assert lim.max_speed[3] == HARD_BOUNDS["max_speed"][3][1]


def test_clamp_speed() -> None:
    lim = SafetyLimits()
    assert lim.clamp_speed(1, 1000) == lim.max_speed[1]
    with pytest.raises(ValueError):
        lim.clamp_speed(9, 1)
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `control/safety.py`:
```python
"""Protection layer as a pure function (spec §3). No threads, no IO, no hardware.

HARD_BOUNDS are tighten-only: the operator can narrow limits but never widen them. Travel comes
from our measured axis extents (V1.py), homing feedrate limits from MachineMotion.py:189-190
(500..8000 mm/min = 8.3..133 mm/s). Defaults are conservative starting values, NOT validated
safe limits; revise in plan/notes.md after commissioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRAVEL_MM: dict[int, float] = {1: 145.0, 2: 145.0, 3: 840.0, 4: 930.0}  # V1.py

HARD_BOUNDS: dict[str, object] = {
    "max_speed": {1: (0.1, 20.0), 2: (0.1, 20.0), 3: (0.1, 300.0), 4: (0.1, 300.0)},  # mm/s
    "max_accel": {1: (1.0, 100.0), 2: (1.0, 100.0), 3: (1.0, 2000.0), 4: (1.0, 2000.0)},  # mm/s^2
    "travel": {n: (0.0, t) for n, t in TRAVEL_MM.items()},  # mm
    "heater_max_on_s": (5.0, 600.0),
    "telemetry_timeout_s": (0.5, 5.0),
    "near_limit_mm": (0.0, 20.0),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


@dataclass(frozen=True)
class SafetyLimits:
    max_speed: dict[int, float] = field(default_factory=lambda: {1: 5.0, 2: 5.0, 3: 200.0, 4: 200.0})
    max_accel: dict[int, float] = field(default_factory=lambda: {1: 30.0, 2: 30.0, 3: 1000.0, 4: 1000.0})
    travel_min: dict[int, float] = field(default_factory=lambda: {n: 0.0 for n in TRAVEL_MM})
    travel_max: dict[int, float] = field(default_factory=lambda: dict(TRAVEL_MM))
    heater_max_on_s: float = 120.0
    telemetry_timeout_s: float = 2.0
    near_limit_mm: float = 5.0  # warning band

    @classmethod
    def bounded(cls, **kw: object) -> SafetyLimits:
        """Build limits clamped into HARD_BOUNDS (tighten-only)."""
        base = cls()
        ms = dict(base.max_speed)
        for n, v in (kw.get("max_speed") or {}).items():  # type: ignore[union-attr]
            lo, hi = HARD_BOUNDS["max_speed"][int(n)]  # type: ignore[index]
            ms[int(n)] = _clamp(v, lo, hi)
        ma = dict(base.max_accel)
        for n, v in (kw.get("max_accel") or {}).items():  # type: ignore[union-attr]
            lo, hi = HARD_BOUNDS["max_accel"][int(n)]  # type: ignore[index]
            ma[int(n)] = _clamp(v, lo, hi)
        tmin = dict(base.travel_min)
        tmax = dict(base.travel_max)
        for n, v in (kw.get("travel_min") or {}).items():  # type: ignore[union-attr]
            tmin[int(n)] = _clamp(v, 0.0, TRAVEL_MM[int(n)])
        for n, v in (kw.get("travel_max") or {}).items():  # type: ignore[union-attr]
            tmax[int(n)] = _clamp(v, 0.0, TRAVEL_MM[int(n)])
        for n in TRAVEL_MM:
            if tmin[n] > tmax[n]:
                tmin[n], tmax[n] = tmax[n], tmin[n]
        h_lo, h_hi = HARD_BOUNDS["heater_max_on_s"]  # type: ignore[misc]
        t_lo, t_hi = HARD_BOUNDS["telemetry_timeout_s"]  # type: ignore[misc]
        n_lo, n_hi = HARD_BOUNDS["near_limit_mm"]  # type: ignore[misc]
        return cls(
            max_speed=ms, max_accel=ma, travel_min=tmin, travel_max=tmax,
            heater_max_on_s=_clamp(float(kw.get("heater_max_on_s", base.heater_max_on_s)), h_lo, h_hi),  # type: ignore[arg-type]
            telemetry_timeout_s=_clamp(float(kw.get("telemetry_timeout_s", base.telemetry_timeout_s)), t_lo, t_hi),  # type: ignore[arg-type]
            near_limit_mm=_clamp(float(kw.get("near_limit_mm", base.near_limit_mm)), n_lo, n_hi),  # type: ignore[arg-type]
        )

    def clamp_speed(self, axis: int, mm_s: float) -> float:
        if axis not in self.max_speed:
            raise ValueError(f"unknown axis {axis}")
        return _clamp(mm_s, 0.1, self.max_speed[axis])

    def clamp_accel(self, axis: int, mm_s2: float) -> float:
        if axis not in self.max_accel:
            raise ValueError(f"unknown axis {axis}")
        return _clamp(mm_s2, 1.0, self.max_accel[axis])

    def clamp_position(self, axis: int, mm: float) -> float:
        if axis not in self.travel_max:
            raise ValueError(f"unknown axis {axis}")
        return _clamp(mm, self.travel_min[axis], self.travel_max[axis])

    def to_dict(self) -> dict[str, object]:
        return {
            "max_speed": dict(self.max_speed), "max_accel": dict(self.max_accel),
            "travel_min": dict(self.travel_min), "travel_max": dict(self.travel_max),
            "heater_max_on_s": self.heater_max_on_s,
            "telemetry_timeout_s": self.telemetry_timeout_s, "near_limit_mm": self.near_limit_mm,
        }


@dataclass(frozen=True)
class SafetyDecision:
    trip: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def evaluate(telemetry: "Telemetry", limits: SafetyLimits, telemetry_age_s: float,
             heater_on_s: float, move_pending: bool) -> SafetyDecision:
    reasons: list[str] = []
    warnings: list[str] = []
    if telemetry_age_s > limits.telemetry_timeout_s:
        reasons.append(f"telemetry stale ({telemetry_age_s:.1f}s > {limits.telemetry_timeout_s}s)")
    if telemetry.estop_triggered:
        reasons.append("controller e-stop asserted")
    if not telemetry.health_ok:
        reasons.append("controller health not ok (motion controller unreachable)")
    if move_pending and not telemetry.drives_ready:
        reasons.append("drives not ready while a move is pending")
    for axis, pos in telemetry.positions.items():
        lo, hi = limits.travel_min.get(axis, 0.0), limits.travel_max.get(axis, TRAVEL_MM.get(axis, 0.0))
        if pos < lo - 0.01 or pos > hi + 0.01:
            reasons.append(f"axis {axis} at {pos:.2f} mm outside [{lo:.1f}, {hi:.1f}]")
        elif pos - lo < limits.near_limit_mm or hi - pos < limits.near_limit_mm:
            warnings.append(f"axis {axis} near travel limit ({pos:.1f} mm)")
    if telemetry.heater_on and heater_on_s > limits.heater_max_on_s:
        reasons.append(f"heater on {heater_on_s:.0f}s > watchdog {limits.heater_max_on_s:.0f}s")
    return SafetyDecision(trip=bool(reasons), reasons=tuple(reasons), warnings=tuple(warnings))


from vention_printer_interface.device.printer import Telemetry  # noqa: E402 (type only, avoids cycle)
```
(Put the `Telemetry` import at the top under `TYPE_CHECKING` instead if mypy prefers; either is fine as long as ruff/mypy are clean.)

- [ ] **Step 4: Run** `uv run pytest tests/test_safety.py -q` → pass; lint clean.
- [ ] **Step 5: Commit** `git commit -am "feat(control): pure protection evaluator with tighten-only limits"`

---

### Task 9: Supervisory Controller

**Files:**
- Create: `control/controller.py`
- Test: `tests/test_controller.py`

- [ ] **Step 1: Failing tests**
```python
import time

import pytest

from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.safety import SafetyLimits
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.device.simulated import SimulatedTransport


def make(**sim: object) -> tuple[Controller, SimulatedTransport]:
    t = SimulatedTransport(realtime=True, **sim)  # type: ignore[arg-type]
    c = Controller(poll_interval_s=0.05, limits=SafetyLimits())
    c.attach_device(PrinterDevice(t, heater_io=(1, 2)), backend="simulated")
    return c, t


def wait(pred, timeout=2.0):  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_attach_connects_and_polls() -> None:
    c, _ = make()
    try:
        assert c.state == ControllerState.CONNECTED
        assert wait(lambda: c.snapshot()["telemetry"] is not None)
        assert c.snapshot()["armed"] is False
    finally:
        c.stop()


def test_commands_refused_until_armed() -> None:
    c, _ = make()
    try:
        with pytest.raises(RuntimeError, match="not armed"):
            c.home_all()
        c.arm()
        c.home_all()
        assert c.snapshot()["armed"] is True
    finally:
        c.stop()


def test_move_is_clamped_and_speed_bounded() -> None:
    c, t = make()
    try:
        c.arm(); c.home_all()
        assert wait(lambda: all(c.snapshot()["telemetry"]["motion_complete"].values()) and c.snapshot()["telemetry"]["positions"]["3"] == 0)
        assert c.set_max_speed(3, 99999) == SafetyLimits().max_speed[3]
        assert c.move_absolute(3, 5000) == 840.0
    finally:
        c.stop()


def test_estop_bypasses_gate_and_kills_heater() -> None:
    c, t = make()
    try:
        c.arm(); c.heater_on()
        assert t.mqtt_latest("devices/io-expander/1/digital-output/2") == "1"
        c.estop()
        assert t.mqtt_latest("devices/io-expander/1/digital-output/2") == "0"
        assert c.snapshot()["armed"] is False
        assert wait(lambda: c.state == ControllerState.FAULT)
    finally:
        c.stop()


def test_stale_telemetry_faults_and_clear_requires_clean() -> None:
    c, t = make()
    try:
        c.arm(); c.heater_on()
        t._unreachable = True
        assert wait(lambda: c.state == ControllerState.FAULT, 3)
        with pytest.raises(RuntimeError):
            c.clear_fault()
        t._unreachable = False
        assert wait(lambda: c.snapshot()["telemetry"] is not None and c.snapshot()["telemetry"]["health_ok"], 3)
        c.clear_fault()
        assert c.state == ControllerState.CONNECTED
        assert c.snapshot()["armed"] is False
    finally:
        c.stop()


def test_listener_receives_snapshots_and_exceptions_are_swallowed() -> None:
    c, _ = make()
    seen: list[dict] = []
    c.add_listener(lambda s: seen.append(s))
    c.add_listener(lambda s: 1 / 0)
    try:
        assert wait(lambda: len(seen) > 2)
    finally:
        c.stop()


def test_detach_forces_heater_off_and_disconnects() -> None:
    c, t = make()
    c.arm(); c.heater_on()
    c.detach_device()
    assert t.mqtt_latest("devices/io-expander/1/digital-output/2") == "0"
    assert c.state == ControllerState.DISCONNECTED
    c.stop()


def test_ungated_safe_direction_commands() -> None:
    c, _ = make()
    try:
        c.stop_all()  # never gated
        c.heater_off()
    finally:
        c.stop()
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `control/controller.py`:
```python
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


class ControllerState(str, enum.Enum):
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
        self._device_info: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle --------------------------------------------------------------------------
    def attach_device(self, device: PrinterDevice, *, backend: str) -> None:
        self.detach_device()
        with self._io_lock:
            try:
                self._device_info = device.identify()
            except Exception:
                device.close()
                raise
        with self._lock:
            self._device, self.backend = device, backend
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
                for fn in (dev.stop_all, lambda: dev.heater_write(False), dev.close):
                    try:
                        fn()
                    except Exception as exc:  # noqa: BLE001 - detach is best-effort, must finish
                        log.warning("detach step failed: %s", exc)
        with self._lock:
            self._device, self.backend = None, "none"
            self.state, self.armed = ControllerState.DISCONNECTED, False
            self._telemetry, self._fault_reasons, self._heater_on_since = None, (), None

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
            self._enter_fault((f"telemetry read failed: {exc}",))
            self._notify()
            return
        self._last_read_done = time.monotonic()
        with self._lock:
            self._telemetry = tel
            if tel.heater_on and self._heater_on_since is None:
                self._heater_on_since = start
            if not tel.heater_on:
                self._heater_on_since = None
            heater_on_s = (start - self._heater_on_since) if self._heater_on_since else 0.0
            if all(tel.motion_complete.values()):
                self._move_pending = False
            decision: SafetyDecision = evaluate(tel, self.limits, age, heater_on_s, self._move_pending)
            self._warnings = decision.warnings
        if decision.trip and self.state != ControllerState.FAULT:
            self._enter_fault(decision.reasons)
        self._notify()

    def _enter_fault(self, reasons: tuple[str, ...]) -> None:
        log.error("FAULT: %s", "; ".join(reasons))
        dev = self._device
        if dev is not None:
            with self._io_lock:
                for fn in (dev.stop_all, lambda: dev.heater_write(False)):
                    try:
                        fn()
                    except Exception as exc:  # noqa: BLE001 - keep going: latch the fault regardless
                        log.warning("fault action failed: %s", exc)
        with self._lock:
            self.state, self.armed = ControllerState.FAULT, False
            self._fault_reasons, self._heater_on_since = reasons, None

    def clear_fault(self) -> None:
        with self._lock:
            tel = self._telemetry
            if self.state != ControllerState.FAULT:
                return
            if tel is None:
                raise RuntimeError("cannot clear fault: no telemetry")
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
            except Exception as exc:  # noqa: BLE001 - a listener must never break the control loop
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
        dev = self._require_armed()
        tel = self._telemetry
        here = tel.positions.get(axis, 0.0) if tel else 0.0
        target = self.limits.clamp_position(axis, here + mm)
        with self._io_lock:
            self._move_pending = True
            dev.move_absolute(axis, target)  # relative moves are clamped by issuing an absolute
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
            for fn in (dev.stop_all, lambda: dev.heater_write(False), lambda: dev.estop_trigger("vpi operator")):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001 - e-stop must complete every step
                    log.warning("e-stop step failed: %s", exc)

    # ---- snapshot ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            tel = self._telemetry
            heater_on_s = (time.monotonic() - self._heater_on_since) if self._heater_on_since else 0.0
            return {
                "state": self.state.value,
                "backend": self.backend,
                "armed": self.armed,
                "fault_reasons": list(self._fault_reasons),
                "warnings": list(self._warnings),
                "device": self._device_info,
                "limits": self.limits.to_dict(),
                "heater": {"on": bool(tel and tel.heater_on), "on_s": round(heater_on_s, 1),
                           "max_on_s": self.limits.heater_max_on_s},
                "telemetry": None if tel is None else {
                    "host_timestamp_ns": tel.host_timestamp_ns,
                    "positions": {str(k): v for k, v in tel.positions.items()},
                    "motion_complete": {str(k): v for k, v in tel.motion_complete.items()},
                    "estop_triggered": tel.estop_triggered,
                    "drives_ready": tel.drives_ready,
                    "health_ok": tel.health_ok,
                    "heater_on": tel.heater_on,
                },
            }
```

- [ ] **Step 4: Run** `uv run pytest tests/test_controller.py -q` → pass. Fix any flake by raising `wait` timeouts, not by sleeping in code.
- [ ] **Step 5: Commit** `git commit -am "feat(control): supervisory controller with ARM gate, e-stop, protection and listeners"`

---

### Task 10: Limits persistence

**Files:**
- Create: `control/limits_store.py`
- Test: `tests/test_limits_store.py`

- [ ] **Step 1: Failing tests**
```python
from pathlib import Path

from vention_printer_interface.control.limits_store import CONFIG_NAME, load_limits, save_limits
from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits


def test_round_trip(tmp_path: Path) -> None:
    save_limits(tmp_path, SafetyLimits(heater_max_on_s=42))
    assert (tmp_path / CONFIG_NAME).exists()
    assert load_limits(tmp_path).heater_max_on_s == 42


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_limits(tmp_path) == SafetyLimits()


def test_hand_edited_file_is_reclamped(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text('{"heater_max_on_s": 999999}')
    assert load_limits(tmp_path).heater_max_on_s == HARD_BOUNDS["heater_max_on_s"][1]


def test_corrupt_file_gives_defaults(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text("not json")
    assert load_limits(tmp_path) == SafetyLimits()
```

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement**
```python
"""Persist SafetyLimits as a dotfile under experiments_root; loading always re-clamps."""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.control.safety import SafetyLimits

CONFIG_NAME = ".limits.json"


def load_limits(root: Path) -> SafetyLimits:
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return SafetyLimits()
    if not isinstance(data, dict):
        return SafetyLimits()
    return SafetyLimits.bounded(**data)


def save_limits(root: Path, limits: SafetyLimits) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_NAME).write_text(json.dumps(limits.to_dict(), indent=2))
```
- [ ] **Step 4: Run** → pass. **Step 5: Commit** `git commit -am "feat(control): limits persistence with re-clamp on load"`

---

### Task 11: Run recorder

**Files:**
- Create: `recording/__init__.py`, `recording/recorder.py`
- Test: `tests/test_recorder.py`

- [ ] **Step 1: Failing tests**
```python
import json
from pathlib import Path

from vention_printer_interface.recording.recorder import Recorder


def snap(z: float = 1.0, heater: bool = False) -> dict:
    return {"state": "connected", "armed": True, "heater": {"on": heater, "on_s": 0},
            "telemetry": {"host_timestamp_ns": 1, "positions": {"1": z, "2": 0, "3": 0, "4": 0},
                          "motion_complete": {"1": True, "2": True, "3": True, "4": True},
                          "estop_triggered": False, "drives_ready": True, "health_ok": True,
                          "heater_on": heater}}


def test_layout_and_manifest_on_clean_stop(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("Test Run", notes="n", metadata={"backend": "simulated"})
    assert (run / "metadata.json").exists()
    rec.record(snap(1.0)); rec.record(snap(2.0))
    rec.event("layer_completed", {"layer": 1})
    rec.stop()
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["complete"] is True and manifest["sample_count"] == 2
    assert set(manifest["checksums"]) == {"metadata.json", "events.json", "telemetry.csv"}
    lines = (run / "telemetry.csv").read_text().splitlines()
    assert lines[0].startswith("host_timestamp_ns,controller_state,armed,pos_1,pos_2,pos_3,pos_4")
    assert len(lines) == 3
    events = json.loads((run / "events.json").read_text())
    assert [e["label"] for e in events] == ["recording_started", "layer_completed", "recording_stopped"]


def test_missing_manifest_means_incomplete(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    run = rec.start("crash")
    rec.record(snap())
    assert not (run / "manifest.json").exists()
    assert rec.list_runs() == [{"run": run.name, "complete": False, "size_bytes": rec.list_runs()[0]["size_bytes"]}]


def test_slug_and_collision(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    a = rec.start("My Part!"); rec.stop()
    b = rec.start("My Part!"); rec.stop()
    assert a.name.endswith("_My_Part") and b.name.endswith("_My_Part_2")


def test_record_ignored_when_idle(tmp_path: Path) -> None:
    rec = Recorder(tmp_path)
    rec.record(snap())
    assert rec.active is None
```

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement** `recording/__init__.py` (docstring) and `recording/recorder.py`:
```python
"""Run recorder (spec §4). Mirrors the FLIR/T&C integrity model.

experiments/<YYYYMMDD_HHMMSS>_<slug>/ : metadata.json at start; telemetry.csv streamed and
flushed per row; events.json + manifest.json (sha256 checksums, complete=true) ONLY on clean
stop. A missing manifest.json marks a crashed or incomplete run.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vention_printer_interface import __version__

FORMAT_VERSION = 1
TELEMETRY_FIELDS = ["host_timestamp_ns", "controller_state", "armed", "pos_1", "pos_2", "pos_3",
                    "pos_4", "complete_1", "complete_2", "complete_3", "complete_4",
                    "estop_triggered", "drives_ready", "health_ok", "heater_on", "heater_on_s"]


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "run"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active: Path | None = None
        self._csv: Any = None
        self._file: Any = None
        self._events: list[dict[str, Any]] = []
        self._count = 0
        self._started = 0.0

    def start(self, name: str, *, notes: str = "", metadata: dict[str, Any] | None = None) -> Path:
        if self.active is not None:
            raise RuntimeError("already recording")
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        base = f"{stamp}_{_slug(name)}"
        run, n = self.root / base, 2
        while run.exists():
            run, n = self.root / f"{base}_{n}", n + 1
        run.mkdir()
        meta = {
            "format_version": FORMAT_VERSION,
            "started_utc": datetime.now(UTC).isoformat(),
            "experiment": {"name": name, "notes": notes, **(metadata or {})},
            "software": {"name": "vention-printer-interface", "version": __version__,
                         "python": platform.python_version(), "platform": platform.platform()},
        }
        (run / "metadata.json").write_text(json.dumps(meta, indent=2))
        self._file = (run / "telemetry.csv").open("w", newline="")
        self._csv = csv.writer(self._file)
        self._csv.writerow(TELEMETRY_FIELDS)
        self._file.flush()
        self._events, self._count, self._started = [], 0, time.time()
        self.active = run
        self.event("recording_started", {"name": name})
        return run

    def record(self, snapshot: dict[str, Any]) -> None:
        if self.active is None or not snapshot.get("telemetry"):
            return
        t = snapshot["telemetry"]
        pos, comp = t["positions"], t["motion_complete"]
        self._csv.writerow([
            t["host_timestamp_ns"], snapshot["state"], snapshot["armed"],
            pos.get("1"), pos.get("2"), pos.get("3"), pos.get("4"),
            comp.get("1"), comp.get("2"), comp.get("3"), comp.get("4"),
            t["estop_triggered"], t["drives_ready"], t["health_ok"], t["heater_on"],
            snapshot.get("heater", {}).get("on_s", 0),
        ])
        self._file.flush()
        self._count += 1

    def event(self, label: str, data: dict[str, Any] | None = None) -> None:
        if self.active is None:
            return
        self._events.append({"host_timestamp_ns": time.time_ns(), "label": label, "data": data or {}})

    def stop(self) -> Path | None:
        run = self.active
        if run is None:
            return None
        self.event("recording_stopped", {})
        self._file.close()
        (run / "events.json").write_text(json.dumps(self._events, indent=2))
        manifest = {
            "complete": True,
            "sample_count": self._count,
            "duration_s": round(time.time() - self._started, 3),
            "checksums": {n: _sha256(run / n) for n in ("metadata.json", "events.json", "telemetry.csv")},
        }
        (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
        self.active, self._csv, self._file = None, None, None
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        out = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            out.append({"run": d.name, "complete": (d / "manifest.json").exists(), "size_bytes": size})
        return out
```
- [ ] **Step 4: Run** → pass. **Step 5: Commit** `git commit -am "feat(recording): run recorder with manifest-on-clean-stop integrity"`

---

### Task 12: FastAPI app, cross-origin policy, WebSocket

**Files:**
- Create: `api/__init__.py`, `api/app.py`
- Test: `tests/test_api.py`, `tests/test_cors.py`

- [ ] **Step 1: Failing tests**

`tests/test_api.py`:
```python
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


@pytest.fixture
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield c


def wait_tel(c: TestClient) -> dict:
    for _ in range(100):
        s = c.get("/api/status").json()
        if s["controller"]["telemetry"]:
            return s
        time.sleep(0.02)
    raise AssertionError("no telemetry")


def test_health(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["api_version"] == "0.1" and h["backend"] == "none"


def test_status_idle(client: TestClient) -> None:
    s = client.get("/api/status").json()
    assert s["controller"]["state"] == "disconnected"
    assert s["recording"] == {"active": False, "run": None}


def test_discovery_lists_simulated(client: TestClient) -> None:
    d = client.get("/api/discovery").json()
    assert any(c["backend"] == "simulated" for c in d["candidates"])


def test_connect_simulated_and_arm_flow(client: TestClient) -> None:
    r = client.post("/api/connect", json={"backend": "simulated"})
    assert r.status_code == 200 and r.json()["controller"]["state"] == "connected"
    assert client.post("/api/motion/home", json={"axes": []}).status_code == 409
    assert client.post("/api/arm").status_code == 200
    assert client.post("/api/motion/home", json={"axes": []}).status_code == 200
    wait_tel(client)
    r = client.post("/api/motion/move", json={"axis": 3, "mode": "abs", "mm": 9999})
    assert r.status_code == 200 and r.json()["applied_mm"] == 840.0
    assert client.post("/api/motion/stop", json={}).status_code == 200
    assert client.post("/api/disconnect").status_code == 200
    assert client.get("/api/status").json()["controller"]["state"] == "disconnected"


def test_connect_unknown_backend_400(client: TestClient) -> None:
    assert client.post("/api/connect", json={"backend": "nope"}).status_code == 400


def test_axis_motion_settings_have_bounds(client: TestClient) -> None:
    client.post("/api/connect", json={"backend": "simulated"}); client.post("/api/arm")
    r = client.put("/api/axes/3/motion", json={"max_speed": 5000, "max_accel": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["max_speed"] == 200.0 and "bounds" in body


def test_safety_limits_get_put(client: TestClient) -> None:
    g = client.get("/api/safety-limits").json()
    assert "bounds" in g and g["heater_max_on_s"] == 120.0
    r = client.put("/api/safety-limits", json={"heater_max_on_s": 30})
    assert r.json()["heater_max_on_s"] == 30.0


def test_heater_requires_arm_and_off_is_ungated(client: TestClient) -> None:
    client.post("/api/connect", json={"backend": "simulated"})
    assert client.post("/api/heater/on").status_code == 409
    assert client.post("/api/heater/off").status_code == 200
    client.post("/api/arm")
    assert client.post("/api/heater/on").status_code == 200
    assert wait_tel(client)["controller"]["heater"]["on"] is True


def test_estop_and_release(client: TestClient) -> None:
    client.post("/api/connect", json={"backend": "simulated"}); client.post("/api/arm")
    r = client.post("/api/estop")
    assert r.status_code == 200 and r.json() == {"ok": True}
    for _ in range(100):
        if client.get("/api/status").json()["controller"]["state"] == "fault":
            break
        time.sleep(0.02)
    assert client.post("/api/estop/release").status_code == 200
    # drives re-energise after ~3 s in the simulator; clear_fault then succeeds
    time.sleep(3.2)
    assert client.post("/api/clear-fault").status_code == 200


def test_recording_flow(client: TestClient, tmp_path: Path) -> None:
    client.post("/api/connect", json={"backend": "simulated"})
    wait_tel(client)
    r = client.post("/api/recording/start", json={"name": "run A", "notes": ""})
    assert r.status_code == 200
    assert client.post("/api/recording/start", json={"name": "x"}).status_code == 409
    time.sleep(0.2)
    stop = client.post("/api/recording/stop").json()
    runs = client.get("/api/recordings").json()["runs"]
    assert runs[0]["run"] == stop["run"] and runs[0]["complete"] is True
    assert client.get(f"/api/recordings/{stop['run']}/telemetry.csv").status_code == 200
    assert client.get("/api/recordings/../etc/telemetry.csv").status_code in (400, 404)


def test_ws_telemetry_pushes_status(client: TestClient) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        msg = ws.receive_json()
        assert msg["controller"]["state"] == "disconnected"
```

`tests/test_cors.py`:
```python
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


def test_cross_origin_write_without_header_is_403(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with TestClient(create_app(backend="none", experiments_root=tmp_path,
                               site_origin="https://mattlmccoy.github.io")) as c:
        r = c.post("/api/arm", headers={"Origin": "https://evil.example", "Host": "localhost:8020"})
        assert r.status_code == 403
        r = c.post("/api/arm", headers={"Origin": "https://mattlmccoy.github.io",
                                        "Host": "localhost:8020", "X-VPI-Client": "1"})
        assert r.status_code == 409  # passed the guard; refused by the controller (no device)
```

- [ ] **Step 2: Run** → ImportError.

- [ ] **Step 3: Implement** `api/__init__.py` (docstring) and `api/app.py`:
```python
"""FastAPI app (spec §5). GET /api/status and /ws/telemetry are the same payload.

Cross-origin policy is copied from FLIR/T&C: cross-origin state-changing /api/ requests must carry
``X-VPI-Client: 1``; CORS allows the hosted-site origin plus localhost.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vention_printer_interface import __version__
from vention_printer_interface.control.controller import Controller, ControllerState
from vention_printer_interface.control.limits_store import load_limits, save_limits
from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits
from vention_printer_interface.device import create_transport, registered_transports
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.protocol import routes as r
from vention_printer_interface.recording.recorder import Recorder

log = logging.getLogger(__name__)

API_VERSION = "0.1"
LOCAL_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
CLIENT_HEADER = "x-vpi-client"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def install_cross_origin_policy(app: FastAPI, *, site_origin: str | None) -> None:
    def _cross_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        host = request.headers.get("host", "")
        return origin.split("://", 1)[-1] != host

    @app.middleware("http")
    async def _client_header_guard(request: Request, call_next: Any) -> Any:
        if (request.method not in SAFE_METHODS and request.url.path.startswith("/api/")
                and _cross_origin(request) and request.headers.get(CLIENT_HEADER) != "1"):
            return JSONResponse({"detail": "browser requests must send the X-VPI-Client: 1 header"}, 403)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[site_origin] if site_origin else [],
        allow_origin_regex=LOCAL_ORIGIN_RE,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", CLIENT_HEADER],
        allow_private_network=True,
        max_age=600,
    )


class ConnectBody(BaseModel):
    backend: str
    ip: str | None = None
    heater_io: tuple[int, int] | None = (1, 0)


class HomeBody(BaseModel):
    axes: list[int] = Field(default_factory=list)


class MoveBody(BaseModel):
    axis: int = Field(ge=1, le=4)
    mode: str = Field(pattern="^(abs|rel)$")
    mm: float


class StopBody(BaseModel):
    axes: list[int] = Field(default_factory=list)


class AxisMotionBody(BaseModel):
    max_speed: float | None = None
    max_accel: float | None = None


class LimitsBody(BaseModel):
    max_speed: dict[int, float] | None = None
    max_accel: dict[int, float] | None = None
    travel_min: dict[int, float] | None = None
    travel_max: dict[int, float] | None = None
    heater_max_on_s: float | None = None
    telemetry_timeout_s: float | None = None
    near_limit_mm: float | None = None


class RecordingStartBody(BaseModel):
    name: str = "run"
    notes: str = ""


def _tcp_open(ip: str, port: int, timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def create_app(*, backend: str = "none", ip: str | None = None, poll_interval_s: float = 0.2,
               experiments_root: Path | None = None, limits: SafetyLimits | None = None,
               frontend_dist: Path | None = None, site_origin: str | None = None,
               heater_io: tuple[int, int] | None = None) -> FastAPI:
    root = experiments_root or Path.cwd() / "experiments"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        controller = Controller(poll_interval_s=poll_interval_s, limits=limits or load_limits(root))
        recorder = Recorder(root)
        controller.add_listener(recorder.record)
        app.state.controller, app.state.recorder, app.state.backend = controller, recorder, "none"
        app.state.axis_motion = {n: {"max_speed": None, "max_accel": None} for n in (1, 2, 3, 4)}
        if backend != "none":
            try:
                _attach(app, backend, ip, heater_io)
            except Exception as exc:  # noqa: BLE001 - device may be absent; serve anyway
                log.warning("boot attach failed (%s); serving idle", exc)
        try:
            yield
        finally:
            recorder.stop()
            controller.stop()

    app = FastAPI(title="Vention Printer Interface", version=__version__, lifespan=lifespan)
    install_cross_origin_policy(app, site_origin=site_origin)

    @app.middleware("http")
    async def _no_cache_html(request: Request, call_next: Any) -> Any:
        resp = await call_next(request)
        if "text/html" in resp.headers.get("content-type", ""):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def ctrl() -> Controller:
        return app.state.controller  # type: ignore[no-any-return]

    def rec() -> Recorder:
        return app.state.recorder  # type: ignore[no-any-return]

    def status_payload() -> dict[str, Any]:
        c, rc = ctrl(), rec()
        snap = c.snapshot()
        return {
            "device": snap.pop("device"),
            "controller": snap,
            "axis_motion": app.state.axis_motion,
            "recording": {"active": rc.active is not None, "run": rc.active.name if rc.active else None},
        }

    def guarded(fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    # ---- identity / status ------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"version": __version__, "api_version": API_VERSION, "backend": app.state.backend,
                "platform": platform.platform()}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return status_payload()

    @app.get("/api/discovery")
    def discovery() -> dict[str, Any]:
        cands = [{"backend": "simulated", "ip": None, "reachable": True}]
        for name, cand_ip in (("ethernet", r.DEFAULT_IP_ETHERNET), ("usb", r.DEFAULT_IP_USB)):
            cands.append({"backend": "machinemotion", "ip": cand_ip, "label": name,
                          "reachable": _tcp_open(cand_ip, r.HTTP_PORT)})
        return {"candidates": cands, "connected": {"backend": app.state.backend}}

    # ---- connection -------------------------------------------------------------------------
    @app.post("/api/connect")
    def connect(body: ConnectBody) -> dict[str, Any]:
        if body.backend not in registered_transports():
            raise HTTPException(400, f"unknown backend {body.backend!r}; known: {registered_transports()}")
        try:
            _attach(app, body.backend, body.ip, body.heater_io)
        except Exception as exc:  # noqa: BLE001 - surface any connect failure as 503
            raise HTTPException(503, f"could not connect: {exc}") from exc
        return status_payload()

    @app.post("/api/disconnect")
    def disconnect() -> dict[str, Any]:
        rec().stop()
        ctrl().detach_device()
        app.state.backend = "none"
        return status_payload()

    @app.post("/api/arm")
    def arm() -> dict[str, Any]:
        guarded(ctrl().arm)
        rec().event("armed")
        return status_payload()

    @app.post("/api/disarm")
    def disarm() -> dict[str, Any]:
        ctrl().disarm()
        rec().event("disarmed")
        return status_payload()

    @app.post("/api/estop")
    def estop() -> dict[str, Any]:
        ctrl().estop()
        rec().event("estop")
        return {"ok": True}

    @app.post("/api/estop/release")
    def estop_release() -> dict[str, Any]:
        guarded(ctrl().estop_release)
        rec().event("estop_released")
        return status_payload()

    @app.post("/api/clear-fault")
    def clear_fault() -> dict[str, Any]:
        guarded(ctrl().clear_fault)
        return status_payload()

    # ---- motion -----------------------------------------------------------------------------
    @app.post("/api/motion/home")
    def home(body: HomeBody) -> dict[str, Any]:
        if body.axes:
            for a in body.axes:
                guarded(ctrl().home, a)
        else:
            guarded(ctrl().home_all)
        rec().event("home", {"axes": body.axes or "all"})
        return status_payload()

    @app.post("/api/motion/move")
    def move(body: MoveBody) -> dict[str, Any]:
        fn = ctrl().move_absolute if body.mode == "abs" else ctrl().move_relative
        applied = guarded(fn, body.axis, body.mm)
        rec().event("move", {"axis": body.axis, "mode": body.mode, "requested_mm": body.mm, "applied_mm": applied})
        return {"axis": body.axis, "mode": body.mode, "requested_mm": body.mm, "applied_mm": applied}

    @app.post("/api/motion/stop")
    def stop(body: StopBody) -> dict[str, Any]:
        guarded(ctrl().stop_all)
        rec().event("stop", {"axes": body.axes or "all"})
        return status_payload()

    def _bounds(axis: int) -> dict[str, Any]:
        return {"max_speed": HARD_BOUNDS["max_speed"][axis], "max_accel": HARD_BOUNDS["max_accel"][axis]}  # type: ignore[index]

    @app.get("/api/axes/{axis}/motion")
    def axis_motion(axis: int) -> dict[str, Any]:
        if axis not in (1, 2, 3, 4):
            raise HTTPException(400, "axis must be 1..4")
        return {**app.state.axis_motion[axis], "bounds": _bounds(axis),
                "limit_speed": ctrl().limits.max_speed[axis], "limit_accel": ctrl().limits.max_accel[axis]}

    @app.put("/api/axes/{axis}/motion")
    def set_axis_motion(axis: int, body: AxisMotionBody) -> dict[str, Any]:
        if axis not in (1, 2, 3, 4):
            raise HTTPException(400, "axis must be 1..4")
        if body.max_speed is not None:
            app.state.axis_motion[axis]["max_speed"] = guarded(ctrl().set_max_speed, axis, body.max_speed)
        if body.max_accel is not None:
            app.state.axis_motion[axis]["max_accel"] = guarded(ctrl().set_max_accel, axis, body.max_accel)
        return axis_motion(axis)

    # ---- limits -----------------------------------------------------------------------------
    @app.get("/api/safety-limits")
    def get_limits() -> dict[str, Any]:
        return {**ctrl().limits.to_dict(), "bounds": HARD_BOUNDS}

    @app.put("/api/safety-limits")
    def put_limits(body: LimitsBody) -> dict[str, Any]:
        current = ctrl().limits.to_dict()
        current.update({k: v for k, v in body.model_dump().items() if v is not None})
        limits = SafetyLimits.bounded(**current)
        ctrl().set_limits(limits)
        save_limits(root, limits)
        return get_limits()

    # ---- heater -----------------------------------------------------------------------------
    @app.post("/api/heater/on")
    def heater_on() -> dict[str, Any]:
        guarded(ctrl().heater_on)
        rec().event("heater_on")
        return status_payload()

    @app.post("/api/heater/off")
    def heater_off() -> dict[str, Any]:
        ctrl().heater_off()
        rec().event("heater_off")
        return status_payload()

    # ---- recording --------------------------------------------------------------------------
    @app.post("/api/recording/start")
    def recording_start(body: RecordingStartBody) -> dict[str, Any]:
        if rec().active is not None:
            raise HTTPException(409, "already recording")
        run = rec().start(body.name, notes=body.notes, metadata={
            "backend": app.state.backend, "device": ctrl().snapshot()["device"],
            "limits": ctrl().limits.to_dict()})
        return {"run": run.name}

    @app.post("/api/recording/stop")
    def recording_stop() -> dict[str, Any]:
        run = rec().stop()
        return {"run": run.name if run else None, "stopped": run is not None}

    @app.get("/api/recording/status")
    def recording_status() -> dict[str, Any]:
        return status_payload()["recording"]

    @app.get("/api/recordings")
    def recordings() -> dict[str, Any]:
        return {"runs": rec().list_runs()}

    @app.get("/api/recordings/{run}/{name}")
    def recording_file(run: str, name: str) -> FileResponse:
        if name not in ("telemetry.csv", "events.json", "metadata.json", "manifest.json", "layers.csv"):
            raise HTTPException(404, "unknown file")
        target = (root / run / name).resolve()
        if target.parent.parent != root.resolve() or not target.exists():
            raise HTTPException(400, "bad run")
        return FileResponse(target)

    # ---- websocket --------------------------------------------------------------------------
    @app.websocket("/ws/telemetry")
    async def ws_telemetry(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                await ws.send_json(status_payload())
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            return

    dist = frontend_dist or _DEFAULT_FRONTEND_DIST
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


def _attach(app: FastAPI, backend: str, ip: str | None, heater_io: tuple[int, int] | None) -> None:
    kwargs: dict[str, Any] = {}
    if backend == "machinemotion":
        kwargs["ip"] = ip or r.DEFAULT_IP_ETHERNET
    transport = create_transport(backend, **kwargs)
    device = PrinterDevice(transport, heater_io=heater_io)
    app.state.controller.attach_device(device, backend=backend)
    app.state.backend = backend
    for n in (1, 2, 3, 4):
        app.state.axis_motion[n] = {"max_speed": None, "max_accel": None}


__all__ = ["create_app", "install_cross_origin_policy", "API_VERSION"]
```
Note `_DEFAULT_FRONTEND_DIST`: `api/app.py` → parents[0]=api, [1]=package, [2]=backend, [3]=repo root → `repo/frontend/dist`. Verify with a quick print if unsure.

- [ ] **Step 4: Run** `uv run pytest -q` → all pass; ruff + mypy clean. The estop test waits 3.2 s — acceptable.
- [ ] **Step 5: Commit** `git commit -am "feat(api): FastAPI operator with status/ws, connect, arm, motion, heater, limits, recording"`

---

### Task 13: `vpi-serve`

**Files:** Create `api/server.py`.

- [ ] **Step 1: Implement** (verified by running, not unit-tested — CLI glue):
```python
"""vpi-serve: run the operator (API + built UI) on 127.0.0.1:8020 (8000 = FLIR, 8010 = T&C)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from vention_printer_interface.api.app import create_app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-serve", description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--backend", choices=["none", "simulated", "machinemotion"], default="none",
                    help="none = boot idle and connect via the UI (default)")
    ap.add_argument("--ip", default=None, help="controller IP (implies --backend machinemotion)")
    ap.add_argument("--heater-io", default="1,0", help="IO module id,pin for the heater relay (UNVERIFIED default)")
    ap.add_argument("--poll-interval", type=float, default=0.2)
    ap.add_argument("--experiments-root", type=Path, default=None)
    ap.add_argument("--site-origin", default="https://mattlmccoy.github.io",
                    help="origin allowed to control this operator cross-origin; '' disables")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    backend = "machinemotion" if args.ip else args.backend
    dev, pin = (int(x) for x in args.heater_io.split(","))
    app = create_app(backend=backend, ip=args.ip, poll_interval_s=args.poll_interval,
                     experiments_root=args.experiments_root, site_origin=args.site_origin or None,
                     heater_io=(dev, pin))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
- [ ] **Step 2: Verify** `uv run vpi-serve --backend simulated &` then `curl -s localhost:8020/api/status | head -c 300` shows `"state":"connected"`. Kill the server.
- [ ] **Step 3: Commit** `git commit -am "feat(cli): vpi-serve"`

---

### Task 14: `vpi-probe` (read-only commissioning) and `vpi-monitor`

**Files:** Create `probe.py`, `monitor.py`; Test `tests/test_probe.py`.

- [ ] **Step 1: Failing test**
```python
import json
from pathlib import Path

from vention_printer_interface.probe import main, run_probe


def test_run_probe_simulated_is_read_only(tmp_path: Path) -> None:
    report = run_probe(backend="simulated", ip=None, samples=3, interval_s=0.0, mqtt_capture_s=0.0)
    assert report["backend"] == "simulated"
    assert report["health"]["version"] == "2.14.1"
    assert len(report["samples"]) == 3
    assert set(report["samples"][0]["positions"]) == {"1", "2", "3", "4"}
    assert "endstops" in report and "drive_configs" in report and "mqtt" in report
    assert report["writes_performed"] == []


def test_main_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "probe.json"
    assert main(["--simulated", "--samples", "1", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["samples"]
```
- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement** `probe.py`:
```python
"""vpi-probe: read-only commissioning probe — the first tool to run against the real controller.

Performs NO motion and NO writes: GET /health, /smartDrives/position, /smartDrives/complete/*,
/smartDrives/maxSpeed|maxAcceleration/*, /smartDrives/configuration?drive=N, M119 endstops, and a
timed MQTT capture of the subscribed topics. Writes a JSON report whose samples replace the
SDK-derived fixtures (plan/notes.md "Data-contract status").
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any

from vention_printer_interface.device import create_transport
from vention_printer_interface.device.base import TransportError
from vention_printer_interface.protocol import parsers as p
from vention_printer_interface.protocol import routes as r

log = logging.getLogger(__name__)


def _try(fn: Any) -> Any:
    try:
        return fn()
    except (TransportError, p.ProtocolError) as exc:
        return {"error": str(exc)}


def run_probe(*, backend: str, ip: str | None, samples: int, interval_s: float,
              mqtt_capture_s: float) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"ip": ip or r.DEFAULT_IP_ETHERNET} if backend == "machinemotion" else {"realtime": True}
    t = create_transport(backend, **kwargs)
    report: dict[str, Any] = {"backend": backend, "ip": kwargs.get("ip"), "writes_performed": [],
                              "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        raw = t.http_get(r.HEALTH_PATH)
        h = p.parse_health(raw)
        report["health"] = {"version": ".".join(map(str, h.version)), "async_supported": h.async_supported,
                            "estop_triggered": h.estop_triggered, "raw": h.raw}
        report["drive_configs"] = {n: _try(lambda n=n: json.loads(t.http_get(r.drive_config_path(n)))) for n in (1, 2, 3, 4)}
        report["max_speed"] = {n: _try(lambda n=n: json.loads(t.http_get(r.max_speed_path(n)))) for n in (1, 2, 3, 4)}
        report["max_accel"] = {n: _try(lambda n=n: json.loads(t.http_get(r.max_accel_path(n)))) for n in (1, 2, 3, 4)}
        report["endstops"] = _try(lambda: p.parse_endstops(t.http_get(r.gcode_path(r.GCODE_ENDSTOPS)).decode()))
        report["motion_status_raw"] = _try(lambda: t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode())
        report["samples"] = []
        for _ in range(samples):
            pos_raw = t.http_get(r.POSITION_PATH)
            report["samples"].append({
                "host_timestamp_ns": time.time_ns(),
                "positions_raw": pos_raw.decode(errors="replace"),
                "positions": {str(k): v for k, v in _try(lambda: p.parse_positions(pos_raw)).items()}
                if not isinstance(_try(lambda: p.parse_positions(pos_raw)), dict) or "error" not in _try(lambda: p.parse_positions(pos_raw)) else {},
                "complete_raw": {n: _try(lambda n=n: t.http_get(r.complete_path(n)).decode()) for n in (1, 2, 3, 4)},
            })
            time.sleep(interval_s)
        end = time.monotonic() + mqtt_capture_s
        seen: dict[str, str | None] = {}
        while True:
            for topic in (r.TOPIC_ESTOP_STATUS, r.TOPIC_DRIVES_READY):
                seen[topic] = t.mqtt_latest(topic)
            for dev in range(1, 9):
                v = t.mqtt_latest(f"devices/io-expander/{dev}/available")
                if v is not None:
                    seen[f"devices/io-expander/{dev}/available"] = v
            for n in (1, 2, 3, 4):
                v = t.mqtt_latest(f"drive/{n}/motionComplete")
                if v is not None:
                    seen[f"drive/{n}/motionComplete"] = v
            if time.monotonic() >= end:
                break
            time.sleep(0.2)
        report["mqtt"] = seen
    finally:
        t.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-probe", description=__doc__)
    ap.add_argument("--ip", default=None, help="controller IP (default 192.168.0.2)")
    ap.add_argument("--simulated", action="store_true", help="probe the built-in simulator")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--mqtt-seconds", type=float, default=10.0)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    backend = "simulated" if args.simulated else "machinemotion"
    try:
        report = run_probe(backend=backend, ip=args.ip, samples=args.samples,
                           interval_s=args.interval, mqtt_capture_s=args.mqtt_seconds)
    except TransportError as exc:
        print(f"PROBE FAILED: {exc}")
        print("Check: is the Mac on 192.168.0.x (Ethernet) or 192.168.7.x (USB)? ping the controller first.")
        return 2
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
        print(f"wrote {args.output}")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
Simplify the awkward `positions` expression: compute `parsed = _try(lambda: p.parse_positions(pos_raw))` once and set `"positions": {} if "error" in parsed else {str(k): v for k, v in parsed.items()}` (do this — the plan shows intent; the engineer writes the clean form).

`monitor.py`:
```python
"""vpi-monitor: live console telemetry through the real Controller (protection active, read-only)."""

from __future__ import annotations

import argparse
import time

from vention_printer_interface.control.controller import Controller
from vention_printer_interface.device import create_transport
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.protocol import routes as r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-monitor", description=__doc__)
    ap.add_argument("--ip", default=None)
    ap.add_argument("--simulated", action="store_true")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args(argv)
    backend = "simulated" if args.simulated else "machinemotion"
    kwargs = {"ip": args.ip or r.DEFAULT_IP_ETHERNET} if backend == "machinemotion" else {}
    c = Controller(poll_interval_s=0.2)
    c.attach_device(PrinterDevice(create_transport(backend, **kwargs)), backend=backend)
    try:
        while True:
            s = c.snapshot()
            t = s["telemetry"]
            pos = " ".join(f"{k}={v:7.2f}" for k, v in (t or {}).get("positions", {}).items())
            flags = ("ESTOP " if t and t["estop_triggered"] else "") + ("" if not t or t["drives_ready"] else "NOT-READY ")
            print(f"[{s['state']}] {pos} {flags}" + (" FAULT: " + "; ".join(s["fault_reasons"]) if s["fault_reasons"] else ""))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        c.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
- [ ] **Step 4: Run** `uv run pytest -q` → all pass; `uv run vpi-probe --simulated --samples 2 --mqtt-seconds 0.5` prints a report; lint clean.
- [ ] **Step 5: Commit** `git commit -am "feat(cli): vpi-probe read-only commissioning probe and vpi-monitor"`

---

### Task 15: CI, README, docs skeleton, launch config

**Files:** Create `.github/workflows/ci.yml`, `README.md`, `docs/architecture.md`, `docs/protocol.md`, `docs/commissioning.md`, `docs/development.md`, `.claude/launch.json`, `plan/task_plan.md`.

- [ ] **Step 1: ci.yml**
```yaml
name: ci
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: uv sync --extra dev
      - run: uv run ruff check .
      - run: uv run mypy vention_printer_interface
      - run: uv run pytest -p no:warnings   # hardware tests are skipped without --hardware
```
- [ ] **Step 2: README.md** — status table in the family shape (Piece | Location | State) listing every module from this plan with state `tested` / `tested; simulator-verified` / `UNVERIFIED on hardware`; a "Scientific / engineering stance" paragraph (only the documented protocol; everything unverified until `vpi-probe`); Safety paragraph (heater like RF; ARM; E-STOP ungated); Quick start (simulator); "Talking to the real printer (read-only first)" with the exact probe command; Layout.
- [ ] **Step 3: docs/commissioning.md** — the six-step order from spec §7 with exact commands:
```bash
# 0. network: System Settings → Network → USB-Ethernet adapter → Configure IPv4 Manually, IP 192.168.0.10, mask 255.255.255.0
ping -c 3 192.168.0.2
curl -s http://192.168.0.2:8000/health | head -c 400
# 1. read-only probe (no motion)
cd backend && uv run vpi-probe --ip 192.168.0.2 --samples 5 --mqtt-seconds 10 --output ../plan/probe_report.json
# 2. reconcile: compare plan/probe_report.json against tests/test_parsers.py fixtures; update plan/notes.md
# 3. serve; ARM; home printhead gantry; jog
uv run vpi-serve --ip 192.168.0.2
# 4. heater pin: with the relay coil disconnected, POST /api/heater/on and listen; try --heater-io 1,0 .. 1,3
# 5. Plan 2: dry-run recipe; 6. full recipe
```
- [ ] **Step 4: docs/architecture.md, docs/protocol.md, docs/development.md** — copy structure from `../TC-POWER/docs/architecture.md` (ASCII flow, "three data concerns", protection-dominant layering, staged commissioning), `docs/protocol.md` = the routes table from spec §2 + "Data-contract status (unverified against our unit)", `docs/development.md` = TDD, commands, "only device/machinemotion.py opens sockets", Conventional Commits.
- [ ] **Step 5: .claude/launch.json**
```json
{"version":"0.0.1","configurations":[
 {"name":"backend","runtimeExecutable":"uv","runtimeArgs":["run","--directory","backend","vpi-serve","--backend","simulated","--port","8020"],"port":8020},
 {"name":"frontend-dev","runtimeExecutable":"npm","runtimeArgs":["--prefix","frontend","run","dev"],"port":5175}]}
```
- [ ] **Step 6: Commit** `git commit -am "docs: README, architecture, protocol, commissioning; ci workflow"`

---

## Self-review

**Spec coverage (Plan 1 scope):** §1 layout ✔ (T1, T15); §2 routes/parsers/simulator/real transport ✔ (T2–T6); §3 controller/safety/limits ✔ (T8–T10); heater watchdog ✔ (evaluate + controller `_heater_on_since`; a separate `heater.py` is unnecessary — dropped, YAGNI); §4 recorder ✔ (T11; `layers.csv` and recipe events come in Plan 2); §5 API/WS ✔ (T12) except `/api/recipe*` (Plan 2); §7 tests + hardware marker + commissioning ✔ (T14, T15). Frontend = Plan 3. `deploy/` LaunchAgent deferred until the operator is proven on hardware.

**Type consistency:** `Telemetry` fields used identically in safety, controller.snapshot, recorder, and tests. `SafetyLimits.bounded(**dict)` accepts `to_dict()` output (keys match). `create_transport("machinemotion", ip=...)`, `("simulated", realtime=...)` match constructors. `Controller.snapshot()["device"]` popped into `status_payload()["device"]`.

**Placeholders:** none; the one "write the clean form" note in T14 is accompanied by the exact expression.
