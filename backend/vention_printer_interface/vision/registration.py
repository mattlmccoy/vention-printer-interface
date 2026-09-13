"""Bed-plane registration: pure functions over point correspondences + calibration IO."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


def compute_homography(image_pts: np.ndarray, world_pts_mm: np.ndarray) -> np.ndarray:
    """Compute the image->world homography from matched point correspondences."""
    import cv2

    src = np.asarray(image_pts, float).reshape(-1, 1, 2)
    dst = np.asarray(world_pts_mm, float).reshape(-1, 1, 2)
    h_matrix, _ = cv2.findHomography(src, dst, method=0)
    if h_matrix is None:
        raise ValueError("homography could not be computed")
    return h_matrix


def apply_homography(h_matrix: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Map 2D points through homography `h_matrix`, dehomogenizing the result."""
    pts = np.asarray(pts, float)
    hom = np.hstack([pts, np.ones((len(pts), 1))])
    out = (h_matrix @ hom.T).T
    result: np.ndarray = out[:, :2] / out[:, 2:]
    return result


def reprojection_error(
    h_matrix: np.ndarray, image_pts: np.ndarray, world_pts_mm: np.ndarray
) -> float:
    """RMS distance (mm) between `h_matrix`-mapped image points and their true world points."""
    mapped = apply_homography(h_matrix, image_pts)
    d = mapped - np.asarray(world_pts_mm, float)
    return float(np.sqrt((d**2).sum(axis=1).mean()))


def warp_to_bed(
    image: np.ndarray,
    h_matrix: np.ndarray,
    mm_per_px: float,
    bed_extent_mm: tuple[float, float, float, float],
) -> np.ndarray:
    """Warp a raw frame into a bed-plane raster at a fixed mm/px scale.

    `h_matrix` maps image pixels to bed-plane millimeters; `bed_extent_mm` is
    `(x0, y0, x1, y1)` in mm, and the output raster covers exactly that extent.
    """
    import cv2

    x0, y0, x1, y1 = bed_extent_mm
    out_w = int(round((x1 - x0) / mm_per_px))
    out_h = int(round((y1 - y0) / mm_per_px))
    # mm -> output-pixel: translate by (x0, y0), scale by 1/mm_per_px
    scale = np.array(
        [
            [1 / mm_per_px, 0, -x0 / mm_per_px],
            [0, 1 / mm_per_px, -y0 / mm_per_px],
            [0, 0, 1],
        ],
        float,
    )
    warp_matrix = scale @ h_matrix  # image -> output pixels
    result: np.ndarray = cv2.warpPerspective(image, warp_matrix, (out_w, out_h))
    return result


def calibrate_intrinsics(
    object_points: list[np.ndarray],
    image_points: list[np.ndarray],
    image_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, float]:
    """Calibrate camera intrinsics + distortion from multiple planar-target views.

    `object_points`/`image_points` are one array per view of matched 3D (mm,
    typically Z=0 on a planar target) / 2D (px) correspondences, as consumed
    by `cv2.calibrateCamera`. Returns `(camera_matrix, dist_coeffs, rms)`.
    """
    import cv2

    obj = [np.asarray(pts, np.float32) for pts in object_points]
    img = [np.asarray(pts, np.float32) for pts in image_points]
    rms, k_matrix, dist_coeffs, _rvecs, _tvecs = cv2.calibrateCamera(
        obj, img, image_size, None, None
    )
    return k_matrix, dist_coeffs, float(rms)


def undistort_image(image: np.ndarray, k_matrix: np.ndarray, dist_coeffs: np.ndarray) -> np.ndarray:
    """Undistort a raw frame given camera intrinsics `k_matrix` and `dist_coeffs`."""
    import cv2

    result: np.ndarray = cv2.undistort(image, k_matrix, dist_coeffs)
    return result


def undistort_points(pts: np.ndarray, k_matrix: np.ndarray, dist_coeffs: np.ndarray) -> np.ndarray:
    """Undistort 2D pixel points, returning pixel coordinates (not normalized)."""
    import cv2

    src = np.asarray(pts, np.float32).reshape(-1, 1, 2)
    undistorted = cv2.undistortPoints(src, k_matrix, dist_coeffs, P=k_matrix)
    result: np.ndarray = undistorted.reshape(-1, 2)
    return result


@dataclass
class Calibration:
    """Persisted bed-plane calibration. Field names are a stable on-disk contract.

    `camera_matrix`/`dist_coeffs`/`image_size` are optional: older (Phase-2)
    calibration files predate the intrinsics pipeline and carry only the
    homography fields. `load_calibration` tolerates their absence.
    """

    H: np.ndarray  # noqa: N815 - fixed field name, consumed by later phases
    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]
    version: str
    reprojection_error: float
    camera_matrix: np.ndarray | None = None
    dist_coeffs: np.ndarray | None = None
    distortion_model: str = "opencv-5"
    image_size: tuple[int, int] | None = None
    validation: dict[str, Any] = field(default_factory=dict)


def save_calibration(path: Path, calib: Calibration) -> None:
    """Write `calib` to `path` as JSON."""
    payload = asdict(calib)
    payload["H"] = calib.H.tolist()
    payload["bed_extent_mm"] = list(calib.bed_extent_mm)
    payload["camera_matrix"] = (
        calib.camera_matrix.tolist() if calib.camera_matrix is not None else None
    )
    payload["dist_coeffs"] = calib.dist_coeffs.tolist() if calib.dist_coeffs is not None else None
    payload["image_size"] = list(calib.image_size) if calib.image_size is not None else None
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_calibration(path: Path) -> Calibration | None:
    """Read a `Calibration` from `path`, or return None when the file is absent.

    Tolerates Phase-2 files that predate the intrinsics fields: missing keys
    fall back to `None`/defaults and a warning is logged.
    """
    p = Path(path)
    if not p.exists():
        return None
    payload = json.loads(p.read_text(encoding="utf-8"))
    bed_extent = payload["bed_extent_mm"]

    camera_matrix_raw = payload.get("camera_matrix")
    dist_coeffs_raw = payload.get("dist_coeffs")
    image_size_raw = payload.get("image_size")
    if camera_matrix_raw is None or dist_coeffs_raw is None or image_size_raw is None:
        log.warning(
            "calibration file %s has no intrinsics; falling back to homography-only "
            "(back-compat with Phase-2 calibration files)",
            p,
        )

    image_size: tuple[int, int] | None = None
    if image_size_raw is not None:
        image_size = (int(image_size_raw[0]), int(image_size_raw[1]))

    return Calibration(
        H=np.array(payload["H"]),
        mm_per_px=payload["mm_per_px"],
        bed_extent_mm=(bed_extent[0], bed_extent[1], bed_extent[2], bed_extent[3]),
        version=payload["version"],
        reprojection_error=payload["reprojection_error"],
        camera_matrix=np.array(camera_matrix_raw) if camera_matrix_raw is not None else None,
        dist_coeffs=np.array(dist_coeffs_raw) if dist_coeffs_raw is not None else None,
        distortion_model=payload.get("distortion_model", "opencv-5"),
        image_size=image_size,
        validation=payload.get("validation") or {},
    )


def register_frame(
    image: np.ndarray, calibration: Calibration | None
) -> tuple[np.ndarray, dict[str, Any] | None]:
    """Register a raw frame into bed-plane coordinates, or pass it through uncalibrated.

    Homography-only for now (stable call signature for the capture worker): a later
    chunk upgrades the internals to fused undistort+homography once camera intrinsics
    are available on `Calibration`, without changing this function's signature.
    """
    if calibration is None:
        return image, None
    registered = warp_to_bed(
        image, calibration.H, calibration.mm_per_px, calibration.bed_extent_mm
    )
    registered_space = {
        "mm_per_px": calibration.mm_per_px,
        "bed_extent_mm": list(calibration.bed_extent_mm),
    }
    return registered, registered_space
