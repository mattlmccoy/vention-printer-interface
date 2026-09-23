"""UVC camera controls, independent of the transport (pure; unit-tested on captured data).

Reads each control's real range / factory default / current value straight from the camera
(GET_MIN/MAX/RES/DEF/CUR), sets one control, and resets every control to the camera's own
factory default (GET_DEF). Selectors and bmControls bit positions are UVC 1.5 (tables 4-3 / 4-5
and A-10 / A-11). The transport (``uvc_macos.MacUvcDevice``) supplies ``get`` and ``set_cur``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

GET_CUR, GET_MIN, GET_MAX, GET_RES, GET_DEF = 0x81, 0x82, 0x83, 0x84, 0x87
AE_MANUAL = 1  # CT_AE_MODE bitmap: 1 manual, 2 auto, 4 shutter priority, 8 aperture priority

Kind = Literal["range", "bool", "menu"]


class UvcError(RuntimeError):
    """A control request failed on the device (e.g. a STALL for an unsupported request)."""


class UvcIO(Protocol):
    def get(self, request: int, selector: int, unit: int, interface: int, length: int) -> bytes: ...

    def set_cur(self, selector: int, unit: int, interface: int, payload: bytes) -> None: ...


@dataclass(frozen=True)
class ControlSpec:
    key: str
    label: str
    unit: Literal["CT", "PU"]
    bit: int  # bmControls bit that advertises the control
    selector: int
    size: int
    kind: Kind = "range"
    signed: bool = False
    auto_key: str | None = None  # the auto-mode control that must be off for a manual value
    options: tuple[tuple[int, str], ...] = ()


# Display order. Only controls the camera advertises AND answers are shown.
CONTROLS: tuple[ControlSpec, ...] = (
    ControlSpec("exposure_auto", "auto exposure", "CT", 1, 0x02, 1, "bool"),
    ControlSpec("exposure", "exposure", "CT", 3, 0x04, 4, auto_key="exposure_auto"),
    ControlSpec("gain", "gain", "PU", 9, 0x04, 2),
    ControlSpec("brightness", "brightness", "PU", 0, 0x02, 2, signed=True),
    ControlSpec("contrast", "contrast", "PU", 1, 0x03, 2),
    ControlSpec("saturation", "saturation", "PU", 3, 0x07, 2),
    ControlSpec("hue", "hue", "PU", 2, 0x06, 2, signed=True),
    ControlSpec("sharpness", "sharpness", "PU", 4, 0x08, 2),
    ControlSpec("gamma", "gamma", "PU", 5, 0x09, 2),
    ControlSpec("white_balance_auto", "auto white balance", "PU", 12, 0x0B, 1, "bool"),
    ControlSpec("white_balance", "white balance (K)", "PU", 6, 0x0A, 2,
                auto_key="white_balance_auto"),
    ControlSpec("backlight_compensation", "backlight comp", "PU", 8, 0x01, 2),
    ControlSpec("power_line_frequency", "power line", "PU", 10, 0x05, 1, "menu",
                options=((0, "off"), (1, "50 Hz"), (2, "60 Hz"), (3, "auto"))),
    ControlSpec("focus_auto", "autofocus", "CT", 17, 0x08, 1, "bool"),
    ControlSpec("focus", "focus", "CT", 5, 0x06, 2, auto_key="focus_auto"),
    ControlSpec("zoom", "zoom", "CT", 9, 0x0B, 2),
    ControlSpec("iris", "iris", "CT", 7, 0x09, 2),
)
_BY_KEY = {c.key: c for c in CONTROLS}


@dataclass(frozen=True)
class VcTopology:
    """The VideoControl interface number and its camera terminal / processing unit
    (unit id, bmControls bitmap). None when the camera has no such unit."""

    interface: int
    camera_terminal: tuple[int, int] | None
    processing_unit: tuple[int, int] | None

    def unit(self, kind: str) -> tuple[int, int] | None:
        return self.camera_terminal if kind == "CT" else self.processing_unit


def parse_vc_topology(desc: bytes) -> VcTopology:
    """Walk a configuration descriptor and read ONLY the class-specific descriptors that belong
    to the first VideoControl interface (class 0x0E, subclass 1). Stops at the next interface:
    VideoStreaming descriptors reuse the same subtype numbers and must not be read as units."""
    interface: int | None = None
    ct: tuple[int, int] | None = None
    pu: tuple[int, int] | None = None
    p = 0
    while p + 2 < len(desc):
        length, dtype = desc[p], desc[p + 1]
        if length < 2:
            break
        if dtype == 0x04:  # INTERFACE
            if interface is not None:
                break  # left the VideoControl interface
            if desc[p + 5] == 0x0E and desc[p + 6] == 0x01:
                interface = desc[p + 2]
        elif dtype == 0x24 and interface is not None:  # CS_INTERFACE inside VideoControl
            subtype = desc[p + 2]
            if subtype == 0x02 and ct is None:  # VC_INPUT_TERMINAL (camera)
                n = desc[p + 14]
                ct = (desc[p + 3], int.from_bytes(desc[p + 15:p + 15 + n], "little"))
            elif subtype == 0x05 and pu is None:  # VC_PROCESSING_UNIT
                n = desc[p + 7]
                pu = (desc[p + 3], int.from_bytes(desc[p + 8:p + 8 + n], "little"))
        p += length
    if interface is None:
        raise UvcError("no UVC VideoControl interface in the configuration descriptor")
    return VcTopology(interface, ct, pu)


def _where(topo: VcTopology, spec: ControlSpec) -> int | None:
    """The unit id hosting ``spec`` if the camera advertises it, else None."""
    u = topo.unit(spec.unit)
    return u[0] if u is not None and u[1] & (1 << spec.bit) else None


def _get(io: UvcIO, topo: VcTopology, spec: ControlSpec, request: int) -> int:
    unit = _where(topo, spec)
    if unit is None:
        raise UvcError(f"{spec.key} is not advertised by this camera")
    raw = io.get(request, spec.selector, unit, topo.interface, spec.size)
    return int.from_bytes(raw, "little", signed=spec.signed)


def _put(io: UvcIO, topo: VcTopology, spec: ControlSpec, value: int) -> None:
    unit = _where(topo, spec)
    if unit is None:
        raise UvcError(f"{spec.key} is not advertised by this camera")
    io.set_cur(spec.selector, unit, topo.interface,
               int(value).to_bytes(spec.size, "little", signed=spec.signed))


def _auto_on_value(io: UvcIO, topo: VcTopology, spec: ControlSpec) -> int:
    """Raw value that switches an auto mode ON. AE mode is a bitmap: use the factory default
    when it is an auto mode, else the best auto mode the camera lists in GET_RES."""
    if spec.key != "exposure_auto":
        return 1
    default = _get(io, topo, spec, GET_DEF)
    if default != AE_MANUAL:
        return default
    modes = _get(io, topo, spec, GET_RES)
    return next((m for m in (8, 2, 4) if modes & m), AE_MANUAL)


def _read_one(io: UvcIO, topo: VcTopology, spec: ControlSpec) -> dict[str, Any]:
    cur, default = _get(io, topo, spec, GET_CUR), _get(io, topo, spec, GET_DEF)
    out: dict[str, Any] = {"key": spec.key, "label": spec.label, "kind": spec.kind,
                           "auto_key": spec.auto_key}
    if spec.kind == "bool":
        off = AE_MANUAL if spec.key == "exposure_auto" else 0
        return {**out, "value": cur != off, "default": default != off}
    lo, hi = _get(io, topo, spec, GET_MIN), _get(io, topo, spec, GET_MAX)
    if spec.kind == "menu":
        opts = [{"value": v, "label": lab} for v, lab in spec.options if lo <= v <= hi]
        return {**out, "value": cur, "default": default, "options": opts}
    step = max(_get(io, topo, spec, GET_RES), 1)
    return {**out, "value": cur, "default": default, "min": lo, "max": hi, "step": step}


def read_controls(io: UvcIO, topo: VcTopology) -> list[dict[str, Any]]:
    """Every advertised control the camera actually answers, with its real range/default/value.
    A control whose GETs fail is left out rather than shown with made-up numbers."""
    out: list[dict[str, Any]] = []
    for spec in CONTROLS:
        if _where(topo, spec) is None:
            continue
        try:
            out.append(_read_one(io, topo, spec))
        except UvcError:
            continue
    return out


def set_control(io: UvcIO, topo: VcTopology, key: str, value: Any) -> None:
    """Set one control. A manual value on a control with an auto mode (exposure, white balance,
    focus) switches that auto mode off first, as the camera ignores the value otherwise."""
    spec = _BY_KEY.get(key)
    if spec is None or _where(topo, spec) is None:
        raise ValueError(f"{key}: not a control this camera has")
    if spec.kind == "bool":
        on = bool(value)
        _put(io, topo, spec, _auto_on_value(io, topo, spec) if on else
             (AE_MANUAL if key == "exposure_auto" else 0))
        return
    v = int(value)
    lo, hi = _get(io, topo, spec, GET_MIN), _get(io, topo, spec, GET_MAX)
    if not lo <= v <= hi:
        raise ValueError(f"{key}: {v} is outside the camera's range {lo}..{hi}")
    if spec.auto_key is not None:
        auto = _BY_KEY[spec.auto_key]
        if _where(topo, auto) is not None:
            _put(io, topo, auto, AE_MANUAL if auto.key == "exposure_auto" else 0)
    _put(io, topo, spec, v)


def reset_to_defaults(io: UvcIO, topo: VcTopology) -> dict[str, Any]:
    """Restore every control to the camera's own factory default (GET_DEF). Auto modes go to
    manual first so the camera accepts the stored values, then return to their defaults.
    Every control that could not be reset is reported, never silently skipped."""
    present = [s for s in CONTROLS if _where(topo, s) is not None]
    autos = [s for s in present if s.kind == "bool"]
    values = [s for s in present if s.kind != "bool"]
    reset: list[str] = []
    failed: dict[str, str] = {}
    for s in autos:
        try:
            _put(io, topo, s, AE_MANUAL if s.key == "exposure_auto" else 0)
        except UvcError:
            pass  # reported below if its own reset fails
    for s in values + autos:
        try:
            _put(io, topo, s, _get(io, topo, s, GET_DEF))
            reset.append(s.key)
        except UvcError as exc:
            failed[s.key] = str(exc)
    # An advertised control the camera never answers (not readable) is not a reset failure.
    readable = {c["key"] for c in read_controls(io, topo)}
    failed = {k: v for k, v in failed.items() if k in readable}
    return {"reset": reset, "failed": failed}
