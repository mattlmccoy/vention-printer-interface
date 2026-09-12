import numpy as np

from vention_printer_interface.vision.registration import compute_homography, reprojection_error


def test_recovers_known_homography():
    world = np.array([[0, 0], [100, 0], [100, 80], [0, 80], [50, 40]], float)  # mm
    h_true = np.array([[2.0, 0.1, 30.0], [0.0, 2.0, 20.0], [0.0, 0.0, 1.0]])
    hom = np.hstack([world, np.ones((len(world), 1))])
    proj = (h_true @ hom.T).T
    image_pts = proj[:, :2] / proj[:, 2:]
    h_computed = compute_homography(image_pts, world)  # image->world
    err = reprojection_error(h_computed, image_pts, world)
    assert err < 1e-6
