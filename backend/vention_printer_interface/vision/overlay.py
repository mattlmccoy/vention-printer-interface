"""Overlays drawn ON the calibration photo, so the Calibrate page shows what the solve did.

* ``raw``: the capture-pose photo as taken, with the board's own square grid and the
  calibrated-area outline projected INTO it (inverse homography, then the lens model forward). The
  grid is where the solved calibration says the square edges are: it lies on them when the fit is
  right, and any misfit shows as a visible offset. (A 10 mm bed grid is the fallback when the board
  pose is unknown; it cannot line up with 16 mm squares.)
* ``corrected``: the same photo undistorted and warped onto the bed (``build_bed_remap``), where the
  same grid is straight.

Images are scaled down to at most ``MAX_OVERLAY_PX`` wide for display (a 20 MP PNG is ~30 MB).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from vention_printer_interface.vision.registration import (
    apply_homography,
    build_bed_remap,
    rigid_transform_2d,
    undistort_points,
)

MAX_OVERLAY_PX = 1600
GRID_MM = 10.0
_GRID = (90, 200, 255)  # BGR amber
_AREA = (80, 220, 120)  # BGR green


def fit_width(size: tuple[int, int], max_w: int = MAX_OVERLAY_PX) -> tuple[int, int]:
    """Display size: unchanged when narrow enough, else scaled to ``max_w`` wide."""
    w, h = size
    if w <= max_w:
        return (w, h)
    return (max_w, round(h * max_w / w))


def bed_to_raw_px(
    pts_mm: np.ndarray, k: np.ndarray, dist: np.ndarray, h_bed: np.ndarray
) -> np.ndarray:
    """Bed mm -> pixels in the RAW (distorted) photo: H^-1 to undistorted px, then the lens."""
    import cv2

    pts = np.asarray(pts_mm, float).reshape(-1, 2)
    hom = (np.linalg.inv(h_bed) @ np.column_stack([pts, np.ones(len(pts))]).T).T
    und = hom[:, :2] / hom[:, 2:]
    norm = (np.linalg.inv(k) @ np.column_stack([und, np.ones(len(und))]).T).T
    out, _ = cv2.projectPoints(norm.astype(np.float32).reshape(-1, 1, 3), np.zeros(3),
                               np.zeros(3), k, dist)
    result: np.ndarray = out.reshape(-1, 2)
    return result


def fit_board_to_bed(
    image_points: np.ndarray, object_points: np.ndarray, result: Any
) -> Callable[[np.ndarray], np.ndarray]:
    """Board mm -> bed mm for the board as it lay in one photo: the photo's points through the
    solved calibration, then a rigid (no scale) fit onto their board coordinates."""
    bed = apply_homography(result.H, undistort_points(image_points, result.camera_matrix,
                                                      result.dist_coeffs))
    obj = np.asarray(object_points, float).reshape(-1, 3)[:, :2]
    r_mat, t_vec = rigid_transform_2d(obj, bed)

    def to_bed(xy: np.ndarray) -> np.ndarray:
        out: np.ndarray = np.asarray(xy, float).reshape(-1, 2) @ r_mat.T + t_vec
        return out

    return to_bed


def board_grid_mm(
    squares_x: int, squares_y: int, square_mm: float,
    to_bed: Callable[[np.ndarray], np.ndarray],
) -> list[np.ndarray]:
    """The board's square-edge lines (each densely sampled) in bed mm."""
    w, h = squares_x * square_mm, squares_y * square_mm
    lines = []
    for i in range(squares_x + 1):
        ys = np.linspace(0.0, h, 60)
        lines.append(to_bed(np.column_stack([np.full_like(ys, i * square_mm), ys])))
    for j in range(squares_y + 1):
        xs = np.linspace(0.0, w, 60)
        lines.append(to_bed(np.column_stack([xs, np.full_like(xs, j * square_mm)])))
    return lines


def _grid_lines(extent: tuple[float, float, float, float]) -> list[np.ndarray]:
    """10 mm grid lines over the extent, each densely sampled (so it can bend in the raw view)."""
    x0, y0, x1, y1 = extent
    lines: list[np.ndarray] = []
    for x in np.arange(np.ceil(x0 / GRID_MM) * GRID_MM, x1 + 1e-9, GRID_MM):
        ys = np.linspace(y0, y1, 60)
        lines.append(np.column_stack([np.full_like(ys, x), ys]))
    for y in np.arange(np.ceil(y0 / GRID_MM) * GRID_MM, y1 + 1e-9, GRID_MM):
        xs = np.linspace(x0, x1, 60)
        lines.append(np.column_stack([xs, np.full_like(xs, y)]))
    return lines


def _poly(img: np.ndarray, pts: np.ndarray, color: tuple[int, int, int], closed: bool,
          thick: int) -> None:
    import cv2

    cv2.polylines(img, [np.round(pts).astype(np.int32).reshape(-1, 1, 2)], closed, color, thick,
                  cv2.LINE_AA)


def _scaled(img: np.ndarray) -> np.ndarray:
    import cv2

    w, h = fit_width((img.shape[1], img.shape[0]))
    if (w, h) == (img.shape[1], img.shape[0]):
        return img
    out: np.ndarray = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return out


def draw_overlay(
    image: np.ndarray, result: Any, view: str, board_lines: list[np.ndarray] | None = None,
) -> np.ndarray:
    """The ``raw`` or ``corrected`` overlay for a solved ``AutocalResult``. ``board_lines`` (bed mm,
    from :func:`board_grid_mm`) replaces the fallback 10 mm grid."""
    import cv2

    k, dist, h_bed = result.camera_matrix, result.dist_coeffs, result.H
    extent = tuple(float(v) for v in result.bed_extent_mm)
    region = np.asarray(result.valid_region_mm, float).reshape(-1, 2)
    img = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if view == "raw":
        out = img.copy()
        thick = max(2, round(out.shape[1] / 700))
        for line in board_lines or _grid_lines(extent):  # type: ignore[arg-type]
            _poly(out, bed_to_raw_px(line, k, dist, h_bed), _GRID, False, thick)
        if len(region) >= 3:
            _poly(out, bed_to_raw_px(region, k, dist, h_bed), _AREA, True, thick * 2)
        return _scaled(out)
    # Remap straight at display resolution (never wider than MAX_OVERLAY_PX): the full raster
    # then a resize took 3 s on the real 5120x3840 run (2026-10-21) for the same picture.
    mpp = max(float(result.mm_per_px), (extent[2] - extent[0]) / MAX_OVERLAY_PX)
    map1, map2 = build_bed_remap(k, dist, h_bed, mpp, extent)  # type: ignore[arg-type]
    out = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
    x0, y0 = extent[0], extent[1]

    def to_px(pts: np.ndarray) -> np.ndarray:
        return (np.asarray(pts, float) - [x0, y0]) / mpp

    thick = max(2, round(out.shape[1] / 700))
    for line in board_lines or _grid_lines(extent):  # type: ignore[arg-type]
        _poly(out, to_px(line), _GRID, False, thick)
    if len(region) >= 3:
        _poly(out, to_px(region), _AREA, True, thick * 2)
    return _scaled(out)


def arrow_gain(residuals: np.ndarray, image_w: int) -> float:
    """Arrow enlargement so the 95th-percentile residual draws ~2% of the photo width."""
    mags = np.linalg.norm(np.asarray(residuals, float).reshape(-1, 2), axis=1)
    p95 = float(np.percentile(mags, 95)) if len(mags) else 0.0
    return 0.02 * image_w / p95 if p95 > 0 else 1.0


def draw_residual_arrows(
    image: np.ndarray, points: np.ndarray, residuals: np.ndarray
) -> np.ndarray:
    """The capture-pose photo with each point's lens-fit residual as an arrow (direction and
    size, enlarged; colour = size: blue small -> red large). The gain is printed on the image."""
    import cv2

    out = (image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)).copy()
    pts = np.asarray(points, float).reshape(-1, 2)
    res = np.asarray(residuals, float).reshape(-1, 2)
    gain = arrow_gain(res, out.shape[1])
    mags = np.linalg.norm(res, axis=1)
    top = float(mags.max()) if len(mags) else 1.0
    thick = max(2, round(out.shape[1] / 700))
    for (x, y), (dx, dy), m in zip(pts, res, mags, strict=True):
        t = m / top if top > 0 else 0.0
        color = (int(255 * (1 - t)), 60, int(255 * t))  # BGR: blue -> red
        cv2.arrowedLine(out, (round(x), round(y)), (round(x + dx * gain), round(y + dy * gain)),
                        color, thick, cv2.LINE_AA, tipLength=0.25)
    label = f"lens-fit residual arrows x{gain:.0f} (largest {top:.2f} px)"
    cv2.putText(out, label, (20, 20 + 30 * thick), cv2.FONT_HERSHEY_SIMPLEX, thick * 0.6,
                (20, 20, 20), thick * 3, cv2.LINE_AA)
    cv2.putText(out, label, (20, 20 + 30 * thick), cv2.FONT_HERSHEY_SIMPLEX, thick * 0.6,
                (255, 255, 255), thick, cv2.LINE_AA)
    return _scaled(out)
