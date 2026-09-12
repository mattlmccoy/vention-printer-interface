"""Bed-plane registration: pure functions over point correspondences + calibration IO."""
from __future__ import annotations

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
