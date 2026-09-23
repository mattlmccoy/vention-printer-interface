"""UVC control logic (vision/uvc.py) against data CAPTURED from the real ELP 20MP U3 cameras.

Fixtures (tests/fixtures/uvc/) were read on 2026-09-23 through vision/uvc_macos.py with GET-only
requests: the raw configuration descriptor of each camera, and MIN/MAX/RES/INFO/DEF/CUR for every
selector the capture script tried. The capture script's naive parser also walked descriptors
AFTER the VideoControl interface, so the controls file contains bogus units (PU3..PU16) that all
STALL -- the real parser must never use them.
"""

import json
from pathlib import Path

import pytest

from vention_printer_interface.vision.uvc import (
    UvcError,
    parse_vc_topology,
    read_controls,
    reset_to_defaults,
    set_control,
)

FIX = Path(__file__).parent / "fixtures" / "uvc"
UID = "0x23100032e42020"


class FakeCamera:
    """Answers GETs from the captured values; a SET updates CUR (like the device)."""

    def __init__(self, uid: str = UID) -> None:
        cap = json.loads((FIX / "elp_20mp_controls.json").read_text())[uid]
        self.iface = cap["vc_interface"]
        self.vals: dict[tuple[int, int], dict[str, str]] = {}
        for key, vals in cap["controls"].items():
            unit = int(key.split(".")[0][2:])
            sel = int(key.split("sel")[1], 16)
            self.vals.setdefault((unit, sel), vals)
        self.sets: list[tuple[int, int, bytes]] = []
        self.reject_sets: set[tuple[int, int]] = set()

    def get(self, request: int, selector: int, unit: int, interface: int, length: int) -> bytes:
        assert interface == self.iface
        name = {0x81: "CUR", 0x82: "MIN", 0x83: "MAX", 0x84: "RES", 0x86: "INFO", 0x87: "DEF"}
        v = self.vals.get((unit, selector), {}).get(name[request], "ERR stall")
        if v.startswith("ERR"):
            raise UvcError(v)
        raw = bytes.fromhex(v)
        assert len(raw) == length, (unit, selector, length)
        return raw

    def set_cur(self, selector: int, unit: int, interface: int, payload: bytes) -> None:
        if (unit, selector) in self.reject_sets:
            raise UvcError("stall")
        self.sets.append((unit, selector, payload))
        self.vals[(unit, selector)] = {**self.vals[(unit, selector)], "CUR": payload.hex()}


def _topo():  # type: ignore[no-untyped-def]
    return parse_vc_topology(bytes.fromhex((FIX / f"elp_20mp_{UID}.desc.hex").read_text()))


def _by_key(cam: FakeCamera) -> dict[str, dict]:  # type: ignore[type-arg]
    return {c["key"]: c for c in read_controls(cam, _topo())}


def test_topology_is_only_the_videocontrol_units() -> None:
    t = _topo()
    assert t.interface == 0
    assert t.camera_terminal == (1, 0x262A7E)
    assert t.processing_unit == (2, 0x177F)


def test_reads_the_real_ranges_defaults_and_current_values() -> None:
    c = _by_key(FakeCamera())
    def rng(k: str) -> tuple[int, int, int]:
        return (c[k]["min"], c[k]["max"], c[k]["default"])

    assert rng("brightness") == (0, 255, 128)
    assert rng("contrast") == (0, 128, 65)
    assert rng("hue") == (-128, 128, 0)  # signed
    assert rng("white_balance") == (2800, 6500, 4650)
    assert c["white_balance"]["auto_key"] == "white_balance_auto"
    ex = c["exposure"]
    assert (ex["min"], ex["max"], ex["default"], ex["value"]) == (1, 10000, 156, 156)
    assert ex["auto_key"] == "exposure_auto"
    assert c["exposure_auto"]["value"] is True and c["exposure_auto"]["default"] is True  # mode 8
    assert c["focus_auto"]["value"] is True
    assert c["power_line_frequency"]["value"] == 1 and c["power_line_frequency"]["kind"] == "menu"
    assert [o["label"] for o in c["power_line_frequency"]["options"]] == ["50 Hz", "60 Hz"]


def test_controls_the_device_does_not_answer_are_left_out() -> None:
    keys = set(_by_key(FakeCamera()))
    assert "iris" not in keys and "pan_tilt" not in keys
    assert keys >= {"brightness", "contrast", "saturation", "sharpness", "gamma", "gain",
                    "backlight_compensation", "exposure", "focus", "zoom"}


def test_setting_a_manual_exposure_turns_auto_exposure_off_first() -> None:
    cam = FakeCamera()
    set_control(cam, _topo(), "exposure", 400)
    assert cam.sets == [(1, 0x02, bytes([1])), (1, 0x04, (400).to_bytes(4, "little"))]


def test_set_rejects_values_outside_the_device_range() -> None:
    with pytest.raises(ValueError, match="brightness"):
        set_control(FakeCamera(), _topo(), "brightness", 300)


def test_setting_a_signed_control_encodes_twos_complement() -> None:
    cam = FakeCamera()
    set_control(cam, _topo(), "hue", -20)
    assert cam.sets == [(2, 0x06, (-20).to_bytes(2, "little", signed=True))]


def test_reset_restores_every_factory_default_values_before_auto_modes() -> None:
    cam = FakeCamera()
    topo = _topo()
    set_control(cam, topo, "brightness", 40)
    set_control(cam, topo, "exposure", 900)  # also flips auto exposure off
    set_control(cam, topo, "power_line_frequency", 2)
    cam.sets.clear()
    result = reset_to_defaults(cam, topo)
    c = _by_key(cam)
    assert c["brightness"]["value"] == 128 and c["exposure"]["value"] == 156
    assert c["exposure_auto"]["value"] is True and c["power_line_frequency"]["value"] == 1
    assert result["failed"] == {}
    # auto modes go manual first (so the camera accepts the values), values are restored, and
    # only THEN do the auto modes return to their defaults
    order = [(u, s) for u, s, _ in cam.sets]
    last_ae = len(order) - 1 - order[::-1].index((1, 0x02))
    assert order.index((1, 0x02)) < order.index((1, 0x04)) < last_ae


def test_reset_reports_a_control_the_camera_refuses_instead_of_hiding_it() -> None:
    cam = FakeCamera()
    cam.reject_sets.add((2, 0x08))  # sharpness
    result = reset_to_defaults(cam, _topo())
    assert "sharpness" in result["failed"]
    assert "brightness" in result["reset"]
