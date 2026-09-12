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
