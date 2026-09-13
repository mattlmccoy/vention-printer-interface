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


def test_uvc_source_constructs_without_opening_hardware():
    src = UvcFrameSource(device_index=2)
    assert src.device_index == 2
    assert hasattr(src, "open") and hasattr(src, "grab") and hasattr(src, "close")


def test_grab_fresh_default_returns_a_frame():
    """The base FrameSource.grab_fresh() default just delegates to grab()."""
    src = SimulatedFrameSource(width=16, height=12)
    src.open()
    f = src.grab_fresh()
    assert isinstance(f, Frame)
    assert f.image.shape == (12, 16, 3)
    src.close()
