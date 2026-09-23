"""Which cameras can the operator drive over UVC, and how to open one (macOS).

A camera is listed when it is both an AVFoundation camera (so it has the same stable unique id
the rest of the console uses: science binding, ignore list) AND a USB device -- on macOS the
AVFoundation unique id of a UVC camera is ``0x{locationID}{VID}{PID}``, which is how the two are
joined. Built-in and Continuity cameras have no USB device and are left out.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from vention_printer_interface.vision.avfoundation import list_avf_cameras
from vention_printer_interface.vision.uvc_macos import MacUvcDevice, UvcTransportError
from vention_printer_interface.vision.uvc_macos import list_cameras as list_usb


class UvcDeviceIO(Protocol):
    def config_descriptor(self) -> bytes: ...

    def get(self, request: int, selector: int, unit: int, interface: int, length: int) -> bytes: ...

    def set_cur(self, selector: int, unit: int, interface: int, payload: bytes) -> None: ...


class UvcBackend(Protocol):
    def cameras(self) -> list[dict[str, str]]: ...

    def open(self, unique_id: str) -> Any: ...  # context manager yielding a UvcDeviceIO


class MacUvcBackend:
    def _usb(self) -> dict[str, int]:
        return {c.avf_unique_id: c.location_id for c in list_usb()}

    def cameras(self) -> list[dict[str, str]]:
        usb = self._usb()
        return [{"unique_id": c.unique_id, "name": c.name}
                for c in list_avf_cameras() if c.unique_id in usb]

    @contextmanager
    def open(self, unique_id: str) -> Iterator[MacUvcDevice]:
        loc = self._usb().get(unique_id)
        if loc is None:
            raise KeyError(unique_id)
        dev = MacUvcDevice(loc)
        try:
            yield dev
        finally:
            dev.close()


__all__ = ["MacUvcBackend", "UvcBackend", "UvcDeviceIO", "UvcTransportError"]
