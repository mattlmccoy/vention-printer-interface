import json
import time

import numpy as np

from vention_printer_interface.vision.capture import VisionService
from vention_printer_interface.vision.events import CAPTURE_LABELS, CaptureRequest, label_to_stage
from vention_printer_interface.vision.frame_source import Frame, FrameSource, SimulatedFrameSource
from vention_printer_interface.vision.registration import Calibration


def test_capture_labels_are_the_three_stage_marks():
    assert CAPTURE_LABELS == ("capture:pre_jet", "capture:post_jet", "capture:post_heat")


def test_label_to_stage_extracts_stage_for_capture_labels():
    assert label_to_stage("capture:post_jet") == "post_jet"
    assert label_to_stage("capture:pre_jet") == "pre_jet"
    assert label_to_stage("capture:post_heat") == "post_heat"


def test_label_to_stage_returns_none_for_non_capture_labels():
    assert label_to_stage("layer_started") is None
    assert label_to_stage("capture:unknown") is None


def test_capture_request_fields():
    req = CaptureRequest(
        layer=3,
        stage="post_jet",
        host_timestamp_ns=123,
        axis_positions_mm={"build": 0.0},
        job={"id": "j1"},
    )
    assert req.layer == 3
    assert req.stage == "post_jet"
    assert req.host_timestamp_ns == 123
    assert req.axis_positions_mm == {"build": 0.0}
    assert req.job == {"id": "j1"}


def _svc(tmp_path, source=None, calibration=None, camera_role=None):
    return VisionService(
        source=source or SimulatedFrameSource(32, 24),
        run_dir_provider=lambda: tmp_path,
        calibration=calibration,  # None: registered == raw
        camera_role=camera_role,
        queue_max=8,
    )


def test_capture_event_writes_files(tmp_path):
    svc = _svc(tmp_path)
    svc.start()
    svc.on_event("capture:post_jet", {"layer": 2, "axis_positions_mm": {"build": 0.0}})
    svc.drain(timeout=2.0)
    assert (tmp_path / "vision" / "layer_0002" / "post_jet.png").exists()
    assert (tmp_path / "vision" / "layer_0002" / "post_jet.raw.png").exists()
    svc.stop()


def test_non_capture_labels_ignored(tmp_path):
    svc = _svc(tmp_path)
    svc.start()
    svc.on_event("layer_started", {"layer": 1})
    svc.drain(timeout=1.0)
    assert not (tmp_path / "vision").exists()
    svc.stop()


def test_grab_error_is_swallowed(tmp_path):
    class Boom(FrameSource):
        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise RuntimeError("camera fell off")

    svc = _svc(tmp_path, source=Boom())
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1})  # must not raise
    svc.drain(timeout=1.0)
    svc.stop()


def test_sink_is_non_blocking_even_when_source_is_slow(tmp_path):
    class Slow(FrameSource):
        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            time.sleep(1.0)
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=1)

    svc = _svc(tmp_path, source=Slow())
    svc.start()
    t0 = time.monotonic()
    svc.on_event("capture:post_heat", {"layer": 1})  # must return immediately
    dt = time.monotonic() - t0
    assert dt < 0.05, f"sink blocked for {dt:.3f}s"
    svc.stop()


def test_worker_uses_grab_fresh_not_grab(tmp_path):
    """Stage captures must never accept a stale, buffered frame (see Capture freshness)."""

    class GrabFreshOnly(FrameSource):
        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=42)

    svc = _svc(tmp_path, source=GrabFreshOnly())
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1})
    svc.drain(timeout=2.0)
    assert (tmp_path / "vision" / "layer_0001" / "pre_jet.png").exists()
    svc.stop()


def test_capture_meta_includes_expanded_fields(tmp_path):
    calib = Calibration(
        H=np.eye(3),
        mm_per_px=0.5,
        bed_extent_mm=(0.0, 0.0, 10.0, 10.0),
        version="cal-v1",
        reprojection_error=0.01,
    )
    svc = _svc(tmp_path, calibration=calib, camera_role="science")
    svc.start()
    svc.on_event(
        "capture:post_heat",
        {
            "layer": 2,
            "host_timestamp_ns": 999,
            "axis_positions_mm": {"build": 1.0},
            "job": {"id": "j9"},
        },
    )
    svc.drain(timeout=2.0)
    svc.stop()

    sidecar = json.loads((tmp_path / "vision" / "layer_0002" / "post_heat.json").read_text())
    assert sidecar["layer"] == 2
    assert sidecar["stage"] == "post_heat"
    assert sidecar["host_timestamp_ns"] == 999
    assert sidecar["frame_timestamp_ns"] > 0
    assert sidecar["axis_positions_mm"] == {"build": 1.0}
    assert sidecar["job"] == {"id": "j9"}
    assert sidecar["camera"]["role"] == "science"
    assert sidecar["camera"]["model"] is None
    assert sidecar["calibration"]["version"] == "cal-v1"
    assert sidecar["registered_space"] == {
        "mm_per_px": 0.5,
        "bed_extent_mm": [0.0, 0.0, 10.0, 10.0],
    }
