"""MJPEG encoding + single-grabber fan-out for the overview camera's live-view stream.

The overview stream is served as `multipart/x-mixed-replace`: repeated boundary-framed
JPEG chunks. `encode_jpeg`/`mjpeg_chunk` are the pure encode/frame steps. `OverviewStreamer`
owns the one background thread that actually calls `FrameSource.grab()`: any number of HTTP
clients read the latest published chunk from a shared slot via `frames()` and never call
`grab()` themselves, so concurrent clients never race on the same `cv2.VideoCapture` (see
review finding I1 -- concurrent `VideoCapture.read()` across threadpool clients is not
thread-safe).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import numpy as np

from vention_printer_interface.vision.frame_source import FrameSource

log = logging.getLogger(__name__)

_BOUNDARY = b"--frame"


def encode_jpeg(image: np.ndarray) -> bytes:
    """JPEG-encode a BGR `numpy.ndarray` frame; raises `RuntimeError` on encode failure."""
    import cv2

    ok, buf = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return bytes(buf)


def mjpeg_chunk(jpeg_bytes: bytes) -> bytes:
    """Wrap JPEG bytes in one `multipart/x-mixed-replace` boundary-framed chunk."""
    header = (
        _BOUNDARY
        + b"\r\n"
        + b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg_bytes)}\r\n\r\n".encode("ascii")
    )
    return header + jpeg_bytes + b"\r\n"


class OverviewStreamer:
    """Owns the single background grabber thread for the overview live-view stream.

    `start()` launches a daemon thread that loops `source.grab()` -> `encode_jpeg` ->
    `mjpeg_chunk`, publishing the latest chunk into a shared slot guarded by a
    `threading.Condition`. `frames()` is a per-client generator that only reads that slot
    -- it never touches `source` -- so any number of concurrent clients safely share the
    one capture. `stop()` joins the thread so no daemon thread leaks past shutdown.

    Pacing + error handling (M6): the loop sleeps to hit `target_fps` instead of busy-
    looping (important for an unpaced source such as `SimulatedFrameSource`), and a
    `grab()`/encode failure is logged and retried on the next tick rather than killing
    the streamer -- a transient camera hiccup must not end the whole live view.
    """

    def __init__(self, source: FrameSource, target_fps: float = 15.0) -> None:
        self._source = source
        self._interval_s = 1.0 / target_fps if target_fps > 0 else 0.0
        self._cond = threading.Condition()
        self._latest_chunk: bytes | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="overview-streamer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def frames(self) -> Iterator[bytes]:
        """Per-client generator: yields the latest published chunk, never calls `grab()`."""
        last_seen: bytes | None = None
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait_for(
                    lambda: self._stop.is_set() or self._latest_chunk is not last_seen,
                    timeout=1.0,
                )
                chunk = self._latest_chunk
            if chunk is None or chunk is last_seen:
                continue
            last_seen = chunk
            yield chunk

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                frame = self._source.grab()
                chunk = mjpeg_chunk(encode_jpeg(frame.image))
            except Exception as exc:  # noqa: BLE001 - a transient grab must not kill the streamer
                log.warning("overview grab/encode failed: %s", exc)
            else:
                with self._cond:
                    self._latest_chunk = chunk
                    self._cond.notify_all()
            remaining = self._interval_s - (time.monotonic() - t0)
            if remaining > 0:
                self._stop.wait(remaining)
