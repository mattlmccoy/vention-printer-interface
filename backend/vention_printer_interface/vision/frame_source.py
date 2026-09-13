"""Camera frame sources behind one interface, so hardware choice never leaks upward."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray            # HxWx3 uint8 (BGR, OpenCV convention)
    timestamp_ns: int
    settings: dict[str, Any] = field(default_factory=dict)


class FrameSource(ABC):
    @abstractmethod
    def open(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def grab(self) -> Frame: ...
    def configure(self, **settings: Any) -> None:  # optional; default no-op
        self._settings = {**getattr(self, "_settings", {}), **settings}

    def grab_fresh(self, discard: int = 2) -> Frame:
        """Grab a frame guaranteed not to be a stale, buffered one.

        Default just delegates to `grab()` — sufficient for sources with no internal
        buffering (e.g. `SimulatedFrameSource`). A UVC-backed source overrides this to
        flush its driver buffer first (see the addendum's A1 buffer-flush work).
        """
        return self.grab()


def _simulated_default_settings(width: int, height: int) -> dict[str, Any]:
    """A deterministic, realistic `{requested, actual, controls}`-shaped settings dict.

    Matches `UvcFrameSource`'s flat-key contract (`requested`/`actual`/`exposure`/
    `gain`/`white_balance`/`auto_exposure`/`auto_white_balance`) so tests exercising
    the default (unconfigured) simulated source exercise real values through the
    capture/store pipeline, not `None`.
    """
    mode = {"width": width, "height": height, "fps": 30.0, "pixel_format": "MJPG"}
    return {
        "requested": dict(mode),
        "actual": dict(mode),
        "exposure": -6.0,
        "gain": 1.0,
        "white_balance": 4600.0,
        "auto_exposure": 1.0,
        "auto_white_balance": 1.0,
    }


class SimulatedFrameSource(FrameSource):
    """Deterministic synthetic frames for tests (a gradient + a bright square)."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width, self.height = width, height
        self._settings: dict[str, Any] = {}
        self._configured = False
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def configure(self, **settings: Any) -> None:
        self._configured = True
        self._settings = {**self._settings, **settings}

    def grab(self) -> Frame:
        if not self._open:
            raise RuntimeError("source not open")
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:, :, 1] = np.linspace(0, 255, self.width, dtype=np.uint8)[None, :]
        img[self.height // 4 : self.height // 2, self.width // 4 : self.width // 2] = 255
        settings = (
            dict(self._settings)
            if self._configured
            else _simulated_default_settings(self.width, self.height)
        )
        return Frame(image=img, timestamp_ns=time.time_ns(), settings=settings)


# UVC control names read back best-effort on open(); the sidecar key each maps to.
_CONTROL_PROPS: dict[str, str] = {
    "exposure": "CAP_PROP_EXPOSURE",
    "gain": "CAP_PROP_GAIN",
    "white_balance": "CAP_PROP_WB_TEMPERATURE",
    "auto_exposure": "CAP_PROP_AUTO_EXPOSURE",
    "auto_white_balance": "CAP_PROP_AUTO_WB",
}


def _decode_fourcc(value: float) -> str | None:
    """Decode a `CAP_PROP_FOURCC` numeric readback into its 4-char code (e.g. "MJPG")."""
    code = int(value)
    if code <= 0:
        return None
    chars = [chr((code >> (8 * i)) & 0xFF) for i in range(4)]
    decoded = "".join(chars)
    return decoded if decoded.strip("\x00") else None


def _read_control(cap: Any, cv2_module: Any, prop_name: str) -> float | None:
    """Best-effort UVC control readback: `None` when the driver can't/won't report it.

    Never raises -- a missing/unsupported control must not block `open()`/`grab()`.
    """
    try:
        prop = getattr(cv2_module, prop_name)
        return float(cap.get(prop))
    except Exception:  # noqa: BLE001 - a control read must never propagate
        return None


class UvcFrameSource(FrameSource):
    """OpenCV VideoCapture over a UVC device. Real capture is verified on hardware."""

    def __init__(
        self,
        device_index: int = 0,
        width: int | None = None,
        height: int | None = None,
        backend: int | None = None,
        pixel_format: str | None = None,
        fps: float | None = None,
    ) -> None:
        self.device_index = device_index
        self.width, self.height = width, height
        self.backend = backend  # per-OS cv2.CAP_* (from cameras.default_backend())
        self.pixel_format = pixel_format  # e.g. "MJPG"/"YUY2" (mirrors CameraSpec)
        self.fps = fps
        self._settings: dict[str, Any] = {"focus": "manual-fixed"}
        self._cap: Any = None

    def open(self) -> None:
        import cv2

        cap = (
            cv2.VideoCapture(self.device_index, self.backend)
            if self.backend is not None
            else cv2.VideoCapture(self.device_index)
        )
        if self.pixel_format:
            fourcc = cv2.VideoWriter_fourcc(*self.pixel_format)  # type: ignore[attr-defined]
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            cap.set(cv2.CAP_PROP_FPS, self.fps)
        # Capture freshness: keep the driver buffer at 1 frame so grab_fresh()'s
        # discard-then-grab actually reaches the current frame, not a queued backlog.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            raise RuntimeError(f"cannot open UVC device {self.device_index}")

        requested = {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "pixel_format": self.pixel_format,
        }
        actual = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or None,
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or None,
            "fps": cap.get(cv2.CAP_PROP_FPS) or None,
            "pixel_format": _decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC)),
        }
        controls = {
            name: _read_control(cap, cv2, prop_name) for name, prop_name in _CONTROL_PROPS.items()
        }

        self._settings = {
            "requested": requested,
            "actual": actual,
            "focus": "manual-fixed",
            **controls,
        }
        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def grab(self) -> Frame:
        if self._cap is None:
            raise RuntimeError("source not open")
        ok, img = self._cap.read()
        if not ok or img is None:
            raise RuntimeError("frame grab failed")
        return Frame(image=img, timestamp_ns=time.time_ns(), settings=dict(self._settings))

    def grab_fresh(self, discard: int = 2) -> Frame:
        """Flush the driver's internal buffer, then return the next (current) frame.

        UVC drivers buffer frames; a plain `read()` can hand back a stale, pre-event
        frame that would be silently mislabeled to the wrong capture stage (see the
        spec's "Capture freshness"). Reading and discarding `discard` frames first
        drains that backlog so the frame this method returns reflects the bed *now*.
        """
        if self._cap is None:
            raise RuntimeError("source not open")
        for _ in range(discard):
            self._cap.read()
        return self.grab()
