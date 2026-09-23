import json
import logging

import numpy as np

from vention_printer_interface.vision.registration import (
    BoardDetection,
    BoardSpec,
    Calibration,
    build_bed_remap,
    calibrate_intrinsics,
    calibrate_intrinsics_boards,
    compute_homography,
    detect_board,
    load_calibration,
    register_frame,
    reprojection_error,
    rigid_transform_2d,
    save_calibration,
    undistort_image,
    undistort_points,
    validate_dimensions,
    warp_to_bed,
)


def test_recovers_known_homography():
    world = np.array([[0, 0], [100, 0], [100, 80], [0, 80], [50, 40]], float)  # mm
    h_true = np.array([[2.0, 0.1, 30.0], [0.0, 2.0, 20.0], [0.0, 0.0, 1.0]])
    hom = np.hstack([world, np.ones((len(world), 1))])
    proj = (h_true @ hom.T).T
    image_pts = proj[:, :2] / proj[:, 2:]
    h_computed = compute_homography(image_pts, world)  # image->world
    err = reprojection_error(h_computed, image_pts, world)
    assert err < 1e-6


def test_warp_output_dimensions():
    img = np.zeros((480, 640, 3), np.uint8)
    h_identity = np.eye(3)  # image coords already == mm for this test
    bed = warp_to_bed(img, h_identity, mm_per_px=0.5, bed_extent_mm=(0, 0, 100, 80))
    assert bed.shape == (160, 200, 3)  # 80/0.5=160 rows, 100/0.5=200 cols
    assert bed.dtype == np.uint8


def test_calibration_round_trip(tmp_path):
    calib = Calibration(
        H=np.array([[2.0, 0.1, 30.0], [0.0, 2.0, 20.0], [0.0, 0.0, 1.0]]),
        mm_per_px=0.5,
        bed_extent_mm=(0.0, 0.0, 100.0, 80.0),
        version="v1",
        reprojection_error=0.01,
    )
    path = tmp_path / ".vision_calibration.json"
    save_calibration(path, calib)

    loaded = load_calibration(path)

    assert loaded is not None
    assert np.allclose(loaded.H, calib.H)
    assert loaded.mm_per_px == calib.mm_per_px
    assert loaded.bed_extent_mm == calib.bed_extent_mm
    assert isinstance(loaded.bed_extent_mm, tuple)
    assert loaded.version == calib.version
    assert loaded.reprojection_error == calib.reprojection_error


def test_load_calibration_returns_none_when_missing(tmp_path):
    assert load_calibration(tmp_path / "does_not_exist.json") is None


def test_register_frame_passes_through_when_no_calibration():
    img = np.zeros((10, 10, 3), np.uint8)
    img[0, 0] = (1, 2, 3)
    registered, space = register_frame(img, None)
    assert registered is img
    assert space is None


def test_register_frame_warps_via_homography_when_calibrated():
    img = np.zeros((480, 640, 3), np.uint8)
    calib = Calibration(
        H=np.eye(3),
        mm_per_px=0.5,
        bed_extent_mm=(0.0, 0.0, 100.0, 80.0),
        version="v1",
        reprojection_error=0.01,
    )
    registered, space = register_frame(img, calib)
    assert registered.shape == (160, 200, 3)
    assert registered.dtype == np.uint8
    assert space == {"mm_per_px": 0.5, "bed_extent_mm": [0.0, 0.0, 100.0, 80.0]}


def test_calibration_round_trip_with_intrinsics(tmp_path):
    k_matrix = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
    dist = np.array([0.01, -0.02, 0.0, 0.0, 0.0])
    calib = Calibration(
        H=np.eye(3),
        mm_per_px=0.5,
        bed_extent_mm=(0.0, 0.0, 100.0, 80.0),
        version="v2",
        reprojection_error=0.01,
        camera_matrix=k_matrix,
        dist_coeffs=dist,
        distortion_model="opencv-5",
        image_size=(640, 480),
        validation={"rms_mm": 0.2, "points": []},
    )
    path = tmp_path / ".vision_calibration.json"
    save_calibration(path, calib)

    loaded = load_calibration(path)

    assert loaded is not None
    assert loaded.camera_matrix is not None
    assert np.allclose(loaded.camera_matrix, k_matrix)
    assert loaded.dist_coeffs is not None
    assert np.allclose(loaded.dist_coeffs, dist)
    assert loaded.distortion_model == "opencv-5"
    assert loaded.image_size == (640, 480)
    assert loaded.validation == {"rms_mm": 0.2, "points": []}


def test_load_calibration_back_compat_without_intrinsics(tmp_path, caplog):
    """Phase-2 `.vision_calibration.json` files predate the intrinsics fields."""
    old_payload = {
        "H": [[2.0, 0.1, 30.0], [0.0, 2.0, 20.0], [0.0, 0.0, 1.0]],
        "mm_per_px": 0.5,
        "bed_extent_mm": [0.0, 0.0, 100.0, 80.0],
        "version": "v1",
        "reprojection_error": 0.01,
    }
    path = tmp_path / ".vision_calibration.json"
    path.write_text(json.dumps(old_payload), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = load_calibration(path)

    assert loaded is not None
    assert loaded.camera_matrix is None
    assert loaded.dist_coeffs is None
    assert loaded.distortion_model == "opencv-5"
    assert loaded.image_size is None
    assert loaded.validation == {}
    assert any("intrinsics" in rec.message.lower() for rec in caplog.records)


def test_calibrate_intrinsics_recovers_known_camera_matrix():
    import cv2

    k_true = np.array([[900.0, 0.0, 320.0], [0.0, 900.0, 240.0], [0.0, 0.0, 1.0]])
    dist_true = np.zeros(5)
    image_size = (640, 480)

    grid_x, grid_y = np.meshgrid(np.arange(7, dtype=float), np.arange(5, dtype=float))
    object_pts = np.stack([grid_x.ravel(), grid_y.ravel(), np.zeros(grid_x.size)], axis=1) * 20.0

    poses = [
        (np.array([0.1, -0.2, 0.05]), np.array([-60.0, -40.0, 400.0])),
        (np.array([-0.15, 0.1, 0.1]), np.array([-50.0, -30.0, 450.0])),
        (np.array([0.05, 0.15, -0.1]), np.array([-70.0, -50.0, 420.0])),
        (np.array([0.2, 0.0, 0.0]), np.array([-40.0, -35.0, 380.0])),
    ]

    object_points = []
    image_points = []
    for rvec, tvec in poses:
        projected, _ = cv2.projectPoints(object_pts, rvec, tvec, k_true, dist_true)
        image_points.append(projected.reshape(-1, 2))
        object_points.append(object_pts.astype(np.float32))

    k_computed, dist_computed, rms = calibrate_intrinsics(object_points, image_points, image_size)

    assert rms < 1.0
    assert np.isclose(k_computed[0, 0], k_true[0, 0], rtol=0.05)
    assert np.isclose(k_computed[1, 1], k_true[1, 1], rtol=0.05)
    assert np.isclose(k_computed[0, 2], k_true[0, 2], atol=15)
    assert np.isclose(k_computed[1, 2], k_true[1, 2], atol=15)
    assert dist_computed.size == 5


def test_undistort_image_with_zero_distortion_matches_input():
    img = np.random.default_rng(0).integers(0, 255, (48, 64, 3), dtype=np.uint8)
    k_matrix = np.array([[100.0, 0.0, 32.0], [0.0, 100.0, 24.0], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)

    result = undistort_image(img, k_matrix, dist)

    assert result.shape == img.shape
    assert result.dtype == np.uint8
    assert np.allclose(result, img, atol=2)


def test_undistort_points_with_zero_distortion_matches_input():
    k_matrix = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    pts = np.array([[100.0, 150.0], [320.0, 240.0], [500.0, 400.0]])

    result = undistort_points(pts, k_matrix, dist)

    assert result.shape == pts.shape
    assert np.allclose(result, pts, atol=1e-3)


def test_build_bed_remap_output_dimensions():
    k_matrix = np.array([[100.0, 0.0, 32.0], [0.0, 100.0, 24.0], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    h_identity = np.eye(3)

    map1, map2 = build_bed_remap(
        k_matrix, dist, h_identity, mm_per_px=0.5, bed_extent_mm=(0, 0, 100, 80)
    )

    assert map1.shape == (160, 200)
    assert map2.shape == (160, 200)
    assert map1.dtype == np.float32
    assert map2.dtype == np.float32


def test_validate_dimensions_computes_rms_and_max_error():
    known = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    measured = np.array([[0.1, 0.0], [10.0, -0.2], [10.3, 10.0], [0.0, 9.8]])
    expected_dists = np.sqrt(((measured - known) ** 2).sum(axis=1))

    result = validate_dimensions(known, measured)

    assert np.isclose(result["rms_mm"], np.sqrt((expected_dists**2).mean()))
    assert np.isclose(result["max_mm"], expected_dists.max())
    assert len(result["points"]) == 4
    assert result["points"][0]["known_mm"] == [0.0, 0.0]
    assert result["points"][0]["measured_mm"] == [0.1, 0.0]
    assert np.isclose(result["points"][0]["error_mm"], expected_dists[0])


def test_validate_dimensions_zero_error_for_identical_points():
    pts = np.array([[0.0, 0.0], [5.0, 5.0]])

    result = validate_dimensions(pts, pts)

    assert result["rms_mm"] == 0.0
    assert result["max_mm"] == 0.0


def test_register_frame_corrected_path_matches_homography_only_when_no_distortion():
    """With camera_matrix=eye/dist=zeros, undistort is an identity map, so the
    corrected (undistort + warp) path must equal the homography-only path.
    """
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8).astype(np.uint8)
    h_matrix = np.eye(3)

    calib_homography_only = Calibration(
        H=h_matrix,
        mm_per_px=1.0,
        bed_extent_mm=(0.0, 0.0, 96.0, 64.0),
        version="v1",
        reprojection_error=0.0,
    )
    calib_corrected = Calibration(
        H=h_matrix,
        mm_per_px=1.0,
        bed_extent_mm=(0.0, 0.0, 96.0, 64.0),
        version="v2",
        reprojection_error=0.0,
        camera_matrix=np.eye(3),
        dist_coeffs=np.zeros(5),
        image_size=(96, 64),
    )

    registered_plain, space_plain = register_frame(img, calib_homography_only)
    registered_corrected, space_corrected = register_frame(img, calib_corrected)

    assert registered_plain.shape == registered_corrected.shape
    assert registered_plain.dtype == registered_corrected.dtype == np.uint8
    assert np.allclose(
        registered_plain.astype(float), registered_corrected.astype(float), atol=1.0
    )
    assert space_plain == space_corrected


def test_register_frame_passes_through_uncalibrated_distortion_field():
    """Calibration without intrinsics (back-compat) must take the homography-only path."""
    img = np.zeros((64, 96, 3), np.uint8)
    calib = Calibration(
        H=np.eye(3),
        mm_per_px=1.0,
        bed_extent_mm=(0.0, 0.0, 96.0, 64.0),
        version="v1",
        reprojection_error=0.0,
    )
    registered, _space = register_frame(img, calib)
    assert calib.camera_matrix is None
    assert registered.shape == (64, 96, 3)


def test_register_frame_applies_undistortion_when_distortion_present():
    """Distortion must actually be applied, not silently ignored, when calibration carries it."""
    rng = np.random.default_rng(3)
    img = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8).astype(np.uint8)
    k_matrix = np.array([[80.0, 0.0, 48.0], [0.0, 80.0, 32.0], [0.0, 0.0, 1.0]])
    dist = np.array([0.15, -0.05, 0.0, 0.0, 0.0])  # meaningful barrel distortion
    h_matrix = np.eye(3)
    bed_extent = (0.0, 0.0, 96.0, 64.0)
    calib = Calibration(
        H=h_matrix,
        mm_per_px=1.0,
        bed_extent_mm=bed_extent,
        version="v3",
        reprojection_error=0.0,
        camera_matrix=k_matrix,
        dist_coeffs=dist,
        image_size=(96, 64),
    )

    registered, _space = register_frame(img, calib)
    expected = warp_to_bed(undistort_image(img, k_matrix, dist), h_matrix, 1.0, bed_extent)
    homography_only = warp_to_bed(img, h_matrix, 1.0, bed_extent)

    assert np.allclose(registered.astype(float), expected.astype(float), atol=1e-6)
    # must differ meaningfully from the naive homography-only path -- proves
    # distortion correction is actually exercised, not silently skipped
    assert np.abs(registered.astype(float) - homography_only.astype(float)).mean() > 1.0


def test_build_bed_remap_agrees_with_two_step_undistort_then_warp():
    import cv2

    rng = np.random.default_rng(2)
    img = rng.integers(0, 255, (64, 96, 3), dtype=np.uint8).astype(np.uint8)
    k_matrix = np.array([[80.0, 0.0, 48.0], [0.0, 80.0, 32.0], [0.0, 0.0, 1.0]])
    dist = np.zeros(5)
    h_matrix = np.eye(3)
    mm_per_px = 1.0
    bed_extent = (0.0, 0.0, 96.0, 64.0)

    undistorted = undistort_image(img, k_matrix, dist)
    two_step = warp_to_bed(undistorted, h_matrix, mm_per_px, bed_extent)

    map1, map2 = build_bed_remap(k_matrix, dist, h_matrix, mm_per_px, bed_extent)
    fused = cv2.remap(img, map1, map2, interpolation=cv2.INTER_LINEAR)

    assert fused.shape == two_step.shape
    diff = np.abs(fused.astype(float) - two_step.astype(float))
    assert diff.mean() < 5.0


# --- Board-based intrinsic calibration (A6a): ChArUco + checkerboard --------
#
# All fixtures below are rendered from the REAL installed cv2/cv2.aruco so the
# test asserts against the library's own geometry, not an invented shape.

_CHARUCO_SPEC = BoardSpec(
    kind="charuco",
    squares_x=7,
    squares_y=5,
    square_length_mm=20.0,
    marker_length_mm=15.0,
    aruco_dict="DICT_5X5_100",
)
# checkerboard cols/rows count INNER corners (findChessboardCorners convention).
_CHECKER_SPEC = BoardSpec(kind="checkerboard", cols=6, rows=4, square_size_mm=20.0)


def _render_charuco_image(spec: BoardSpec, size: tuple[int, int] = (700, 500)) -> np.ndarray:
    import cv2.aruco as aruco

    dictionary = aruco.getPredefinedDictionary(getattr(aruco, spec.aruco_dict))
    board = aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y),
        spec.square_length_mm,
        spec.marker_length_mm,
        dictionary,
    )
    img: np.ndarray = board.generateImage(size, marginSize=40)
    return img


def _render_checkerboard_image(spec: BoardSpec, square_px: int = 40) -> np.ndarray:
    border = square_px
    n_cols_sq = spec.cols + 1  # squares = inner corners + 1
    n_rows_sq = spec.rows + 1
    width = n_cols_sq * square_px + 2 * border
    height = n_rows_sq * square_px + 2 * border
    img = np.full((height, width), 255, np.uint8)
    for r in range(n_rows_sq):
        for c in range(n_cols_sq):
            if (r + c) % 2 == 0:
                y0 = border + r * square_px
                x0 = border + c * square_px
                img[y0 : y0 + square_px, x0 : x0 + square_px] = 0
    return img


def _warped_views(base: np.ndarray, n: int, seed: int = 0) -> list[np.ndarray]:
    import cv2

    rng = np.random.default_rng(seed)
    h, w = base.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    views: list[np.ndarray] = []
    for _ in range(n):
        jitter = rng.uniform(-30, 30, (4, 2)).astype(np.float32)
        dst = src + jitter
        m = cv2.getPerspectiveTransform(src, dst)
        views.append(cv2.warpPerspective(base, m, (w, h), borderValue=255))
    return views


def test_detect_charuco_board_corners_and_ids():
    img = _render_charuco_image(_CHARUCO_SPEC)
    det = detect_board(img, _CHARUCO_SPEC)
    assert det is not None
    expected = (_CHARUCO_SPEC.squares_x - 1) * (_CHARUCO_SPEC.squares_y - 1)
    assert det.image_points.shape == (expected, 2)
    assert det.object_points.shape == (expected, 3)
    assert det.ids is not None
    assert det.ids.shape[0] == expected


def test_detect_checkerboard_inner_corners():
    img = _render_checkerboard_image(_CHECKER_SPEC)
    det = detect_board(img, _CHECKER_SPEC)
    assert det is not None
    expected = _CHECKER_SPEC.cols * _CHECKER_SPEC.rows
    assert det.image_points.shape == (expected, 2)
    assert det.object_points.shape == (expected, 3)
    assert det.ids is None


def test_calibrate_intrinsics_boards_charuco():
    base = _render_charuco_image(_CHARUCO_SPEC)
    h, w = base.shape[:2]
    views: list[BoardDetection] = []
    for img in _warped_views(base, 6, seed=1):
        det = detect_board(img, _CHARUCO_SPEC)
        if det is not None:
            views.append(det)
    assert len(views) >= 4
    k_matrix, dist, rms = calibrate_intrinsics_boards(views, _CHARUCO_SPEC, (w, h))
    assert k_matrix.shape == (3, 3)
    assert np.all(np.isfinite(k_matrix))
    assert np.isfinite(rms)
    assert rms < 5.0


def test_calibrate_intrinsics_boards_checkerboard():
    base = _render_checkerboard_image(_CHECKER_SPEC)
    h, w = base.shape[:2]
    views: list[BoardDetection] = []
    for img in _warped_views(base, 6, seed=2):
        det = detect_board(img, _CHECKER_SPEC)
        if det is not None:
            views.append(det)
    assert len(views) >= 4
    k_matrix, dist, rms = calibrate_intrinsics_boards(views, _CHECKER_SPEC, (w, h))
    assert k_matrix.shape == (3, 3)
    assert np.all(np.isfinite(k_matrix))
    assert np.isfinite(rms)
    assert rms < 5.0


def test_detect_board_blank_returns_none():
    blank = np.full((500, 700), 255, np.uint8)
    assert detect_board(blank, _CHARUCO_SPEC) is None
    assert detect_board(blank, _CHECKER_SPEC) is None


# --- rigid (rotation+translation, NO scale) best-fit helper (validation alignment) ---


def test_rigid_transform_2d_recovers_known_rotation_and_translation():
    rng = np.random.default_rng(0)
    src = rng.uniform(-50.0, 50.0, (12, 2))
    theta = 0.3
    r_true = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    t_true = np.array([10.0, -5.0])
    dst = src @ r_true.T + t_true

    r_fit, t_fit = rigid_transform_2d(src, dst)

    assert np.allclose(r_fit, r_true, atol=1e-6)
    assert np.allclose(t_fit, t_true, atol=1e-6)
    aligned = src @ r_fit.T + t_fit
    assert np.allclose(aligned, dst, atol=1e-6)


def test_rigid_transform_2d_does_not_absorb_scale():
    """A no-scale fit must leave a scale error in the residual (so a scale gate can catch it),
    and its rotation must stay a proper orthonormal rotation (det +1, no scale baked in)."""
    rng = np.random.default_rng(1)
    src = rng.uniform(-50.0, 50.0, (20, 2))
    dst = src * 1.10  # pure scale about the origin

    r_fit, t_fit = rigid_transform_2d(src, dst)

    assert np.allclose(r_fit @ r_fit.T, np.eye(2), atol=1e-6)
    assert np.isclose(np.linalg.det(r_fit), 1.0, atol=1e-6)
    aligned = src @ r_fit.T + t_fit
    residual = np.sqrt(((aligned - dst) ** 2).sum(axis=1)).mean()
    assert residual > 1.0  # scale NOT removed by a rigid fit


# ---- bed-raster bounds (fix/charuco-board-calibrate) -----------------------------------------
def test_bed_raster_error_accepts_a_sane_raster() -> None:
    from vention_printer_interface.vision.registration import bed_raster_error, bed_raster_size

    assert bed_raster_size(0.5, (0.0, 0.0, 200.0, 200.0)) == (400, 400)
    assert bed_raster_error(0.5, (0.0, 0.0, 200.0, 200.0)) is None
    assert bed_raster_error(0.05, (0.0, 0.0, 200.0, 200.0)) is None  # 4000x4000 = 16 MP


def test_bed_raster_error_rejects_reversed_or_empty_extent() -> None:
    from vention_printer_interface.vision.registration import bed_raster_error

    assert "x1" in (bed_raster_error(0.5, (10.0, 0.0, 10.0, 80.0)) or "")
    assert "y1" in (bed_raster_error(0.5, (0.0, 80.0, 100.0, 0.0)) or "")


def test_bed_raster_error_rejects_non_positive_scale() -> None:
    from vention_printer_interface.vision.registration import bed_raster_error

    for bad in (0.0, -1.0, float("nan"), float("inf")):
        assert "positive" in (bed_raster_error(bad, (0.0, 0.0, 100.0, 100.0)) or "")


def test_bed_raster_error_explains_an_oversized_raster_and_the_minimum_scale() -> None:
    from vention_printer_interface.vision.registration import MAX_BED_IMAGE_PX, bed_raster_error

    assert MAX_BED_IMAGE_PX == 25_000_000
    msg = bed_raster_error(0.01, (0.0, 0.0, 200.0, 200.0))
    assert msg is not None
    assert "20000x20000" in msg and "400" in msg  # size in px and megapixels
    assert "0.04" in msg  # smallest mm/px that fits the 25 MP cap on a 200x200 mm bed


def test_warp_to_bed_refuses_an_oversized_raster_instead_of_allocating_it() -> None:
    """A calibration saved before the finalize bounds existed must not OOM every capture."""
    import pytest

    img = np.zeros((48, 64, 3), np.uint8)
    with pytest.raises(ValueError, match="20000x20000"):
        warp_to_bed(img, np.eye(3), mm_per_px=0.01, bed_extent_mm=(0, 0, 200, 200))
