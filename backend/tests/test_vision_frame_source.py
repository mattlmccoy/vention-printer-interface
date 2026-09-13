from typing import Any

import cv2
import numpy as np

from vention_printer_interface.vision.frame_source import (
    Frame,
    SimulatedFrameSource,
    UvcFrameSource,
)


def test_simulated_source_grabs_configured_frame():
    src = SimulatedFrameSource(width=64, height=48)
    src.open()
    f = src.grab()
    assert isinstance(f, Frame)
    assert f.image.shape == (48, 64, 3)
    assert f.image.dtype == np.uint8
    assert f.timestamp_ns > 0
    src.close()


def test_configure_records_effective_settings():
    src = SimulatedFrameSource(width=8, height=8)
    src.open()
    src.configure(exposure=0.02, gain=1.5, focus="manual-fixed")
    f = src.grab()
    assert f.settings == {"exposure": 0.02, "gain": 1.5, "focus": "manual-fixed"}
    src.close()


def test_grab_fresh_default_returns_a_frame():
    """The base FrameSource.grab_fresh() default just delegates to grab()."""
    src = SimulatedFrameSource(width=16, height=12)
    src.open()
    f = src.grab_fresh()
    assert isinstance(f, Frame)
    assert f.image.shape == (12, 16, 3)
    src.close()


# ---- hardware-free UVC tests: a stub `cv2.VideoCapture` stands in for the driver ----------


class _StubCap:
    """Fake `cv2.VideoCapture` exposing exactly the surface `UvcFrameSource` uses.

    `get_overrides` maps a `cv2.CAP_PROP_*` id to either a fixed value or a zero-arg
    callable, so a test can simulate "actual differs from requested" or "driver raises
    on read" (an unsupported/unavailable control) without touching real hardware.
    """

    def __init__(
        self,
        get_overrides: dict[int, Any] | None = None,
        read_frames: list[np.ndarray] | None = None,
    ) -> None:
        self.set_calls: list[tuple[int, Any]] = []
        self._props: dict[int, Any] = {}
        self._get_overrides = get_overrides or {}
        self._read_frames = read_frames or [np.zeros((4, 4, 3), np.uint8)]
        self.read_count = 0
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors cv2.VideoCapture's method name
        return True

    def set(self, prop: int, value: Any) -> bool:  # noqa: A003 - mirrors cv2.VideoCapture
        self.set_calls.append((prop, value))
        self._props[prop] = value
        return True

    def get(self, prop: int) -> Any:
        override = self._get_overrides.get(prop)
        if callable(override):
            return override()
        if override is not None:
            return override
        return self._props.get(prop, 0.0)

    def read(self) -> tuple[bool, np.ndarray]:
        idx = min(self.read_count, len(self._read_frames) - 1)
        img = self._read_frames[idx]
        self.read_count += 1
        return True, img

    def release(self) -> None:
        self.released = True


def _install_stub_capture(monkeypatch, stub: _StubCap) -> None:
    monkeypatch.setattr(cv2, "VideoCapture", lambda *args, **kwargs: stub)


def test_uvc_source_open_grab_grab_fresh_close_uses_stub_capture(monkeypatch):
    """Replaces the old hasattr-only tautology: drives real open/grab/grab_fresh/close
    behavior against a stub capture object, never touching real hardware."""
    stub = _StubCap()
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=2, width=640, height=480)

    src.open()
    frame = src.grab()
    assert isinstance(frame, Frame)
    assert frame.image.shape == (4, 4, 3)

    fresh = src.grab_fresh(discard=1)
    assert isinstance(fresh, Frame)

    src.close()
    assert stub.released


def test_uvc_source_open_requests_pixel_format_size_fps_on_cap(monkeypatch):
    stub = _StubCap()
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0, width=1920, height=1080, pixel_format="MJPG", fps=30.0)

    src.open()

    requested_fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    assert (cv2.CAP_PROP_FOURCC, requested_fourcc) in stub.set_calls
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1920) in stub.set_calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 1080) in stub.set_calls
    assert (cv2.CAP_PROP_FPS, 30.0) in stub.set_calls


def test_uvc_source_open_sets_buffersize_one_for_capture_freshness(monkeypatch):
    stub = _StubCap()
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0)

    src.open()

    assert (cv2.CAP_PROP_BUFFERSIZE, 1) in stub.set_calls


def test_uvc_source_records_requested_and_actual_when_driver_differs(monkeypatch):
    actual_fourcc = float(cv2.VideoWriter_fourcc(*"YUY2"))
    stub = _StubCap(
        get_overrides={
            cv2.CAP_PROP_FRAME_WIDTH: 1280.0,
            cv2.CAP_PROP_FRAME_HEIGHT: 720.0,
            cv2.CAP_PROP_FPS: 15.0,
            cv2.CAP_PROP_FOURCC: actual_fourcc,
        }
    )
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0, width=1920, height=1080, pixel_format="MJPG", fps=30.0)

    src.open()
    frame = src.grab()

    assert frame.settings["requested"] == {
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "pixel_format": "MJPG",
    }
    assert frame.settings["actual"] == {
        "width": 1280,
        "height": 720,
        "fps": 15.0,
        "pixel_format": "YUY2",
    }


def test_uvc_source_records_available_control_value(monkeypatch):
    stub = _StubCap(get_overrides={cv2.CAP_PROP_EXPOSURE: -6.0})
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0)

    src.open()
    frame = src.grab()

    assert frame.settings["exposure"] == -6.0


def test_uvc_source_control_unavailable_is_recorded_as_none(monkeypatch):
    def _raise() -> float:
        raise RuntimeError("driver does not support this control")

    stub = _StubCap(get_overrides={cv2.CAP_PROP_GAIN: _raise})
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0)

    src.open()
    frame = src.grab()

    assert frame.settings["gain"] is None


def test_uvc_source_grab_fresh_discards_then_returns_the_next_frame(monkeypatch):
    frames = [np.full((2, 2, 3), i, np.uint8) for i in range(5)]
    stub = _StubCap(read_frames=frames)
    _install_stub_capture(monkeypatch, stub)
    src = UvcFrameSource(device_index=0)
    src.open()

    frame = src.grab_fresh(discard=2)

    assert stub.read_count == 3  # 2 discarded + 1 returned
    assert np.array_equal(frame.image, frames[2])
