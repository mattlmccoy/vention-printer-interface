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


class SimulatedFrameSource(FrameSource):
    """Deterministic synthetic frames for tests (a gradient + a bright square)."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width, self.height = width, height
        self._settings: dict[str, Any] = {}
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def configure(self, **settings: Any) -> None:
        self._settings = {**self._settings, **settings}

    def grab(self) -> Frame:
        if not self._open:
            raise RuntimeError("source not open")
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:, :, 1] = np.linspace(0, 255, self.width, dtype=np.uint8)[None, :]
        img[self.height // 4 : self.height // 2, self.width // 4 : self.width // 2] = 255
        return Frame(image=img, timestamp_ns=time.time_ns(), settings=dict(self._settings))


class UvcFrameSource(FrameSource):
    """OpenCV VideoCapture over a UVC device. Real capture is verified on hardware."""

    def __init__(
        self,
        device_index: int = 0,
        width: int | None = None,
        height: int | None = None,
        backend: int | None = None,
    ) -> None:
        self.device_index = device_index
        self.width, self.height = width, height
        self.backend = backend  # per-OS cv2.CAP_* (from cameras.default_backend())
        self._settings: dict[str, Any] = {"focus": "manual-fixed"}
        self._cap: Any = None

    def open(self) -> None:
        import cv2

        cap = (
            cv2.VideoCapture(self.device_index, self.backend)
            if self.backend is not None
            else cv2.VideoCapture(self.device_index)
        )
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open UVC device {self.device_index}")
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
