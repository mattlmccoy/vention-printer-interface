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
# Board-vs-encoder scale disagreement that is corrected (an engraving tolerance); beyond this the
# board or the encoder is wrong and the run fails rather than absorbing it.
MAX_SCALE_DEV = 0.005
CAPTURE_POSE_TOL_MM = 0.15  # the capture-pose view must be read back within this of the pose


@dataclass(frozen=True)
class AutocalView:
    recoater_mm: float  # measured (telemetry readback), not commanded
    image_points: np.ndarray  # Nx2 px
    object_points: np.ndarray  # Nx3 board mm (Z = 0)
    ids: np.ndarray  # Nx1 ChArUco corner ids
    # Which board placement this photo belongs to (0 = the first; the board is moved between
    # placements so the sweep covers more of the frame).
    placement: int = 0


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
    # Per usable view (input order): Nx2 lens-fit residual arrows, projected - detected (px).
    point_residuals: list[np.ndarray] = field(default_factory=list)

    @property
    def reprojection_rms_mm(self) -> float:
        return self.reprojection_rms_px * self.px_mm


def _fit_distortion(
    views: list[AutocalView], image_size: tuple[int, int], *, free_principal_point: bool = False,
) -> tuple[np.ndarray, np.ndarray, float, dict[str, dict[str, float]], list[np.ndarray]]:
    import cv2

    w, h = image_size
    k0 = np.array([[float(w), 0.0, w / 2.0], [0.0, float(w), h / 2.0], [0.0, 0.0, 1.0]])
    # Principal point FIXED at the image centre too: on the synthetic sweep (true principal point
    # 12/-8 px off-centre, k1=-0.15, k2=0.05) the tangential terms absorb the offset; all-view
    # mapping error was 0.011 mm RMS / 0.033 mm worst fixed vs 0.013 / 0.046 mm free (2026-10-20).
    # With SEVERAL board placements the data spans the frame and the optical centre becomes
    # measurable: freeing it cut the far-region error 16.9 -> 13.2 um on a real-like synthetic
    # (k3 stays fixed: freeing it made that worse). One placement keeps it fixed (2026-10-26 real
    # single-band run: freeing it did not improve held-out accuracy).
    flags = (
        cv2.CALIB_USE_INTRINSIC_GUESS
        | cv2.CALIB_FIX_FOCAL_LENGTH
        | cv2.CALIB_FIX_ASPECT_RATIO
        | cv2.CALIB_FIX_K3
        | (0 if free_principal_point else cv2.CALIB_FIX_PRINCIPAL_POINT)
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
    errs, kinds, radii, vectors = [], [], [], []
    for v, o, i, rv, tv in zip(views, obj, img, rvecs, tvecs, strict=True):
        proj, _ = cv2.projectPoints(o, rv, tv, k, dist)
        pts = i.reshape(-1, 2).astype(float)
        vec = proj.reshape(-1, 2).astype(float) - pts
        vectors.append(vec)
        errs.append(np.linalg.norm(vec, axis=1))
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
    return np.asarray(k, float), np.asarray(dist, float).ravel(), float(rms), residuals, vectors


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
    # Placements: the board is moved between sweeps so more of the frame is calibrated. The FIRST
    # placement defines the bed frame (its capture-pose photo); every placement gets its own
    # reference photo for the encoder-shift check, because its board pose differs.
    groups: dict[int, list[AutocalView]] = {}
    for v in usable:
        groups.setdefault(int(v.placement), []).append(v)
    first = min(groups)
    cap = min(groups[first], key=lambda v: abs(v.recoater_mm - capture_recoater_mm))
    if abs(cap.recoater_mm - capture_recoater_mm) > CAPTURE_POSE_TOL_MM:
        raise ValueError(
            f"no usable photo at the capture pose ({capture_recoater_mm:g} mm): the board must be "
            "visible there, because that photo defines the bed reference"
        )
    for p, vs in groups.items():
        if p != first and len({round(v.recoater_mm, 1) for v in vs}) < 2:
            raise ValueError(f"placement {p + 1} needs at least 2 usable photos at different "
                             "recoater positions; run its sweep again")
    k, dist, rms, residuals, vectors = _fit_distortion(
        usable, image_size, free_principal_point=len(groups) > 1)

    def undist(v: AutocalView) -> np.ndarray:
        return undistort_points(np.asarray(v.image_points, float).reshape(-1, 2), k, dist)

    board_xy = {id(v): np.asarray(v.object_points, float).reshape(-1, 3)[:, :2] for v in usable}
    h_board = compute_homography(undist(cap), board_xy[id(cap)])

    # Recoater direction, per placement: displacement d of each corner (mapped through that
    # placement's reference photo vs its true board position) is Δ·v; least squares over every
    # corner of every other photo. Scale (|v|) is pooled over placements, weighted by Σ Δ².
    v_fit = np.zeros(2)
    scale_num = scale_den = 0.0
    residual_parts: list[np.ndarray] = []
    for p, vs in groups.items():
        ref = cap if p == first else min(vs, key=lambda v: abs(v.recoater_mm - capture_recoater_mm))
        hb = h_board if p == first else compute_homography(undist(ref), board_xy[id(ref)])
        deltas, disps = [], []
        for v in vs:
            if v is ref:
                continue
            d = apply_homography(hb, undist(v)) - board_xy[id(v)]
            deltas.append(np.full(len(d), v.recoater_mm - ref.recoater_mm))
            disps.append(d)
        if not deltas:
            continue
        delta_p, d_p = np.concatenate(deltas), np.vstack(disps)
        denom = float((delta_p ** 2).sum())
        if denom <= 0:
            if p == first:
                raise ValueError("all photos were taken at the same recoater position; need a "
                                 "sweep")
            continue
        v_p = (delta_p[:, None] * d_p).sum(axis=0) / denom
        if p == first:
            v_fit = v_p
        scale_num += float(np.linalg.norm(v_p)) * denom
        scale_den += denom
        residual_parts.append(d_p - delta_p[:, None] * v_p[None, :])
    if scale_den <= 0 or not np.linalg.norm(v_fit) > 0:
        raise ValueError("the board did not move between photos; check the recoater moved")
    scale_ratio = scale_num / scale_den
    x_hat = -v_fit / float(np.linalg.norm(v_fit))  # bed +X in board coordinates (camera +mm ->
    # board appears -X)
    # Scale: the recoater encoder is the length reference. scale_ratio = board-mm per encoder-mm;
    # != 1 means the engraved board is not its nominal size (2026-10-26: 1.0020, and the certified
    # chessboard agreed at 1.0027). The shift check measures consistency with that scale fitted
    # out, then the mapping is rescaled to encoder mm (judge() refuses large disagreements).
    dist_mm = np.linalg.norm(np.vstack(residual_parts), axis=1) / scale_ratio

    c, s = float(x_hat[0]), float(x_hat[1])
    rot = np.array([[c, s], [-s, c]])  # proper rotation taking x_hat to (1, 0)
    origin = _origin_board_xy(groups[first])  # the first placement's corner 0
    to_bed_board = np.eye(3)
    to_bed_board[:2, :2] = rot
    to_bed_board[:2, 2] = -rot @ origin
    to_encoder_mm = np.diag([1.0 / scale_ratio, 1.0 / scale_ratio, 1.0])
    h_bed = to_encoder_mm @ to_bed_board @ h_board
    mm_per_px, extent, region, px_mm = _bed_raster(h_bed, k, dist, usable, image_size,
                                                   max_bed_px)
    return AutocalResult(
        camera_matrix=k, dist_coeffs=dist, H=h_bed, mm_per_px=mm_per_px, bed_extent_mm=extent,
        reprojection_rms_px=rms, shift_rms_mm=float(np.sqrt((dist_mm ** 2).mean())),
        shift_worst_mm=float(dist_mm.max()), scale_ratio=scale_ratio, n_views=len(usable),
        image_size=(int(image_size[0]), int(image_size[1])), valid_region_mm=region,
        capture_view_corners=int(len(np.asarray(cap.image_points).reshape(-1, 2))),
        px_mm=px_mm, residuals=residuals, point_residuals=vectors,
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
    if abs(result.scale_ratio - 1.0) > MAX_SCALE_DEV:
        reasons.append(
            f"the board and the recoater disagree on scale by "
            f"{(result.scale_ratio - 1.0) * 100:+.2f}% (corrected only up to "
            f"{MAX_SCALE_DEV * 100:g}%) — measure the board's scale bar with calipers"
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
