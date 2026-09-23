"""macOS transport for UVC camera controls, via IOKit's USB device interface (ctypes).

Why: Chrome/Safari on macOS expose almost none of a UVC camera's controls to getUserMedia
(no exposure, brightness, white balance...), so the browser settings panel is empty on the Mac.
libusb can't help either -- macOS's UVC driver holds the device, so libusb control transfers fail
with "Access denied" for a normal user (probed 2026-09-23). IOKit's IOUSBDeviceInterface
DeviceRequest DOES work unprivileged, without opening the device (probed on both ELP 20MP U3
cameras: brightness MIN 0 / MAX 255 / DEF 128 / CUR 128). That is what this module wraps.

This file is only the byte transport: enumerate devices, read the configuration descriptor, issue
one class request. Parsing and control semantics live in ``uvc.py`` (pure, unit-tested).

The vtable slot indexes and UUIDs below were printed by the compiler from the macOS SDK headers
(offsetof(IOUSBDeviceInterface, ...) / sizeof(void*)), not counted by hand.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# IOUSBDeviceInterface vtable slots (IOUSBLib.h, via offsetof).
_QUERY_INTERFACE, _RELEASE = 1, 3
_GET_LOCATION_ID, _GET_CONFIG_DESC_PTR, _DEVICE_REQUEST = 20, 21, 26

# kIOUSBDeviceUserClientTypeID, kIOUSBDeviceInterfaceID, kIOCFPlugInInterfaceID
_UUID_USER_CLIENT = bytes.fromhex("9dc7b7809ec011d4a54f000a27052861")
_UUID_DEVICE_IFACE = bytes.fromhex("5c8187d09ef311d48b45000a27052861")
_UUID_PLUGIN = bytes.fromhex("c244e858109c11d491d40050e4c6426f")


def _hex(kr: int) -> str:
    """An IOReturn as the unsigned hex Apple documents (e.g. 0xe000404f = pipe stalled)."""
    return f"0x{kr & 0xFFFFFFFF:08x}"


class UvcTransportError(RuntimeError):
    """A UVC request failed (IOReturn != success) or the platform has no IOKit."""


@dataclass(frozen=True)
class UsbCamera:
    """One USB device: its location id (stable per port) + VID/PID. On macOS the AVFoundation
    unique id of a UVC camera is ``0x{location:x}{vid:04x}{pid:04x}``."""

    location_id: int
    vendor_id: int
    product_id: int

    @property
    def avf_unique_id(self) -> str:
        return f"0x{self.location_id:x}{self.vendor_id:04x}{self.product_id:04x}"


class _IOUSBDevRequest(ctypes.Structure):
    _fields_ = [
        ("bmRequestType", ctypes.c_uint8),
        ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("pData", ctypes.c_void_p),
        ("wLenDone", ctypes.c_uint32),
    ]


class _CFUUIDBytes(ctypes.Structure):
    _fields_ = [("b", ctypes.c_uint8 * 16)]


def available() -> bool:
    return sys.platform == "darwin"


class _Lib:
    """Lazily loaded IOKit + CoreFoundation symbols (import must succeed on Windows/Linux)."""

    def __init__(self) -> None:
        iokit_path = ctypes.util.find_library("IOKit")
        cf_path = ctypes.util.find_library("CoreFoundation")
        if not iokit_path or not cf_path:
            raise UvcTransportError("IOKit/CoreFoundation not found (macOS only)")
        self.io = ctypes.cdll.LoadLibrary(iokit_path)
        self.cf = ctypes.cdll.LoadLibrary(cf_path)
        vp, u32, i32 = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        self.io.IOServiceMatching.restype = vp
        self.io.IOServiceMatching.argtypes = [ctypes.c_char_p]
        self.io.IOServiceGetMatchingServices.argtypes = [u32, vp, ctypes.POINTER(u32)]
        self.io.IOIteratorNext.restype = u32
        self.io.IOIteratorNext.argtypes = [u32]
        self.io.IOObjectRelease.argtypes = [u32]
        self.io.IOCreatePlugInInterfaceForService.argtypes = [
            u32, vp, vp, ctypes.POINTER(vp), ctypes.POINTER(i32)]
        self.io.IORegistryEntryCreateCFProperty.restype = vp
        self.io.IORegistryEntryCreateCFProperty.argtypes = [u32, vp, vp, u32]
        self.cf.CFUUIDGetConstantUUIDWithBytes.restype = vp
        self.cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [vp] + [ctypes.c_uint8] * 16
        self.cf.CFStringCreateWithCString.restype = vp
        self.cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, u32]
        self.cf.CFNumberGetValue.restype = ctypes.c_bool
        self.cf.CFNumberGetValue.argtypes = [vp, ctypes.c_int, vp]
        self.cf.CFRelease.argtypes = [vp]

    def uuid(self, raw: bytes) -> int:
        return int(self.cf.CFUUIDGetConstantUUIDWithBytes(None, *raw))

    def int_prop(self, service: int, key: str) -> int | None:
        k = self.cf.CFStringCreateWithCString(None, key.encode(), 0x08000100)  # UTF-8
        try:
            ref = self.io.IORegistryEntryCreateCFProperty(service, k, None, 0)
        finally:
            self.cf.CFRelease(k)
        if not ref:
            return None
        out = ctypes.c_int64(0)
        ok = self.cf.CFNumberGetValue(ref, 4, ctypes.byref(out))  # kCFNumberSInt64Type
        self.cf.CFRelease(ref)
        return int(out.value) if ok else None


_lib: _Lib | None = None


def _l() -> _Lib:
    global _lib
    if _lib is None:
        _lib = _Lib()
    return _lib


def _vfunc(obj: int, slot: int, restype: object, *argtypes: object) -> Any:
    """The function in COM-style vtable slot ``slot`` of interface ``obj`` (a T** pointer)."""
    vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, *argtypes)  # type: ignore[arg-type]
    return proto(vtbl[slot])


def _services(vid: int | None = None, pid: int | None = None) -> list[tuple[int, UsbCamera]]:
    lib = _l()
    match = lib.io.IOServiceMatching(b"IOUSBDevice")
    it = ctypes.c_uint32(0)
    if lib.io.IOServiceGetMatchingServices(0, match, ctypes.byref(it)) != 0:
        raise UvcTransportError("IOServiceGetMatchingServices failed")
    out: list[tuple[int, UsbCamera]] = []
    while True:
        svc = lib.io.IOIteratorNext(it.value)
        if not svc:
            break
        v, p = lib.int_prop(svc, "idVendor"), lib.int_prop(svc, "idProduct")
        loc = lib.int_prop(svc, "locationID")
        if v is None or p is None or loc is None or (vid, pid) not in ((None, None), (v, p)):
            lib.io.IOObjectRelease(svc)
            continue
        out.append((svc, UsbCamera(loc, v, p)))
    lib.io.IOObjectRelease(it.value)
    return out


class _Device:
    """An IOUSBDeviceInterface for one service; released on close."""

    def __init__(self, service: int) -> None:
        lib = _l()
        plug = ctypes.c_void_p(0)
        score = ctypes.c_int32(0)
        kr = lib.io.IOCreatePlugInInterfaceForService(
            service, lib.uuid(_UUID_USER_CLIENT), lib.uuid(_UUID_PLUGIN),
            ctypes.byref(plug), ctypes.byref(score))
        if kr != 0 or not plug.value:
            raise UvcTransportError(f"IOCreatePlugInInterfaceForService failed ({_hex(kr)})")
        dev = ctypes.c_void_p(0)
        want = _CFUUIDBytes()
        ctypes.memmove(want.b, _UUID_DEVICE_IFACE, 16)
        qi = _vfunc(plug.value, _QUERY_INTERFACE, ctypes.c_int32, _CFUUIDBytes,
                    ctypes.POINTER(ctypes.c_void_p))
        hr = qi(plug.value, want, ctypes.byref(dev))
        _vfunc(plug.value, _RELEASE, ctypes.c_uint32)(plug.value)
        if hr != 0 or not dev.value:
            raise UvcTransportError(f"QueryInterface(IOUSBDeviceInterface) failed ({hr})")
        self._d = dev.value

    def config_descriptor(self) -> bytes:
        ptr = ctypes.c_void_p(0)
        f = _vfunc(self._d, _GET_CONFIG_DESC_PTR, ctypes.c_int32, ctypes.c_uint8,
                   ctypes.POINTER(ctypes.c_void_p))
        kr = f(self._d, 0, ctypes.byref(ptr))
        if kr != 0 or not ptr.value:
            raise UvcTransportError(f"GetConfigurationDescriptorPtr failed ({_hex(kr)})")
        head = ctypes.string_at(ptr.value, 4)
        total = head[2] | head[3] << 8  # wTotalLength
        return ctypes.string_at(ptr.value, total)

    def request(self, bm_type: int, b_request: int, w_value: int, w_index: int,
                data: bytes | int) -> bytes:
        """One control request. ``data`` is the payload for OUT (SET) requests, or the number of
        bytes to read for IN (GET) requests."""
        n = data if isinstance(data, int) else len(data)
        buf = ctypes.create_string_buffer(n) if isinstance(data, int) else \
            ctypes.create_string_buffer(data, n)
        req = _IOUSBDevRequest(bm_type, b_request, w_value, w_index, n,
                               ctypes.cast(buf, ctypes.c_void_p), 0)
        f = _vfunc(self._d, _DEVICE_REQUEST, ctypes.c_int32, ctypes.POINTER(_IOUSBDevRequest))
        kr = f(self._d, ctypes.byref(req))
        if kr != 0:
            raise UvcTransportError(f"IOKit DeviceRequest failed ({_hex(kr)})")
        return buf.raw[: req.wLenDone]

    def close(self) -> None:
        if self._d:
            _vfunc(self._d, _RELEASE, ctypes.c_uint32)(self._d)
            self._d = 0


def list_cameras(vid: int | None = None, pid: int | None = None) -> list[UsbCamera]:
    """USB devices (optionally one VID/PID), without touching them beyond registry reads."""
    found = _services(vid, pid)
    for svc, _ in found:
        _l().io.IOObjectRelease(svc)
    return [cam for _, cam in found]


class MacUvcDevice:
    """Request/descriptor access to the USB device at ``location_id``."""

    def __init__(self, location_id: int) -> None:
        match = [(s, c) for s, c in _services() if c.location_id == location_id]
        for s, _ in match[1:]:
            _l().io.IOObjectRelease(s)
        if not match:
            raise UvcTransportError(f"no USB device at location 0x{location_id:x}")
        svc, self.camera = match[0]
        try:
            self._dev = _Device(svc)
        finally:
            _l().io.IOObjectRelease(svc)

    def config_descriptor(self) -> bytes:
        return self._dev.config_descriptor()

    def get(self, request: int, selector: int, unit: int, interface: int, length: int) -> bytes:
        return self._dev.request(0xA1, request, selector << 8, (unit << 8) | interface, length)

    def set_cur(self, selector: int, unit: int, interface: int, payload: bytes) -> None:
        self._dev.request(0x21, 0x01, selector << 8, (unit << 8) | interface, payload)

    def close(self) -> None:
        self._dev.close()

    def __enter__(self) -> MacUvcDevice:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
