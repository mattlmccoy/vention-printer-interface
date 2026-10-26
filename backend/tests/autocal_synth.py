"""Synthetic ground truth for the automatic calibration solve (test helper, not a test module).

The real ``cv2.aruco.CharucoBoard`` chessboard corners are projected with ``cv2.projectPoints``
through a known lens (focal length, principal point, distortion) for a camera looking straight
down from ``height_mm`` and translated along the machine's recoater axis (world +X) by each shift.
Nothing here is an invented measurement: every image point comes from cv2's own projection of
cv2's own board geometry, so the solve can be checked against the exact answer.

World frame: X = recoater (+mm), Y = across, Z up; the board lies face up on Z = 0. The board's own
frame (x along columns, y along rows) is image-handed, so board -> world is a rotation composed with
a y-flip. The bed frame the solve must produce is X = world X, Y = -world Y (image-handed), with the
origin at ChArUco corner id 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from vention_printer_interface.vision.autocal_solve import AutocalView
from vention_printer_interface.vision.registration import BoardSpec


@dataclass(frozen=True)
class GroundTruth:
    capture_mm: float
    board_to_bed: np.ndarray  # 2x2 proper rotation: bed = R @ (board_xy - board_xy[id0])
    origin_board_xy: np.ndarray
    board_scale: float = 1.0  # true board size / nominal (an engraving scale error)

    def bed_xy(self, object_points: np.ndarray) -> np.ndarray:
        """TRUE bed mm of nominal board points (the engraved board is ``board_scale`` x nominal)."""
        xy = np.asarray(object_points, float).reshape(-1, 3)[:, :2]
        out: np.ndarray = self.board_scale * (self.board_to_bed @ (xy - self.origin_board_xy).T).T
        return out


def _board(spec: BoardSpec):  # type: ignore[no-untyped-def]
    import cv2.aruco as aruco

    d = aruco.getPredefinedDictionary(getattr(aruco, spec.aruco_dict))
    return aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y), spec.square_length_mm, spec.marker_length_mm, d
    )


def synth_views(
    *,
    spec: BoardSpec,
    f: float = 1400.0,
    pp: tuple[float, float] = (972.0, 532.0),
    dist: tuple[float, float, float, float, float] = (-0.15, 0.05, 0.0005, -0.0003, 0.0),
    size: tuple[int, int] = (1920, 1080),
    height_mm: float = 120.0,
    board_rotation_deg: float = 0.0,
    camera_yaw_deg: float = 0.0,
    capture_mm: float = 463.3,
    shifts_mm: tuple[float, ...] = tuple(float(s) for s in range(-40, 41, 5)),
    encoder_scale: float = 1.0,
    board_scale: float = 1.0,
    board_offset_mm: tuple[float, float] = (0.0, 0.0),  # world XY: a second board placement
    placement: int = 0,
    noise_px: float = 0.05,
    seed: int = 7,
    with_markers: bool = False,
    # refined marker corners agree with chessboard corners to < 0.06 px on a cv2-rendered board
    # (tests/test_charuco_points.py, 2026-10-21)
    marker_noise_px: float = 0.05,
) -> tuple[list[AutocalView], GroundTruth]:
    import cv2

    board = _board(spec)
    obj = np.asarray(board.getChessboardCorners(), float).reshape(-1, 3)
    ids = np.arange(len(obj)).reshape(-1, 1)
    noise = np.full(len(obj), noise_px)
    if with_markers:  # every marker's 4 corners, ids per vision/charuco_points.py
        m_obj = [np.asarray(o, float).reshape(4, 3) for o in board.getObjPoints()]
        m_ids = np.asarray(board.getIds()).ravel()
        obj = np.vstack([obj, *m_obj])
        ids = np.vstack([ids, np.array([[1000 + 4 * int(m) + k] for m in m_ids for k in range(4)])])
        noise = np.concatenate([noise, np.full(4 * len(m_ids), marker_noise_px)])
    # Board centred under the camera at the capture pose.
    centre = np.asarray(board.getChessboardCorners(), float).reshape(-1, 3)[:, :2].mean(axis=0)
    th = math.radians(board_rotation_deg)
    rot = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    flip = np.diag([1.0, -1.0])
    b2w = rot @ flip  # board xy -> world xy (improper: board frame is image-handed)

    def to_world(p: np.ndarray) -> np.ndarray:
        xy = board_scale * (b2w @ (p[:, :2] - centre).T).T + np.asarray(board_offset_mm)
        return np.column_stack([xy, np.zeros(len(p))])

    # Camera looking down (-Z); image x = world +X rotated by yaw about the optical axis.
    yaw = math.radians(camera_yaw_deg)
    x_c = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    z_c = np.array([0.0, 0.0, -1.0])
    y_c = np.cross(z_c, x_c)
    r_cw = np.vstack([x_c, y_c, z_c])  # world -> camera rotation (rows = camera axes in world)
    k = np.array([[f, 0, pp[0]], [0, f, pp[1]], [0, 0, 1]], float)
    rng = np.random.default_rng(seed)
    pw = to_world(obj)
    views: list[AutocalView] = []
    for s in shifts_mm:
        cam_c = np.array([s, 0.0, height_mm])
        pc = (r_cw @ (pw - cam_c).T).T
        img, _ = cv2.projectPoints(pc, np.zeros(3), np.zeros(3), k, np.asarray(dist, float))
        img = img.reshape(-1, 2) + rng.normal(0.0, 1.0, (len(obj), 2)) * noise[:, None]
        inside = (img[:, 0] >= 0) & (img[:, 0] < size[0]) & (img[:, 1] >= 0) & (img[:, 1] < size[1])
        if not inside.any():
            continue
        views.append(AutocalView(
            recoater_mm=round(capture_mm + s * encoder_scale, 3),
            image_points=img[inside], object_points=obj[inside], ids=ids[inside],
            placement=placement,
        ))
    # bed = (Xw - Xw0, -(Yw - Yw0)) = flip @ b2w @ (board - board0) -> a proper rotation of board xy
    board_to_bed = flip @ b2w
    return views, GroundTruth(capture_mm, board_to_bed, obj[0, :2].copy(), board_scale)
