"""Bed-plane registration: pure functions over point correspondences + calibration IO."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


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


@dataclass
class Calibration:
    """Persisted bed-plane calibration. Field names are a stable on-disk contract."""

    H: np.ndarray  # noqa: N815 - fixed field name, consumed by later phases
    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]
    version: str
    reprojection_error: float


def save_calibration(path: Path, calib: Calibration) -> None:
    """Write `calib` to `path` as JSON."""
    payload = asdict(calib)
    payload["H"] = calib.H.tolist()
    payload["bed_extent_mm"] = list(calib.bed_extent_mm)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_calibration(path: Path) -> Calibration | None:
    """Read a `Calibration` from `path`, or return None when the file is absent."""
    p = Path(path)
    if not p.exists():
        return None
    payload = json.loads(p.read_text(encoding="utf-8"))
    bed_extent = payload["bed_extent_mm"]
    return Calibration(
        H=np.array(payload["H"]),
        mm_per_px=payload["mm_per_px"],
        bed_extent_mm=(bed_extent[0], bed_extent[1], bed_extent[2], bed_extent[3]),
        version=payload["version"],
        reprojection_error=payload["reprojection_error"],
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
