import json
import logging
import threading
import time

import numpy as np

from vention_printer_interface.vision.capture import VisionService
from vention_printer_interface.vision.events import CAPTURE_LABELS, CaptureRequest, label_to_stage
from vention_printer_interface.vision.frame_source import Frame, FrameSource, SimulatedFrameSource
from vention_printer_interface.vision.registration import Calibration
from vention_printer_interface.vision.store import read_manifest


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


def test_capture_event_appends_manifest_record(tmp_path):
    svc = _svc(tmp_path)
    svc.start()
    svc.on_event(
        "capture:post_jet",
        {"layer": 2, "host_timestamp_ns": 555, "axis_positions_mm": {"build": 0.0}},
    )
    svc.drain(timeout=2.0)
    svc.stop()

    records = read_manifest(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["layer"] == 2
    assert record["stage"] == "post_jet"
    assert record["run_id"] == tmp_path.name
    assert record["registered"] == "vision/layer_0002/post_jet.png"
    assert record["host_timestamp_ns"] == 555


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


def test_capture_sidecar_carries_real_capture_and_control_values_not_none(tmp_path):
    """With the default (unconfigured) SimulatedFrameSource, capture/actual and controls
    in the sidecar should be realistic values, not None -- I3's "exercise real values"."""
    svc = _svc(tmp_path)
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1})
    svc.drain(timeout=2.0)
    svc.stop()

    sidecar = json.loads((tmp_path / "vision" / "layer_0001" / "pre_jet.json").read_text())
    assert sidecar["capture"]["requested"] is not None
    assert sidecar["capture"]["actual"] is not None
    assert sidecar["controls"]["exposure"] is not None
    assert sidecar["controls"]["gain"] is not None


# ---- I2: worker-side capture-freshness guard (re-grab a frame that predates the event) ----


def test_worker_regrabs_once_when_first_frame_predates_the_event(tmp_path):
    """capture freshness: a frame older than the triggering event must not be accepted
    as-is -- the worker re-grabs once via grab_fresh() before writing."""

    class StaleThenFresh(FrameSource):
        def __init__(self):
            self.calls = 0

        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            self.calls += 1
            ts = 100 if self.calls == 1 else 5_000_000_000
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=ts)

    source = StaleThenFresh()
    svc = _svc(tmp_path, source=source)
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1, "host_timestamp_ns": 1_000_000_000})
    svc.drain(timeout=2.0)
    svc.stop()

    assert source.calls == 2  # the first grab predated the event -> exactly one re-grab
    sidecar = json.loads((tmp_path / "vision" / "layer_0001" / "pre_jet.json").read_text())
    assert sidecar["frame_timestamp_ns"] == 5_000_000_000


def test_worker_does_not_regrab_when_first_frame_is_already_fresh(tmp_path):
    class CountingFresh(FrameSource):
        def __init__(self):
            self.calls = 0

        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            self.calls += 1
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=5_000_000_000)

    source = CountingFresh()
    svc = _svc(tmp_path, source=source)
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1, "host_timestamp_ns": 1_000_000_000})
    svc.drain(timeout=2.0)
    svc.stop()

    assert source.calls == 1  # frame was already newer than the event -> no re-grab


def test_worker_logs_warning_when_still_stale_after_regrab(tmp_path, caplog):
    class AlwaysStale(FrameSource):
        def __init__(self):
            self.calls = 0

        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            self.calls += 1
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=100)

    source = AlwaysStale()
    svc = _svc(tmp_path, source=source)
    svc.start()
    with caplog.at_level(logging.WARNING, logger="vention_printer_interface.vision.capture"):
        svc.on_event("capture:pre_jet", {"layer": 1, "host_timestamp_ns": 1_000_000_000})
        svc.drain(timeout=2.0)
    svc.stop()

    assert source.calls == 2  # re-grabbed once, still older than the event
    assert any("stale" in record.message.lower() for record in caplog.records)
    # the capture must still be written -- staleness is recorded, never silently dropped
    assert (tmp_path / "vision" / "layer_0001" / "pre_jet.png").exists()


def test_worker_skips_staleness_check_when_event_has_no_host_timestamp(tmp_path):
    class CountingFresh(FrameSource):
        def __init__(self):
            self.calls = 0

        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            self.calls += 1
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=1)

    source = CountingFresh()
    svc = _svc(tmp_path, source=source)
    svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1})  # no host_timestamp_ns
    svc.drain(timeout=2.0)
    svc.stop()

    assert source.calls == 1  # nothing to compare against -> no re-grab


# ---- M4: bounded queue drops the oldest request, never blocks the sink -------------------


def test_set_calibration_updates_calibration_property(tmp_path):
    svc = _svc(tmp_path)
    assert svc.calibration is None
    new_calib = Calibration(
        H=np.eye(3),
        mm_per_px=1.0,
        bed_extent_mm=(0.0, 0.0, 5.0, 5.0),
        version="cal-x",
        reprojection_error=0.0,
    )
    svc.set_calibration(new_calib)
    assert svc.calibration is new_calib


def test_set_calibration_used_by_subsequent_capture(tmp_path):
    svc = _svc(tmp_path)
    svc.start()
    new_calib = Calibration(
        H=np.eye(3),
        mm_per_px=1.0,
        bed_extent_mm=(0.0, 0.0, 5.0, 5.0),
        version="cal-x",
        reprojection_error=0.0,
    )
    svc.set_calibration(new_calib)
    svc.on_event("capture:pre_jet", {"layer": 1})
    svc.drain(timeout=2.0)
    svc.stop()

    sidecar = json.loads((tmp_path / "vision" / "layer_0001" / "pre_jet.json").read_text())
    assert sidecar["calibration"]["version"] == "cal-x"


def test_queue_full_drops_oldest_request_and_increments_drops(tmp_path):
    block = threading.Event()

    class Blocking(FrameSource):
        def __init__(self):
            self.entered = threading.Event()

        def open(self):
            pass

        def close(self):
            pass

        def grab(self):
            raise AssertionError("worker must call grab_fresh(), not grab()")

        def grab_fresh(self, discard: int = 2) -> Frame:
            self.entered.set()
            block.wait(timeout=5.0)
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=time.time_ns())

    source = Blocking()
    svc = VisionService(
        source=source, run_dir_provider=lambda: tmp_path, calibration=None, queue_max=2
    )
    svc.start()
    try:
        svc.on_event("capture:pre_jet", {"layer": 1})
        assert source.entered.wait(timeout=2.0), "worker never entered grab_fresh"

        # worker is now stuck processing layer 1; these three fill (and overflow) queue_max=2
        svc.on_event("capture:pre_jet", {"layer": 2})
        svc.on_event("capture:post_jet", {"layer": 3})
        svc.on_event("capture:post_heat", {"layer": 4})  # queue full -> drops layer 2

        assert svc.drops == 1
    finally:
        block.set()
        svc.drain(timeout=2.0)
        svc.stop()

    assert (tmp_path / "vision" / "layer_0001").exists()
    assert not (tmp_path / "vision" / "layer_0002").exists()  # dropped, never written
    assert (tmp_path / "vision" / "layer_0003").exists()
    assert (tmp_path / "vision" / "layer_0004").exists()
