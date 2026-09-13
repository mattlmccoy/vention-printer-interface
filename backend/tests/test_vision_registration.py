import json
import logging

import numpy as np

from vention_printer_interface.vision.registration import (
    Calibration,
    calibrate_intrinsics,
    compute_homography,
    load_calibration,
    register_frame,
    reprojection_error,
    save_calibration,
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
