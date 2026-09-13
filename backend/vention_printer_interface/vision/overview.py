"""MJPEG encoding + single-grabber fan-out for the overview camera's live-view stream.

The overview stream is served as `multipart/x-mixed-replace`: repeated boundary-framed
JPEG chunks. `encode_jpeg`/`mjpeg_chunk` are the pure encode/frame steps. `OverviewStreamer`
owns the one background thread that actually calls `FrameSource.grab()`: any number of HTTP
clients read the latest published chunk from a shared slot via `frames()` and never call
`grab()` themselves, so concurrent clients never race on the same `cv2.VideoCapture` (see
review finding I1 -- concurrent `VideoCapture.read()` across threadpool clients is not
thread-safe).

Camera-on-demand (the "camera light stays on" fix): the streamer NEVER opens its
`FrameSource` at construction. It opens on the FIRST stream viewer and releases (closes) it
when the LAST viewer disconnects, after a short idle grace so a quick reconnect reuses the
already-open capture instead of churning the device. The grabber thread therefore runs only
while `viewers > 0` (plus the grace tail). `stop()` is the explicit force-release path used
by app shutdown and `POST /api/vision/deactivate`.
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
    """Viewer-ref-counted, lazy, auto-releasing owner of the overview live-view stream.

    `frames()` is the on-demand entry point (called by the stream route, one call per HTTP
    client): it registers a viewer, opening the `FrameSource` and launching the single
    background grabber thread when it is the FIRST viewer, and returns a generator that reads
    the latest published chunk from a shared slot guarded by a `threading.Condition` -- it
    never calls `grab()` itself, so any number of concurrent clients safely share the one
    capture. When the generator is closed (client disconnect) the viewer count drops; the
    last viewer leaving schedules a release after `idle_grace_s`, which stops the grabber and
    closes the device. `stop()` force-releases everything now (shutdown / deactivate).

    Threading contract: `_lifecycle` guards the viewer count, the grabber thread handle, the
    idle-release timer, and the open flag; the grabber thread and the per-viewer generators
    only touch `_cond`/`_grab_stop`, never `_lifecycle`, so the lock is never held across a
    thread join or a blocking device call.
    """

    def __init__(
        self, source: FrameSource, target_fps: float = 15.0, idle_grace_s: float = 2.5
    ) -> None:
        self._source = source
        self._interval_s = 1.0 / target_fps if target_fps > 0 else 0.0
        self._idle_grace_s = max(idle_grace_s, 0.0)
        self._cond = threading.Condition()
        self._latest_chunk: bytes | None = None
        self._lifecycle = threading.Lock()
        self._viewers = 0
        self._thread: threading.Thread | None = None
        self._grab_stop = threading.Event()
        self._release_timer: threading.Timer | None = None
        self._opened = False
        self._shutdown = False

    def frames(self) -> Iterator[bytes]:
        """Register a stream viewer and return its per-client chunk generator.

        Opening the device happens eagerly here (not inside the returned generator) so that a
        first-viewer open failure raises synchronously to the caller -- the stream route maps
        that to a 503 instead of a half-open 200. A stopped/deactivated streamer registers no
        viewer and returns an empty generator (the route then answers 200 with an empty body).
        """
        acquired = self._acquire()
        return self._generate(acquired)

    def stop(self) -> None:
        """Force-release now: stop the grabber, join it, and close the device (shutdown /
        deactivate). Idempotent and safe even if no viewer ever connected."""
        with self._lifecycle:
            self._shutdown = True
            self._cancel_release_timer_locked()
            thread = self._thread
            self._thread = None
            self._viewers = 0
            self._grab_stop.set()
        with self._cond:
            self._cond.notify_all()
        if thread is not None:
            thread.join(timeout=3.0)
        self._close_source()

    # ---- viewer ref-counting ------------------------------------------------------------

    def _acquire(self) -> bool:
        """Take a viewer slot, starting the grabber on the first viewer. Returns False when
        the streamer is shut down (no slot taken). Re-raises a first-viewer open failure after
        rolling the slot back, so no viewer is counted for a capture that never opened."""
        with self._lifecycle:
            if self._shutdown:
                return False
            self._cancel_release_timer_locked()  # a reconnect cancels a pending idle release
            self._viewers += 1
            if self._thread is None:  # grabber not running -> start it (open the device)
                try:
                    self._start_grabber_locked()
                except BaseException:
                    self._viewers -= 1
                    raise
            return True

    def _release_viewer(self) -> None:
        with self._lifecycle:
            if self._viewers > 0:
                self._viewers -= 1
            if self._viewers == 0 and not self._shutdown:
                self._schedule_release_locked()

    def _start_grabber_locked(self) -> None:
        self._source.open()
        self._opened = True
        self._grab_stop.clear()
        self._thread = threading.Thread(target=self._run, name="overview-streamer", daemon=True)
        self._thread.start()

    def _schedule_release_locked(self) -> None:
        # Always release from a separate timer thread so `_do_release` (which joins the grabber
        # and closes the device) never runs while `_lifecycle` is held.
        self._cancel_release_timer_locked()
        self._release_timer = threading.Timer(self._idle_grace_s, self._do_release)
        self._release_timer.daemon = True
        self._release_timer.start()

    def _cancel_release_timer_locked(self) -> None:
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    def _do_release(self) -> None:
        with self._lifecycle:
            # A viewer reconnected during the grace window, or we already released.
            if self._viewers > 0 or self._thread is None or self._shutdown:
                return
            thread = self._thread
            self._thread = None
            self._grab_stop.set()
        with self._cond:
            self._cond.notify_all()
        thread.join(timeout=3.0)
        self._close_source()

    def _close_source(self) -> None:
        with self._lifecycle:
            opened = self._opened
            self._opened = False
            self._latest_chunk = None
        if opened:
            try:
                self._source.close()
            except Exception as exc:  # noqa: BLE001 - a close failure must not crash release
                log.warning("overview source close failed: %s", exc)

    # ---- per-viewer generator + grabber loop --------------------------------------------

    def _generate(self, acquired: bool) -> Iterator[bytes]:
        if not acquired:
            return
        try:
            last_seen: bytes | None = None
            while not self._grab_stop.is_set() and not self._shutdown:
                with self._cond:
                    while (
                        not self._grab_stop.is_set()
                        and not self._shutdown
                        and (self._latest_chunk is None or self._latest_chunk is last_seen)
                    ):
                        self._cond.wait(timeout=1.0)
                    chunk = self._latest_chunk
                if chunk is None or chunk is last_seen:
                    continue
                last_seen = chunk
                yield chunk
        finally:
            self._release_viewer()

    def _run(self) -> None:
        while not self._grab_stop.is_set():
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
                self._grab_stop.wait(remaining)
