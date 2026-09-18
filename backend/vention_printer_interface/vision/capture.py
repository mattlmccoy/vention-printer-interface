"""VisionService: non-blocking EventLog sink + worker thread.

`on_event` runs synchronously on the caller's (control) thread and must NEVER block:
it only classifies the label and enqueues a `CaptureRequest`, dropping the oldest queued
request when full. All camera I/O (grab, register, write) happens on a background worker
thread, off the control path entirely.

Camera-on-demand (the "camera light stays on" fix): the science `FrameSource` is opened
only AROUND a capture (open -> grab_fresh -> close) on the worker thread and is never held
open while idle -- `start()` launches the worker but opens no device. `grab_once()` applies
the same open->grab->close discipline for the interactive calibration/validation grabs.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

from vention_printer_interface.vision.events import CaptureRequest, label_to_stage
from vention_printer_interface.vision.frame_source import Frame, FrameSource
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
        # Serializes device use (worker captures vs. interactive grab_once) and tracks whether
        # the source is currently open so the explicit release in stop() never double-closes.
        self._source_lock = threading.Lock()
        self._source_open = False
        self.drops = 0

    # ---- the EventLog sink: enqueue and return, nothing else -----------------------------
    def on_event(self, label: str, data: dict[str, Any]) -> None:
        stage = label_to_stage(label)
        if stage is None:
            return
        pl = data.get("print_layer")
        req = CaptureRequest(
            layer=int(data.get("layer", 0)),
            stage=stage,
            host_timestamp_ns=int(data.get("host_timestamp_ns", 0)),
            axis_positions_mm=dict(data.get("axis_positions_mm", {})),
            job=dict(data.get("job", {})),
            print_layer=int(pl) if isinstance(pl, int | float) else None,
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

    @property
    def calibration(self) -> Calibration | None:
        return self._calibration

    def set_calibration(self, calibration: Calibration | None) -> None:
        """Hot-swap the calibration used by future captures (control-thread accessor)."""
        self._calibration = calibration

    def start(self) -> None:
        # On-demand: launch the worker but do NOT open the device -- the camera stays off
        # until a capture actually needs it.
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None
        # Explicit release: close the device if a capture (or a crash) left it open.
        with self._source_lock:
            self._close_source_locked()

    def grab_once(self) -> Frame:
        """Open the device, grab one fresh frame, and close it -- for the interactive
        calibration/validation flows. Serialized with the worker via the source lock so the
        device is never opened twice; never leaves it open."""
        with self._source_lock:
            self._open_source_locked()
            try:
                return self._source.grab_fresh()
            finally:
                self._close_source_locked()

    def stream_jpeg(self, target_fps: float = 10.0) -> Generator[bytes, None, None]:
        """Live MJPEG frames from the science source for interactive alignment (the capture-pose
        calibration overlay). Holds the source open under the source lock and yields
        boundary-framed JPEG chunks until the client disconnects (the generator is closed). Because
        it holds the source lock, NO capture runs while a viewer streams — a setup/calibration
        tool; the route refuses it while a print is running."""
        from vention_printer_interface.vision.overview import encode_jpeg, mjpeg_chunk

        interval = 1.0 / target_fps if target_fps > 0 else 0.0
        with self._source_lock:
            self._open_source_locked()
            try:
                while True:
                    frame = self._source.grab_fresh()
                    yield mjpeg_chunk(encode_jpeg(frame.image))
                    if interval:
                        time.sleep(interval)
            finally:
                self._close_source_locked()

    def _open_source_locked(self) -> None:
        self._source.open()
        self._source_open = True

    def _close_source_locked(self) -> None:
        if not self._source_open:
            return
        try:
            self._source.close()
        except Exception as exc:  # noqa: BLE001 - a close failure must not crash the worker
            log.warning("vision source close failed: %s", exc)
        finally:
            self._source_open = False

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

        # Camera-on-demand: open the device only for this capture and close it immediately
        # after, so it is never held open while the worker sits idle between captures.
        with self._source_lock:
            self._open_source_locked()
            try:
                frame = self._source.grab_fresh()
                frame, stale = self._ensure_fresh(frame, req)
            finally:
                self._close_source_locked()
        registered, registered_space = register_frame(frame.image, self._calibration)

        meta: dict[str, Any] = {
            "run_id": Path(base).name,
            "host_timestamp_ns": req.host_timestamp_ns or frame.timestamp_ns,
            "frame_timestamp_ns": frame.timestamp_ns,
            "stale": stale,
            "job": req.job,
            "axis_positions_mm": req.axis_positions_mm,
            "cad_layer": req.print_layer,  # printing/CAD layer index (excludes precoats)
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
                "cad_layer": req.print_layer,
                "stage": req.stage,
                "registered": registered_rel,
                "host_timestamp_ns": meta["host_timestamp_ns"],
            },
        )

    def _ensure_fresh(self, frame: Frame, req: CaptureRequest) -> tuple[Frame, bool]:
        """Capture-freshness guard: never hand a pre-event frame to the wrong stage.

        `grab_fresh()` already flushes the driver's buffer, but a frame can still
        predate the triggering event (e.g. a slow driver, a race on the discard
        count). When the event carries a `host_timestamp_ns`, re-grab once; if the
        second frame is still older than the event, accept it (never silently drop
        the capture) but log a warning so the staleness is recorded, not hidden.

        Returns `(frame, stale)` where `stale` is True only when the frame still
        predates the event after the re-grab — the sidecar records that flag so the
        staleness is durable, not merely a log line.
        """
        if not req.host_timestamp_ns:
            return frame, False
        if frame.timestamp_ns >= req.host_timestamp_ns:
            return frame, False
        frame = self._source.grab_fresh()
        if frame.timestamp_ns < req.host_timestamp_ns:
            log.warning(
                "vision capture stale: layer %s %s frame_timestamp_ns=%s predates "
                "host_timestamp_ns=%s after re-grab",
                req.layer,
                req.stage,
                frame.timestamp_ns,
                req.host_timestamp_ns,
            )
            return frame, True
        return frame, False

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
