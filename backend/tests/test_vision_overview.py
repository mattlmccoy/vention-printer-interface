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


# ---- I1: OverviewStreamer -- single background grabber, shared fan-out ------------------


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


def test_overview_streamer_publishes_frames_clients_never_call_grab() -> None:
    source = SimulatedFrameSource(width=8, height=8)
    source.open()
    streamer = OverviewStreamer(source, target_fps=50.0)
    streamer.start()
    try:
        chunk = next(streamer.frames())
        assert chunk.startswith(b"--frame")
        assert b"Content-Type: image/jpeg" in chunk
    finally:
        streamer.stop()


def test_overview_streamer_survives_a_transient_grab_error() -> None:
    source = _RaiseOnceThenSucceed()
    streamer = OverviewStreamer(source, target_fps=50.0)
    streamer.start()
    try:
        chunk = next(streamer.frames())  # blocks (bounded) until the first successful frame
        assert chunk.startswith(b"--frame")
        assert source.calls >= 2  # the first (raising) call did not kill the grabber loop
    finally:
        streamer.stop()


def test_overview_streamer_stop_joins_the_grabber_thread() -> None:
    source = SimulatedFrameSource(width=4, height=4)
    source.open()
    streamer = OverviewStreamer(source, target_fps=50.0)
    streamer.start()
    thread = streamer._thread  # noqa: SLF001 - white-box thread-lifecycle check
    assert thread is not None and thread.is_alive()
    streamer.stop()
    assert not thread.is_alive()
    assert streamer._thread is None  # noqa: SLF001


def test_overview_streamer_paces_grabs_instead_of_busy_looping() -> None:
    source = _CountingSource()
    streamer = OverviewStreamer(source, target_fps=20.0)  # 50ms interval
    streamer.start()
    time.sleep(0.22)
    streamer.stop()
    # ~4-5 grabs expected at 20fps over 220ms; an unpaced busy loop would be thousands.
    assert 1 <= source.calls <= 15
