import numpy as np

from vention_printer_interface.vision.frame_source import Frame, SimulatedFrameSource


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
