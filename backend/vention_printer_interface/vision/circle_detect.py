"""Detect the build-piston bore (a large circle) in an overhead science-cam frame.

Used by the camera-center sweep: at each recoater pose we measure how far the bore center sits
from the frame center, and pick the pose that minimises it. Contour-first (robust for a big filled
disc on the textured bed), with a Hough fallback. Pure CV, no IO.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

# Radius bounds as a fraction of the frame's shorter side — the bore fills a big part of the view
# but never the whole frame; excludes tiny specks and full-frame false positives.
_MIN_R_FRAC = 0.12
_MAX_R_FRAC = 0.75
_MIN_FILL = 0.6  # contour area / enclosing-circle area — rejects non-round blobs


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        g = image
    elif image.shape[2] == 4:
        g = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    else:
        g = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0)


def _contour_circle(
    g: np.ndarray, min_r: float, max_r: float
) -> tuple[float, float, float] | None:
    """Largest round-enough region across both Otsu polarities (bore may be brighter or darker)."""
    best: tuple[float, float, float] | None = None
    best_area = 0.0
    for extra in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
        _, bw = cv2.threshold(g, 0, 255, extra + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            (x, y), r = cv2.minEnclosingCircle(cnt)
            if not (min_r <= r <= max_r):
                continue
            if area / (math.pi * r * r) < _MIN_FILL:  # not disc-like
                continue
            if area > best_area:
                best_area, best = area, (float(x), float(y), float(r))
    return best


def _hough_circle(
    g: np.ndarray, min_r: float, max_r: float
) -> tuple[float, float, float] | None:
    circles = cv2.HoughCircles(
        g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=g.shape[0] / 2.0,
        param1=100, param2=30, minRadius=int(min_r), maxRadius=int(max_r),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    x, y, r = circles[0][0]  # strongest accumulator
    return float(x), float(y), float(r)


def detect_piston_circle(image: np.ndarray) -> tuple[float, float, float] | None:
    """Return ``(cx, cy, r)`` px of the dominant bore circle, or ``None`` if none is found."""
    g = _gray(image)
    side = float(min(g.shape[:2]))
    min_r, max_r = _MIN_R_FRAC * side, _MAX_R_FRAC * side
    return _contour_circle(g, min_r, max_r) or _hough_circle(g, min_r, max_r)


def center_offset_px(image: np.ndarray) -> float | None:
    """Radial distance (px) from the frame center to the detected bore center, or ``None``.

    Radial magnitude (not a single axis) so it works regardless of how the recoater-travel axis maps
    to image X/Y: as the recoater sweeps, only the controllable component varies, so the magnitude
    still minimises at the centered pose."""
    circle = detect_piston_circle(image)
    if circle is None:
        return None
    cx, cy, _ = circle
    h, w = image.shape[:2]
    return math.hypot(cx - w / 2.0, cy - h / 2.0)
