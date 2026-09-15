"""Fixtures here are SDK-DERIVED (shapes read from MachineMotion.py), not captured from our unit.

Replace with plan/probe_report.json samples once vpi-probe has run (data-contract rule).
"""

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


def test_parse_positions_rejects_missing_axis() -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_positions(b'{"X": 1}')


def test_parse_actual_speed_reads_numeric_axes() -> None:
    # /smartDrives/get/actualSpeed -> {"actual speed": {"1": v, ...}} keyed by axis NUMBER (mm/s),
    # unlike position which is keyed X/Y/Z/W. (MachineMotion.py:1531-1537)
    raw = json.dumps({"actual speed": {"1": 2.5, "2": 0.0, "3": 100.0, "4": 12.5}}).encode()
    assert p.parse_actual_speed(raw) == {1: 2.5, 2: 0.0, 3: 100.0, 4: 12.5}


def test_parse_actual_speed_rejects_error_and_malformed() -> None:
    with pytest.raises(p.ProtocolError):
        p.parse_actual_speed(b"Error in gCode execution")
    with pytest.raises(p.ProtocolError):
        p.parse_actual_speed(b'{"speed": {"1": 1}}')  # missing "actual speed" key


def test_parse_complete() -> None:
    assert p.parse_complete(b'{"complete": true}') is True  # :1798-1799
    assert p.parse_complete(b'{"complete": false}') is False
    with pytest.raises(p.ProtocolError):
        p.parse_complete(b'{"complete": "yes"}')


def test_parse_motion_status() -> None:
    assert p.parse_motion_status("echo:V0\nMotion Status = COMPLETED\nok") is True  # :1787
    assert p.parse_motion_status("echo:V0\nMotion Status = IN_PROGRESS\nok") is False


def test_parse_health_version() -> None:
    raw = json.dumps(
        {
            "mqtt_services_running": {"services/mm-vention-control/version": "2.14.1"},
            "estop_triggered": False,
            "motion_controller_reachable": True,
        }
    ).encode()
    h = p.parse_health(raw)
    assert h.version == (2, 14, 1)  # :1420-1441
    assert h.estop_triggered is False
    assert h.motion_controller_reachable is True
    assert h.async_supported is True  # :1443-1455 (>= 2.4)


def test_parse_health_without_version_is_zero() -> None:
    h = p.parse_health(b"{}")
    assert h.version == (0, 0, 0)
    assert h.async_supported is False
    assert h.estop_triggered is None


def test_parse_json_bool() -> None:
    assert p.parse_json_bool(b"true") is True
    assert p.parse_json_bool("false") is False
    with pytest.raises(p.ProtocolError):
        p.parse_json_bool(b"maybe")


def test_parse_endstops() -> None:
    reply = (
        "echo:M119\nx_min: open\nx_max: TRIGGERED\ny_min: open\ny_max: open\n"
        "z_min: open\nz_max: open\nw_min: open\nw_max: open\nok\n"
    )
    states = p.parse_endstops(reply)  # :1229-1260
    assert states["x_max"] == "TRIGGERED"
    assert states["w_min"] == "open"
    with pytest.raises(p.ProtocolError):
        p.parse_endstops("echo:M119\nok\n")
