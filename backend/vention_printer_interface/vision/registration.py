"""Bed-plane registration: pure functions over point correspondences + calibration IO."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

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


def view_tilt_deg(image_points: np.ndarray, object_points: np.ndarray) -> float:
    """Out-of-plane tilt (deg) of a planar board from its image/object correspondences: fit the
    board->image homography and measure the foreshortening of opposite edges of the board's bounding
    rectangle. Board-aspect invariant (opposite edges are equal when fronto-parallel, regardless of
    the board's own aspect). ~0 for a flat view; grows with tilt. 0.0 if no homography fits."""
    import math

    import cv2

    img = np.asarray(image_points, float).reshape(-1, 2)
    obj = np.asarray(object_points, float).reshape(-1, 3)[:, :2]
    if len(img) < 4 or len(obj) < 4:
        return 0.0
    h, _ = cv2.findHomography(obj, img, cv2.RANSAC)
    if h is None:
        return 0.0
    xmin, ymin = obj.min(axis=0)
    xmax, ymax = obj.max(axis=0)
    corners = np.array([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]], float)
    m = apply_homography(h, corners)

    def edge(a: int, b: int) -> float:
        return float(np.hypot(m[a][0] - m[b][0], m[a][1] - m[b][1]))

    top, bottom, left, right = edge(0, 1), edge(3, 2), edge(0, 3), edge(1, 2)
    rh = min(top, bottom) / max(top, bottom) if max(top, bottom) > 0 else 1.0
    rv = min(left, right) / max(left, right) if max(left, right) > 0 else 1.0
    ratio = max(-1.0, min(1.0, min(rh, rv)))
    return math.degrees(math.acos(ratio))


def reprojection_error(
    h_matrix: np.ndarray, image_pts: np.ndarray, world_pts_mm: np.ndarray
) -> float:
    """RMS distance (mm) between `h_matrix`-mapped image points and their true world points."""
    mapped = apply_homography(h_matrix, image_pts)
    d = mapped - np.asarray(world_pts_mm, float)
    return float(np.sqrt((d**2).sum(axis=1).mean()))


# Largest bed raster (width x height, px) a calibration may produce. The raster is built on
# EVERY science capture, so an unbounded one (0.01 mm/px on a 200 mm bed = 20000x20000 px,
# ~1.2 GB per frame) exhausts memory.
MAX_BED_IMAGE_PX = 25_000_000


def bed_raster_size(
    mm_per_px: float, bed_extent_mm: tuple[float, float, float, float]
) -> tuple[int, int]:
    """``(width, height)`` in px of the bed raster ``warp_to_bed`` builds for these inputs."""
    x0, y0, x1, y1 = bed_extent_mm
    return int(round((x1 - x0) / mm_per_px)), int(round((y1 - y0) / mm_per_px))


def bed_raster_error(
    mm_per_px: float, bed_extent_mm: tuple[float, float, float, float]
) -> str | None:
    """User-facing reason these raster inputs are unusable, or ``None`` when they are fine.

    Rejects a non-positive / non-finite scale, a reversed or empty extent (``x1 <= x0`` or
    ``y1 <= y0``), and a raster larger than :data:`MAX_BED_IMAGE_PX`.
    """
    import math

    if not (math.isfinite(mm_per_px) and mm_per_px > 0):
        return f"mm_per_px must be a positive number (got {mm_per_px:g})"
    x0, y0, x1, y1 = bed_extent_mm
    if not x1 > x0:
        return f"bed extent must have x1 > x0 (got x0={x0:g}, x1={x1:g})"
    if not y1 > y0:
        return f"bed extent must have y1 > y0 (got y0={y0:g}, y1={y1:g})"
    out_w, out_h = bed_raster_size(mm_per_px, bed_extent_mm)
    if out_w * out_h > MAX_BED_IMAGE_PX:
        w_mm, h_mm = x1 - x0, y1 - y0
        min_scale = math.ceil(math.sqrt(w_mm * h_mm / MAX_BED_IMAGE_PX) * 1000 - 1e-6) / 1000
        return (
            f"mm_per_px {mm_per_px:g} on a {w_mm:g}x{h_mm:g} mm bed makes a "
            f"{out_w}x{out_h} px image ({out_w * out_h / 1e6:.1f} MP); the limit is "
            f"{MAX_BED_IMAGE_PX / 1e6:g} MP, so use mm_per_px >= {min_scale:g}"
        )
    return None


def warp_to_bed(
    image: np.ndarray,
    h_matrix: np.ndarray,
    mm_per_px: float,
    bed_extent_mm: tuple[float, float, float, float],
) -> np.ndarray:
    """Warp a raw frame into a bed-plane raster at a fixed mm/px scale.

    `h_matrix` maps image pixels to bed-plane millimeters; `bed_extent_mm` is
    `(x0, y0, x1, y1)` in mm, and the output raster covers exactly that extent.
    Raises ``ValueError`` (see :func:`bed_raster_error`) rather than allocating an
    unusable or oversized raster.
    """
    import cv2

    problem = bed_raster_error(mm_per_px, bed_extent_mm)
    if problem is not None:
        raise ValueError(f"cannot build the bed image: {problem}")
    x0, y0, x1, y1 = bed_extent_mm
    out_w, out_h = bed_raster_size(mm_per_px, bed_extent_mm)
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


@dataclass(frozen=True)
class BoardSpec:
    """Calibration-board geometry driving detection + calibration.

    Two board kinds are supported (ChArUco preferred, checkerboard allowed):

    * ``"charuco"`` — uses ``squares_x``/``squares_y`` (number of chessboard
      SQUARES per side, the ``cv2.aruco.CharucoBoard`` convention),
      ``square_length_mm``, ``marker_length_mm``, and ``aruco_dict`` (a
      predefined-dictionary NAME, e.g. ``"DICT_4X4_50"``). The recoverable
      chessboard-corner count is ``(squares_x - 1) * (squares_y - 1)``.
    * ``"checkerboard"`` — uses ``cols``/``rows`` = the number of INNER corners
      per side (the ``cv2.findChessboardCorners`` convention, so the printed
      board has ``cols + 1`` by ``rows + 1`` squares) and ``square_size_mm``.
    """

    kind: Literal["charuco", "checkerboard"]
    # ChArUco fields.
    squares_x: int = 0
    squares_y: int = 0
    square_length_mm: float = 0.0
    marker_length_mm: float = 0.0
    aruco_dict: str = "DICT_4X4_50"
    # Checkerboard fields (cols/rows = number of INNER corners).
    cols: int = 0
    rows: int = 0
    square_size_mm: float = 0.0


@dataclass
class BoardDetection:
    """One view's detected board correspondences.

    ``image_points`` is ``Nx2`` float pixel coordinates; ``object_points`` is
    the matching ``Nx3`` float board coordinates in mm (Z=0, planar target);
    ``ids`` is ``Nx1`` int ChArUco corner ids, or ``None`` for a checkerboard
    (whose corners are dense and unlabelled).
    """

    image_points: np.ndarray
    object_points: np.ndarray
    ids: np.ndarray | None = None


def _aruco_dictionary(spec: BoardSpec) -> Any:
    """Build the predefined ``cv2.aruco`` dictionary named by ``spec.aruco_dict``."""
    import cv2.aruco as aruco

    return aruco.getPredefinedDictionary(getattr(aruco, spec.aruco_dict))


def _charuco_board(spec: BoardSpec) -> Any:
    """Build the ``cv2.aruco.CharucoBoard`` object described by ``spec``."""
    import cv2.aruco as aruco

    return aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y),
        spec.square_length_mm,
        spec.marker_length_mm,
        _aruco_dictionary(spec),
    )


def _to_gray(image: np.ndarray) -> np.ndarray:
    """Return a single-channel uint8 view of ``image`` (BGR->gray if needed)."""
    import cv2

    if image.ndim == 3:
        gray: np.ndarray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return gray
    return image


def _checkerboard_object_points(spec: BoardSpec) -> np.ndarray:
    """Planar (Z=0) mm object points for a ``cols x rows`` inner-corner grid."""
    grid = np.zeros((spec.rows * spec.cols, 3), np.float32)
    xy = np.mgrid[0 : spec.cols, 0 : spec.rows].T.reshape(-1, 2)
    grid[:, :2] = xy * spec.square_size_mm
    return grid


def detect_board(image: np.ndarray, spec: BoardSpec) -> BoardDetection | None:
    """Detect a calibration board in ``image``.

    Returns a ``BoardDetection`` on success, or ``None`` when no board is found
    (e.g. a blank frame) — never raises on an empty image. Checkerboard uses
    ``findChessboardCorners`` + ``cornerSubPix``; ChArUco uses the new-API
    ``CharucoDetector.detectBoard`` and ``CharucoBoard.matchImagePoints``.
    """
    import cv2

    gray = _to_gray(image)

    if spec.kind == "checkerboard":
        found, corners = cv2.findChessboardCorners(gray, (spec.cols, spec.rows))
        if not found or corners is None:
            return None
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
        refined = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)
        image_points = np.asarray(refined, np.float32).reshape(-1, 2)
        return BoardDetection(
            image_points=image_points,
            object_points=_checkerboard_object_points(spec),
            ids=None,
        )

    import cv2.aruco as aruco

    board = _charuco_board(spec)
    detector = aruco.CharucoDetector(board)
    charuco_corners, charuco_ids, _marker_corners, _marker_ids = detector.detectBoard(gray)
    if charuco_corners is None or charuco_ids is None or len(charuco_corners) < 4:
        return None
    object_points, image_points = board.matchImagePoints(charuco_corners, charuco_ids)
    if object_points is None or image_points is None or len(object_points) < 4:
        return None
    return BoardDetection(
        image_points=np.asarray(image_points, np.float32).reshape(-1, 2),
        object_points=np.asarray(object_points, np.float32).reshape(-1, 3),
        ids=np.asarray(charuco_ids, np.int32).reshape(-1, 1),
    )


def calibrate_intrinsics_boards(
    views: list[BoardDetection],
    spec: BoardSpec,
    image_size: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, float]:
    """Calibrate intrinsics + distortion from per-view board detections.

    ``views`` is a list of ``BoardDetection`` (one per calibration frame);
    ``image_size`` is ``(width, height)`` in pixels. Both board kinds resolve to
    per-view object/image correspondences fed to ``cv2.calibrateCamera`` (the
    new-API replacement for the removed ``calibrateCameraCharuco``). Returns
    ``(camera_matrix, dist_coeffs, rms)``.
    """
    import cv2

    if not views:
        raise ValueError("calibrate_intrinsics_boards requires at least one view")

    object_points = [np.asarray(v.object_points, np.float32).reshape(-1, 1, 3) for v in views]
    image_points = [np.asarray(v.image_points, np.float32).reshape(-1, 1, 2) for v in views]
    rms, k_matrix, dist_coeffs, _rvecs, _tvecs = cv2.calibrateCamera(
        object_points, image_points, image_size, None, None
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


def build_bed_remap(
    k_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    h_matrix: np.ndarray,
    mm_per_px: float,
    bed_extent_mm: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Precompute a fused undistort+homography remap for `cv2.remap` on the RAW frame.

    For each output bed-mm pixel, `h_matrix` (defined on undistorted-image
    coordinates) is inverted to find the undistorted-image pixel, then the
    camera model (`k_matrix`, `dist_coeffs`) is applied forward to find the
    corresponding pixel in the RAW, distorted source frame. `(map1, map2)`
    are `CV_32FC1` x/y source-pixel maps, one resampling instead of two.
    """
    import cv2

    x0, y0, x1, y1 = bed_extent_mm
    out_w = int(round((x1 - x0) / mm_per_px))
    out_h = int(round((y1 - y0) / mm_per_px))

    us, vs = np.meshgrid(np.arange(out_w, dtype=float), np.arange(out_h, dtype=float))
    xs_mm = x0 + us * mm_per_px
    ys_mm = y0 + vs * mm_per_px

    h_inv = np.linalg.inv(h_matrix)
    world_hom = np.stack([xs_mm.ravel(), ys_mm.ravel(), np.ones(xs_mm.size)], axis=1)
    undistorted_hom = (h_inv @ world_hom.T).T
    undistorted_px = undistorted_hom[:, :2] / undistorted_hom[:, 2:]

    k_inv = np.linalg.inv(k_matrix)
    undistorted_hom_px = np.hstack([undistorted_px, np.ones((len(undistorted_px), 1))])
    normalized = (k_inv @ undistorted_hom_px.T).T  # Nx3 camera-normalized points, z==1

    object_pts = normalized.astype(np.float32).reshape(-1, 1, 3)
    rvec = np.zeros(3)
    tvec = np.zeros(3)
    distorted_px, _ = cv2.projectPoints(object_pts, rvec, tvec, k_matrix, dist_coeffs)
    distorted_px = distorted_px.reshape(-1, 2)

    map1 = distorted_px[:, 0].reshape(out_h, out_w).astype(np.float32)
    map2 = distorted_px[:, 1].reshape(out_h, out_w).astype(np.float32)
    return map1, map2


def rigid_transform_2d(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Best-fit rigid transform (rotation + translation, NO scale) mapping `src` onto `dst`.

    Kabsch/Umeyama with scale DISABLED: returns `(R, t)` (a 2x2 proper rotation and a
    length-2 translation) minimizing ``sum ||R @ src_i + t - dst_i||^2``. Apply to row-vector
    point arrays as ``aligned = src @ R.T + t``.

    Scale is intentionally not a free parameter: for dimensional QA a real scale error must
    survive into the residual (so a separate scale gate can catch it) rather than be absorbed
    by the fit. See the dimensional-validation protocol, Section 5.1 (Analysis A).
    """
    src_a = np.asarray(src, float)
    dst_a = np.asarray(dst, float)
    mu_src = src_a.mean(axis=0)
    mu_dst = dst_a.mean(axis=0)
    src_c = src_a - mu_src
    dst_c = dst_a - mu_dst
    cov = src_c.T @ dst_c
    u_mat, _s, vt_mat = np.linalg.svd(cov)
    d = np.sign(np.linalg.det(vt_mat.T @ u_mat.T))
    correction = np.diag([1.0, d])
    r_mat = vt_mat.T @ correction @ u_mat.T
    t_vec = mu_dst - r_mat @ mu_src
    return r_mat, t_vec


def validate_dimensions(
    known_points_mm: np.ndarray, measured_points_mm: np.ndarray
) -> dict[str, Any]:
    """Compare `measured_points_mm` against `known_points_mm` (independent ground truth).

    Returns `{"rms_mm", "max_mm", "points": [{"known_mm", "measured_mm", "error_mm"}, ...]}`.
    """
    known = np.asarray(known_points_mm, float)
    measured = np.asarray(measured_points_mm, float)
    dists = np.sqrt(((measured - known) ** 2).sum(axis=1))
    points = [
        {
            "known_mm": known[i].tolist(),
            "measured_mm": measured[i].tolist(),
            "error_mm": float(dists[i]),
        }
        for i in range(len(known))
    ]
    return {
        "rms_mm": float(np.sqrt((dists**2).mean())),
        "max_mm": float(dists.max()),
        "points": points,
    }


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


def save_validation(path: Path, calibration_version: str, scale: dict[str, Any]) -> None:
    """Persist the latest scale-validation result, keyed to the calibration version it validated, so
    trust travels with the calibration (a stale validation for an older version does not count)."""
    Path(path).write_text(
        json.dumps({"calibration_version": calibration_version, "scale": scale}, indent=2),
        encoding="utf-8",
    )


def load_validation(path: Path) -> dict[str, Any] | None:
    """Read the stored validation record, or None when absent."""
    p = Path(path)
    if not p.exists():
        return None
    result: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return result


def calibration_validation_warning(
    calibration_version: str, validation: dict[str, Any] | None
) -> str | None:
    """Advisory warning when the active calibration has no PASSING scale validation. None = trusted.
    A validation for a different (older) calibration version does not count."""
    if validation is None or validation.get("calibration_version") != calibration_version:
        return "this calibration has not been validated against a certified board (run Validate)"
    if not (validation.get("scale") or {}).get("passed"):
        return "the last scale validation of this calibration did not pass its tolerance band"
    return None


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

    Stable call signature for the capture worker. When `calibration.camera_matrix`
    is present, takes the corrected path (undistort, then homography-only warp;
    `H` is defined on undistorted-image coordinates). Otherwise falls back to the
    homography-only path (back-compat with Phase-2 calibration files).
    """
    if calibration is None:
        return image, None
    if calibration.camera_matrix is not None:
        dist_coeffs = (
            calibration.dist_coeffs if calibration.dist_coeffs is not None else np.zeros(5)
        )
        source = undistort_image(image, calibration.camera_matrix, dist_coeffs)
    else:
        source = image
    registered = warp_to_bed(
        source, calibration.H, calibration.mm_per_px, calibration.bed_extent_mm
    )
    registered_space = {
        "mm_per_px": calibration.mm_per_px,
        "bed_extent_mm": list(calibration.bed_extent_mm),
    }
    return registered, registered_space
