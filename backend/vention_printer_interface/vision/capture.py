"""VisionService: non-blocking EventLog sink + worker thread.

`on_event` runs synchronously on the caller's (control) thread and must NEVER block:
it only classifies the label and enqueues a `CaptureRequest`, dropping the oldest queued
request when full. All camera I/O (grab, register, write) happens on a background worker
thread, off the control path entirely.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vention_printer_interface.vision.events import CaptureRequest, label_to_stage
from vention_printer_interface.vision.frame_source import FrameSource
from vention_printer_interface.vision.registration import Calibration, register_frame
from vention_printer_interface.vision.store import append_manifest, write_capture

log = logging.getLogger(__name__)


class VisionService:
    def __init__(
        self,
        source: FrameSource,
        run_dir_provider: Callable[[], Path | None],
        calibration: Calibration | None = None,
        camera_role: str | None = None,
        queue_max: int = 16,
    ) -> None:
        self._source = source
        self._run_dir_provider = run_dir_provider
        self._calibration = calibration
        self._camera_role = camera_role
        self._q: queue.Queue[CaptureRequest] = queue.Queue(maxsize=queue_max)
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self.drops = 0

    # ---- the EventLog sink: enqueue and return, nothing else -----------------------------
    def on_event(self, label: str, data: dict[str, Any]) -> None:
        stage = label_to_stage(label)
        if stage is None:
            return
        req = CaptureRequest(
            layer=int(data.get("layer", 0)),
            stage=stage,
            host_timestamp_ns=int(data.get("host_timestamp_ns", 0)),
            axis_positions_mm=dict(data.get("axis_positions_mm", {})),
            job=dict(data.get("job", {})),
        )
        try:
            self._q.put_nowait(req)
        except queue.Full:
            try:  # drop oldest, enqueue newest
                self._q.get_nowait()
                self.drops += 1
                self._q.put_nowait(req)
            except queue.Empty:
                self.drops += 1

    def start(self) -> None:
        self._source.open()
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None
        self._source.close()

    def drain(self, timeout: float = 2.0) -> None:
        """Test/util: block until the queue is empty and the worker is idle."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self._q.empty() and self._idle.is_set():
                return
            time.sleep(0.01)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                req = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._idle.clear()
            try:
                self._process(req)
            except Exception as exc:  # noqa: BLE001 - a capture failure must never crash the worker
                log.warning("vision capture failed (layer %s %s): %s", req.layer, req.stage, exc)
            finally:
                self._idle.set()

    def _process(self, req: CaptureRequest) -> None:
        base = self._run_dir_provider()
        if base is None:
            log.debug("no active run dir; dropping capture layer %s %s", req.layer, req.stage)
            return

        frame = self._source.grab_fresh()
        registered, registered_space = register_frame(frame.image, self._calibration)

        meta: dict[str, Any] = {
            "run_id": Path(base).name,
            "host_timestamp_ns": req.host_timestamp_ns or frame.timestamp_ns,
            "frame_timestamp_ns": frame.timestamp_ns,
            "job": req.job,
            "axis_positions_mm": req.axis_positions_mm,
            "camera": {
                "role": self._camera_role,
                "model": None,
                "asin": None,
                "device_id": None,
                "device_index": None,
            },
            "capture": {
                "requested": frame.settings.get("requested"),
                "actual": frame.settings.get("actual"),
            },
            "controls": {
                "exposure": frame.settings.get("exposure"),
                "gain": frame.settings.get("gain"),
                "white_balance": frame.settings.get("white_balance"),
                "auto_exposure": frame.settings.get("auto_exposure"),
                "auto_white_balance": frame.settings.get("auto_white_balance"),
            },
            "lens_notes": None,
            "calibration": self._calibration_meta(),
            "registered_space": registered_space,
        }

        paths = write_capture(
            Path(base),
            layer=req.layer,
            stage=req.stage,
            raw=frame.image,
            registered=registered,
            meta=meta,
        )

        registered_rel = Path(paths["registered"]).relative_to(Path(base)).as_posix()
        append_manifest(
            Path(base),
            {
                "run_id": meta["run_id"],
                "layer": req.layer,
                "stage": req.stage,
                "registered": registered_rel,
                "host_timestamp_ns": meta["host_timestamp_ns"],
            },
        )

    def _calibration_meta(self) -> dict[str, Any] | None:
        calibration = self._calibration
        if calibration is None:
            return None
        return {
            "version": calibration.version,
            "image_size": None,
            "camera_matrix": None,
            "distortion_model": None,
            "distortion_coeffs": None,
            "bed_homography": calibration.H.tolist(),
            "validation": None,
        }
