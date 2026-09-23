"""Detect camera frames that stopped arriving partway (truncated transfers).

Seen 2026-09-23 on the Windows lab PC: the ELP science camera at 5120x3840 YUY2 (~39 MB/frame,
~295 MB/s at 7.5 fps) through a USB hub shared with a USB-Ethernet adapter delivered frames whose
data stopped about 2/3 down -- torn rows, then a band of UNFILLED buffer. Unfilled YUY2 decodes
green, and every row of that band has the same average colour (it varies across, never down).

Such a frame has plenty of contrast, so the blank/near-uniform guard passes it; without this check
a half-missing science still is stored and analysed as if it were real.

Signature (measured on the real frame vs real print frames and the frame's own dark top):
  * the bottom band's row averages do not drift (max channel std of the row means < 0.5;
    real content measured 1.3 in a dark region, 16-23 in print crops, corrupted band 0.05), and
  * the band is strongly green-dominant (G - max(R, B) >= 30; corrupted band +79, real <= +4), and
  * there is a REAL image above it: the upper half of the frame differs clearly from the band
    (a transfer that stopped had data before it stopped). A synthetic pattern repeated on every row
    -- the simulator's old green ramp -- is flat and green but has nothing above: not truncation.
Limit: a transfer that stops but leaves STALE data (not zeros) is not green and is not caught.
"""

from __future__ import annotations

from typing import Any

import numpy as np

BAND_FRACTION = 0.05  # smallest truncation detected: the last 5% of the frame
MAX_ROW_MEAN_DRIFT = 0.5
MIN_GREEN_DOMINANCE = 30.0
MIN_ABOVE_DIFFERENCE = 10.0  # mean-colour gap between the upper half and the band


def frame_truncation(image: Any, order: str = "rgb") -> str | None:
    """A reason string when ``image`` looks truncated (bottom band of unfilled data), else None.
    ``order`` is the channel order: "rgb", or "bgr" for OpenCV images. Never raises."""
    try:
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] < 3 or arr.shape[0] < 20 or arr.shape[1] < 2:
            return None
        rgb = arr[..., :3][..., ::-1] if order == "bgr" else arr[..., :3]
        h = rgb.shape[0]
        k = max(2, int(h * BAND_FRACTION))
        col_step = max(1, rgb.shape[1] // 256)  # cheap even for 20 MP frames
        band = rgb[h - k:, ::col_step].astype(np.float32)
        row_means = band.mean(axis=1)  # (k, 3)
        drift = float(row_means.std(axis=0).max())
        r, g, b = (float(v) for v in band.reshape(-1, 3).mean(axis=0))
        green = g - max(r, b)
        upper = rgb[: h // 2, ::col_step].astype(np.float32).reshape(-1, 3).mean(axis=0)
        above_differs = float(np.abs(upper - np.array([r, g, b])).max()) >= MIN_ABOVE_DIFFERENCE
        if drift < MAX_ROW_MEAN_DRIFT and green >= MIN_GREEN_DOMINANCE and above_differs:
            return (
                "frame truncated: the bottom of the image never arrived (unfilled green band) — "
                "likely USB bandwidth; use MJPG or a direct USB 3 port"
            )
        return None
    except (TypeError, ValueError):
        return None
