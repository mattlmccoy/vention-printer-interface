"""Automatic calibration solve: lens distortion + print-plane mapping at the capture pose.

Spec docs/superpowers/specs/2026-10-20-auto-calibration-design.md §7. The science camera rides the
recoater; the sweep photographs one static ChArUco board from a row of recoater positions, so every
view is the same plane at the same height.

* **Distortion.** ``cv2.calibrateCamera`` over all usable views with the focal length FIXED to a
  nominal value (the image width). With a translating camera at one height the focal length is not
  observable, and it does not need to be: a wrong focal length is absorbed exactly by the radial and
  tangential coefficients in pixel space, so the pixel -> plane mapping is unchanged.
* **Bed homography.** From the view at the capture pose: undistorted pixels -> board mm, then a
  rotation into the bed frame (origin = ChArUco corner 0, +X = increasing recoater mm, Y
  perpendicular with the image's handedness: a proper rotation, never a mirror).
* **Recoater direction + encoder-shift check.** Every other view, mapped through the capture-pose
  calibration, shows the board displaced by -Δ along the recoater axis (Δ = its recoater offset from
  the capture view, read back from the encoder). A least-squares fit gives that direction and its
  length; ``scale_ratio`` = apparent shift / encoder shift (1.0 when the scale is right), and the
  per-corner residuals give ``shift_rms_mm`` / ``shift_worst_mm``.
* **Bed raster.** ``bed_extent_mm`` = bounding box of where corners were seen (all views, in image
  space) mapped into the bed frame; ``mm_per_px`` ~ native resolution at the image centre, raised
  until the raster fits ``MAX_BED_IMAGE_PX``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vention_printer_interface.vision.charuco_points import MARKER_ID_BASE
from vention_printer_interface.vision.registration import (
    MAX_BED_IMAGE_PX,
    Calibration,
    apply_homography,
    bed_raster_error,
    compute_homography,
    undistort_points,
)

MIN_CORNERS = 4  # a view needs at least this many ChArUco corners to be used
# Pass rule (spec §7, "my call"; tune after the first real run).
MIN_VIEWS = 5
# Lens-fit limit in mm ON THE BED (rms px x mm/px at the image centre), matching the +-0.05 mm
# target. It was 0.5 px, which tightens as the photo grows: 0.034 mm at 1920x1080 but 0.013 mm at
# 5120x3840, so the first full-resolution run (1.40 px = 0.036 mm, every mm check passing) failed.
MAX_REPROJ_MM = 0.05
MAX_SHIFT_RMS_MM = 0.1
CAPTURE_POSE_TOL_MM = 0.15  # the capture-pose view must be read back within this of the pose


@dataclass(frozen=True)
class AutocalView:
    recoater_mm: float  # measured (telemetry readback), not commanded
    image_points: np.ndarray  # Nx2 px
    object_points: np.ndarray  # Nx3 board mm (Z = 0)
    ids: np.ndarray  # Nx1 ChArUco corner ids


@dataclass(frozen=True)
class AutocalResult:
    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    H: np.ndarray  # noqa: N815 - undistorted px -> bed mm (same contract as Calibration.H)
    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]
    reprojection_rms_px: float
    shift_rms_mm: float
    shift_worst_mm: float
    scale_ratio: float
    n_views: int
    image_size: tuple[int, int]
    valid_region_mm: list[tuple[float, float]]
    capture_view_corners: int
    px_mm: float = float("nan")  # true mm per photo pixel at the image centre (unrounded)
    # Lens-fit residuals by point type (corner/marker) and image region (centre/middle/edge by
    # distance from the centre: < 1/3, < 2/3, >= 2/3 of the half-diagonal): {"n", "rms_px"}.
    residuals: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def reprojection_rms_mm(self) -> float:
        return self.reprojection_rms_px * self.px_mm


def _fit_distortion(
    views: list[AutocalView], image_size: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray, float, dict[str, dict[str, float]]]:
    import cv2

    w, h = image_size
    k0 = np.array([[float(w), 0.0, w / 2.0], [0.0, float(w), h / 2.0], [0.0, 0.0, 1.0]])
    # Principal point FIXED at the image centre too: on the synthetic sweep (true principal point
    # 12/-8 px off-centre, k1=-0.15, k2=0.05) the tangential terms absorb the offset; all-view
    # mapping error was 0.011 mm RMS / 0.033 mm worst fixed vs 0.013 / 0.046 mm free (2026-10-20).
    flags = (
        cv2.CALIB_USE_INTRINSIC_GUESS
        | cv2.CALIB_FIX_FOCAL_LENGTH
        | cv2.CALIB_FIX_ASPECT_RATIO
        | cv2.CALIB_FIX_PRINCIPAL_POINT
        | cv2.CALIB_FIX_K3
    )
    criteria = (cv2.TERM_CRITERIA_COUNT + cv2.TERM_CRITERIA_EPS, 200, 1e-10)
    obj = [np.asarray(v.object_points, np.float32).reshape(-1, 3) for v in views]
    img = [np.asarray(v.image_points, np.float32).reshape(-1, 1, 2) for v in views]
    rms, k, dist, rvecs, tvecs = cv2.calibrateCamera(
        obj, img, (int(w), int(h)), k0, np.zeros(5), flags=flags, criteria=criteria,
    )
    # Where does the misfit live? Per point type and per image region (diagnosis, not a gate).
    centre = np.array([w / 2.0, h / 2.0])
    half_diag = float(np.hypot(w / 2.0, h / 2.0))
    errs, kinds, radii = [], [], []
    for v, o, i, rv, tv in zip(views, obj, img, rvecs, tvecs, strict=True):
        proj, _ = cv2.projectPoints(o, rv, tv, k, dist)
        pts = i.reshape(-1, 2).astype(float)
        errs.append(np.linalg.norm(proj.reshape(-1, 2) - pts, axis=1))
        kinds.append(np.asarray(v.ids).ravel() >= MARKER_ID_BASE)
        radii.append(np.linalg.norm(pts - centre, axis=1) / half_diag)
    e, mk, rr = np.concatenate(errs), np.concatenate(kinds), np.concatenate(radii)

    def group(mask: np.ndarray) -> dict[str, float]:
        n = int(mask.sum())
        return {"n": n, "rms_px": float(np.sqrt((e[mask] ** 2).mean())) if n else float("nan")}

    residuals = {
        "corner": group(~mk), "marker": group(mk), "centre": group(rr < 1 / 3),
        "middle": group((rr >= 1 / 3) & (rr < 2 / 3)), "edge": group(rr >= 2 / 3),
    }
    return np.asarray(k, float), np.asarray(dist, float).ravel(), float(rms), residuals


def _origin_board_xy(views: list[AutocalView]) -> np.ndarray:
    for v in views:
        hit = np.where(np.asarray(v.ids).ravel() == 0)[0]
        if len(hit):
            return np.asarray(v.object_points, float).reshape(-1, 3)[hit[0], :2]
    raise ValueError("ChArUco corner 0 (the bed origin) was not seen in any photo")


def _bed_raster(
    to_bed: np.ndarray, k: np.ndarray, dist: np.ndarray, views: list[AutocalView],
    image_size: tuple[int, int], max_bed_px: int,
) -> tuple[float, tuple[float, float, float, float], list[tuple[float, float]], float]:
    import cv2

    seen = np.vstack([np.asarray(v.image_points, np.float32).reshape(-1, 2) for v in views])
    hull = cv2.convexHull(seen).reshape(-1, 2)
    region = apply_homography(to_bed, undistort_points(hull, k, dist))
    x0, y0 = np.floor(region.min(axis=0))
    x1, y1 = np.ceil(region.max(axis=0))
    extent = (float(x0), float(y0), float(x1), float(y1))
    c = np.array([[image_size[0] / 2, image_size[1] / 2]], float)
    probe = np.vstack([c, c + [1.0, 0.0], c + [0.0, 1.0]])
    m = apply_homography(to_bed, undistort_points(probe, k, dist))
    mm = float(np.mean([np.linalg.norm(m[1] - m[0]), np.linalg.norm(m[2] - m[0])]))
    mm_per_px = math.ceil(mm * 100.0) / 100.0 or 0.01
    for _ in range(60):
        if bed_raster_error(mm_per_px, extent) is None and (
            ((x1 - x0) / mm_per_px) * ((y1 - y0) / mm_per_px) <= max_bed_px
        ):
            break
        mm_per_px = round(mm_per_px * 1.25, 4)
    return mm_per_px, extent, [(float(x), float(y)) for x, y in region], mm


def solve_autocal(
    views: list[AutocalView],
    *,
    capture_recoater_mm: float,
    image_size: tuple[int, int],
    max_bed_px: int = MAX_BED_IMAGE_PX,
) -> AutocalResult:
    """Solve the calibration from a sweep, or raise ``ValueError`` with a user-facing reason."""
    usable = [v for v in views if len(np.asarray(v.image_points).reshape(-1, 2)) >= MIN_CORNERS]
    if len(usable) < 2:
        raise ValueError(
            f"need at least 2 usable photos (≥{MIN_CORNERS} corners each); got {len(usable)} views"
        )
    cap = min(usable, key=lambda v: abs(v.recoater_mm - capture_recoater_mm))
    if abs(cap.recoater_mm - capture_recoater_mm) > CAPTURE_POSE_TOL_MM:
        raise ValueError(
            f"no usable photo at the capture pose ({capture_recoater_mm:g} mm): the board must be "
            "visible there, because that photo defines the bed reference"
        )
    k, dist, rms, residuals = _fit_distortion(usable, image_size)

    def undist(v: AutocalView) -> np.ndarray:
        return undistort_points(np.asarray(v.image_points, float).reshape(-1, 2), k, dist)

    board_xy = {id(v): np.asarray(v.object_points, float).reshape(-1, 3)[:, :2] for v in usable}
    h_board = compute_homography(undist(cap), board_xy[id(cap)])

    # Recoater direction: displacement d of each corner (mapped through the capture calibration vs
    # its true board position) is Δ·v; least squares over every corner of every other view.
    others = [v for v in usable if v is not cap]
    deltas, disps = [], []
    for v in others:
        delta = v.recoater_mm - cap.recoater_mm
        d = apply_homography(h_board, undist(v)) - board_xy[id(v)]
        deltas.append(np.full(len(d), delta))
        disps.append(d)
    delta_all, d_all = np.concatenate(deltas), np.vstack(disps)
    denom = float((delta_all ** 2).sum())
    if denom <= 0:
        raise ValueError("all photos were taken at the same recoater position; need a sweep")
    v_fit = (delta_all[:, None] * d_all).sum(axis=0) / denom
    scale_ratio = float(np.linalg.norm(v_fit))
    if scale_ratio == 0:
        raise ValueError("the board did not move between photos; check the recoater moved")
    x_hat = -v_fit / scale_ratio  # bed +X in board coordinates (camera +mm -> board appears -X)
    residual = d_all + delta_all[:, None] * x_hat[None, :]
    dist_mm = np.linalg.norm(residual, axis=1)

    c, s = float(x_hat[0]), float(x_hat[1])
    rot = np.array([[c, s], [-s, c]])  # proper rotation taking x_hat to (1, 0)
    origin = _origin_board_xy(usable)
    to_bed_board = np.eye(3)
    to_bed_board[:2, :2] = rot
    to_bed_board[:2, 2] = -rot @ origin
    h_bed = to_bed_board @ h_board
    mm_per_px, extent, region, px_mm = _bed_raster(h_bed, k, dist, usable, image_size,
                                                   max_bed_px)
    return AutocalResult(
        camera_matrix=k, dist_coeffs=dist, H=h_bed, mm_per_px=mm_per_px, bed_extent_mm=extent,
        reprojection_rms_px=rms, shift_rms_mm=float(np.sqrt((dist_mm ** 2).mean())),
        shift_worst_mm=float(dist_mm.max()), scale_ratio=scale_ratio, n_views=len(usable),
        image_size=(int(image_size[0]), int(image_size[1])), valid_region_mm=region,
        capture_view_corners=int(len(np.asarray(cap.image_points).reshape(-1, 2))),
        px_mm=px_mm, residuals=residuals,
    )


def judge(result: AutocalResult) -> tuple[bool, list[str]]:
    """Pass/fail with one plain sentence per failed limit (never a bare "failed")."""
    reasons: list[str] = []
    if result.n_views < MIN_VIEWS:
        reasons.append(f"only {result.n_views} usable photos; need at least {MIN_VIEWS}")
    if not result.reprojection_rms_mm <= MAX_REPROJ_MM:  # NaN (unknown scale) fails too
        reasons.append(
            f"lens fit error {result.reprojection_rms_mm:.2g} mm on the bed "
            f"({result.reprojection_rms_px:.2g} px at {result.px_mm:.4f} mm/px) is above the "
            f"{MAX_REPROJ_MM:g} mm limit"
        )
    if result.shift_rms_mm > MAX_SHIFT_RMS_MM:
        reasons.append(
            f"encoder-shift check {result.shift_rms_mm:.2g} mm RMS is above the "
            f"{MAX_SHIFT_RMS_MM:g} mm limit (scale {result.scale_ratio:.4f} of the recoater's)"
        )
    return not reasons, reasons


def to_calibration(
    result: AutocalResult, *, version: str, provenance: dict[str, Any]
) -> Calibration:
    """The persisted calibration for a passing run. ``reprojection_error`` (mm, the field the
    manual flow fills with its homography residual) carries the run's encoder-shift RMS."""
    return Calibration(
        H=result.H,
        mm_per_px=result.mm_per_px,
        bed_extent_mm=result.bed_extent_mm,
        version=version,
        reprojection_error=result.shift_rms_mm,
        camera_matrix=result.camera_matrix,
        dist_coeffs=result.dist_coeffs,
        distortion_model="opencv-5",
        image_size=result.image_size,
        validation={},
        provenance=dict(provenance),
    )
