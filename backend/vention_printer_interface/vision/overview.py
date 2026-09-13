"""MJPEG encoding for the overview camera's shared live-view stream.

The overview stream is served as `multipart/x-mixed-replace`: repeated boundary-framed
JPEG chunks. This module holds the two pure encode/frame steps; the streaming HTTP
endpoint (Task 13) loops `source.grab()` -> `encode_jpeg` -> `mjpeg_chunk` per client.
"""

from __future__ import annotations

import numpy as np

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
