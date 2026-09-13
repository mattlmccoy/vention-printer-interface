import numpy as np

from vention_printer_interface.vision.overview import encode_jpeg, mjpeg_chunk


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
