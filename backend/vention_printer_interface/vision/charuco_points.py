"""Every identified point on a ChArUco board: chessboard corners AND ArUco marker corners.

The first automatic calibration used only the interior chessboard corners: 9 on the 4x4 board,
spanning 16-48 mm of the 64 mm pattern, so only the middle third of the photo was calibrated. Each
ArUco marker's four corners also have known board positions (``CharucoBoard.getObjPoints()``) and an
identity (the marker id), which a plain checkerboard cannot offer: 32 more points on that board,
spanning 2-62 mm, still found when much of the board is out of view.

Identity is never guessed: a chessboard corner keeps its ChArUco id (0..N-1); marker corner k of
marker m gets ``MARKER_ID_BASE + 4*m + k`` in ``getObjPoints`` order. Board coordinates come only
from the cv2 board, so both kinds share one frame. OpenCV 5's ``CharucoBoard.matchImagePoints``
refuses marker corners, so they are matched by marker id here. Marker corners are refined with
``cornerSubPix`` before use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vention_printer_interface.vision.registration import BoardSpec, _charuco_board, _to_gray

MARKER_ID_BASE = 1000
_SUBPIX_WIN = (5, 5)


@dataclass(frozen=True)
class BoardPoints:
    image_points: np.ndarray  # Nx2 px
    object_points: np.ndarray  # Nx3 board mm (Z = 0)
    ids: np.ndarray  # Nx1 int (chessboard corner id, or MARKER_ID_BASE + 4*marker + k)
    kinds: np.ndarray  # N of "corner" | "marker"
    markers_px: list[np.ndarray]  # detected marker outlines (4x2 px each), for drawing


def detect_board_points(image: np.ndarray, spec: BoardSpec) -> BoardPoints | None:
    """All identified points in ``image``, or ``None`` when no board point is found."""
    import cv2
    import cv2.aruco as aruco

    gray = _to_gray(image)
    board = _charuco_board(spec)
    corners, corner_ids, marker_corners, marker_ids = aruco.CharucoDetector(board).detectBoard(gray)
    img_pts: list[np.ndarray] = []
    obj_pts: list[np.ndarray] = []
    ids: list[int] = []
    kinds: list[str] = []

    if corners is not None and corner_ids is not None and len(corner_ids):
        chess = np.asarray(board.getChessboardCorners(), float).reshape(-1, 3)
        for p, i in zip(np.asarray(corners, float).reshape(-1, 2),
                        np.asarray(corner_ids).ravel(), strict=True):
            img_pts.append(p)
            obj_pts.append(chess[int(i)])
            ids.append(int(i))
            kinds.append("corner")

    outlines: list[np.ndarray] = []
    if marker_ids is not None and len(marker_ids):
        board_obj = {int(m): np.asarray(o, float).reshape(4, 3)
                     for m, o in zip(np.asarray(board.getIds()).ravel(), board.getObjPoints(),
                                     strict=True)}
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 0.01)
        for quad, m in zip(marker_corners, np.asarray(marker_ids).ravel(), strict=True):
            m = int(m)
            if m not in board_obj:
                continue  # a marker from the dictionary that is not on this board
            pts = np.asarray(quad, np.float32).reshape(-1, 1, 2)
            refined = cv2.cornerSubPix(gray, pts.copy(), _SUBPIX_WIN, (-1, -1), criteria)
            refined = refined.reshape(4, 2).astype(float)
            outlines.append(refined)
            for k in range(4):
                img_pts.append(refined[k])
                obj_pts.append(board_obj[m][k])
                ids.append(MARKER_ID_BASE + 4 * m + k)
                kinds.append("marker")

    if not img_pts:
        return None
    return BoardPoints(
        image_points=np.asarray(img_pts, float).reshape(-1, 2),
        object_points=np.asarray(obj_pts, float).reshape(-1, 3),
        ids=np.asarray(ids, np.int64).reshape(-1, 1),
        kinds=np.asarray(kinds),
        markers_px=outlines,
    )
