import time

import numpy as np

from vention_printer_interface.vision.frame_source import Frame, FrameSource, SimulatedFrameSource
from vention_printer_interface.vision.overview import OverviewStreamer, encode_jpeg, mjpeg_chunk


def test_encode_jpeg_returns_nonempty_jpeg_bytes():
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    jpeg = encode_jpeg(img)
    assert isinstance(jpeg, bytes)
    assert len(jpeg) > 0
    assert jpeg.startswith(b"\xff\xd8")  # JPEG SOI magic


def test_mjpeg_chunk_frames_jpeg_bytes_with_multipart_boundary():
    payload = b"\xff\xd8fake-jpeg-bytes\xff\xd9"
    chunk = mjpeg_chunk(payload)
    assert chunk.startswith(b"--frame")
    assert b"Content-Type: image/jpeg" in chunk
    assert payload in chunk


def test_mjpeg_chunk_round_trips_real_encoded_jpeg():
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    jpeg = encode_jpeg(img)
    chunk = mjpeg_chunk(jpeg)
    assert chunk.startswith(b"--frame")
    assert jpeg in chunk


# ---- test doubles ------------------------------------------------------------------------


class _TrackingSource(FrameSource):
    """Records open()/close()/grab() calls and reports whether it is currently open.

    This is the hardware-free stand-in the on-demand tests key on: the whole point of the
    camera-on-demand fix is that ``open()`` happens lazily (first viewer) and ``close()``
    happens on release (last viewer, after the idle grace) -- so the test asserts on these
    counters, never on a real device.
    """

    def __init__(self) -> None:
        self.open_count = 0
        self.close_count = 0
        self.grab_count = 0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self.open_count += 1
        self._open = True

    def close(self) -> None:
        self.close_count += 1
        self._open = False

    def grab(self) -> Frame:
        self.grab_count += 1
        return Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), timestamp_ns=self.grab_count)


class _RaiseOnceThenSucceed(FrameSource):
    """grab() fails once, then succeeds forever -- a transient grab failure."""

    def __init__(self) -> None:
        self.calls = 0

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient grab failure")
        return Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), timestamp_ns=self.calls)


class _CountingSource(FrameSource):
    def __init__(self) -> None:
        self.calls = 0

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def grab(self) -> Frame:
        self.calls += 1
        return Frame(image=np.zeros((2, 2, 3), dtype=np.uint8), timestamp_ns=self.calls)


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# ---- on-demand lifecycle (the camera-on-demand fix) --------------------------------------


def test_constructing_streamer_does_not_open_source() -> None:
    """No camera at startup: merely constructing the streamer must never open the device."""
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    assert source.open_count == 0
    assert source.grab_count == 0
    assert streamer._thread is None  # noqa: SLF001 - white-box: no grabber thread yet


def test_first_viewer_opens_source_and_grabs_then_release_closes_it() -> None:
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    gen = streamer.frames()
    try:
        chunk = next(gen)  # blocks (bounded) until the first grabbed+published frame
        assert chunk.startswith(b"--frame")
        assert source.open_count == 1  # opened lazily on the FIRST viewer
        assert source.is_open
        assert source.grab_count >= 1
    finally:
        gen.close()  # viewer disconnects
    # after the (short) idle grace, the source is released and the grabber thread stops
    assert _wait_until(lambda: source.close_count == 1)
    assert not source.is_open
    assert _wait_until(lambda: streamer._thread is None)  # noqa: SLF001


def test_two_concurrent_viewers_open_source_once_release_after_both_disconnect() -> None:
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    gen1 = streamer.frames()
    gen2 = streamer.frames()
    try:
        next(gen1)
        next(gen2)
        assert source.open_count == 1  # ONE capture shared across both viewers

        gen1.close()  # first viewer leaves -- source must stay open for the second
        time.sleep(0.15)  # longer than the idle grace
        assert source.close_count == 0
        assert source.is_open
    finally:
        gen2.close()  # last viewer leaves
    assert _wait_until(lambda: source.close_count == 1)  # released only now
    assert not source.is_open


def test_reconnect_within_idle_grace_reuses_the_open_source() -> None:
    """A viewer reconnecting during the idle grace must reuse the still-open capture rather
    than churn the device closed-then-open."""
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.3)
    gen1 = streamer.frames()
    next(gen1)
    gen1.close()  # schedules release after 0.3s grace
    gen2 = streamer.frames()  # reconnect well within the grace window
    try:
        next(gen2)
        assert source.open_count == 1  # never re-opened
        assert source.close_count == 0  # never released
        assert source.is_open
    finally:
        gen2.close()
    streamer.stop()


def test_stop_releases_source_and_joins_the_grabber_thread() -> None:
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=5.0)
    gen = streamer.frames()
    next(gen)
    thread = streamer._thread  # noqa: SLF001 - white-box thread-lifecycle check
    assert thread is not None and thread.is_alive()
    streamer.stop()
    assert not thread.is_alive()
    assert streamer._thread is None  # noqa: SLF001
    assert source.close_count >= 1  # explicit release path closed the device
    assert not source.is_open
    gen.close()


def test_frames_returns_empty_generator_after_stop() -> None:
    """A stopped (deactivated) streamer must not resurrect the camera: frames() yields
    nothing and never opens the source -- this is what lets the stream route answer 200 with
    an empty body for a shut-down streamer."""
    source = _TrackingSource()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    streamer.stop()
    assert list(streamer.frames()) == []
    assert source.open_count == 0


def test_frames_raises_when_source_open_fails_so_route_can_503() -> None:
    class _FailOpen(FrameSource):
        def open(self) -> None:
            raise RuntimeError("no camera attached")

        def close(self) -> None:
            pass

        def grab(self) -> Frame:  # pragma: no cover - never reached
            raise RuntimeError("no camera attached")

    streamer = OverviewStreamer(_FailOpen(), target_fps=50.0, idle_grace_s=0.05)
    import pytest

    with pytest.raises(RuntimeError):
        streamer.frames()  # eager open failure surfaces here (route maps it to 503)
    assert streamer._thread is None  # noqa: SLF001 - no leaked grabber thread on failure


# ---- pacing + resilience (carried over from the single-grabber design) -------------------


def test_overview_streamer_publishes_frames_clients_never_call_grab() -> None:
    source = SimulatedFrameSource(width=8, height=8)
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    gen = streamer.frames()
    try:
        chunk = next(gen)
        assert chunk.startswith(b"--frame")
        assert b"Content-Type: image/jpeg" in chunk
    finally:
        gen.close()
        streamer.stop()


def test_overview_streamer_survives_a_transient_grab_error() -> None:
    source = _RaiseOnceThenSucceed()
    streamer = OverviewStreamer(source, target_fps=50.0, idle_grace_s=0.05)
    gen = streamer.frames()
    try:
        chunk = next(gen)  # blocks (bounded) until the first successful frame
        assert chunk.startswith(b"--frame")
        assert source.calls >= 2  # the first (raising) call did not kill the grabber loop
    finally:
        gen.close()
        streamer.stop()


def test_overview_streamer_paces_grabs_instead_of_busy_looping() -> None:
    source = _CountingSource()
    streamer = OverviewStreamer(source, target_fps=20.0, idle_grace_s=0.05)  # 50ms interval
    gen = streamer.frames()
    next(gen)
    time.sleep(0.22)
    gen.close()
    streamer.stop()
    # ~4-5 grabs expected at 20fps over 220ms; an unpaced busy loop would be thousands.
    assert 1 <= source.calls <= 15
