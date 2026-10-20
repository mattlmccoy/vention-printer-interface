"""Unit tests for the calibration coverage grid (pure, no hardware)."""

from __future__ import annotations

from vention_printer_interface.vision.coverage import CoverageState, coverage


def _det(cx: float, cy: float, tilt: float) -> dict:
    # Minimal descriptor: image-space centroid (px), out-of-plane tilt (deg), frame size (px).
    return {"centroid_px": (cx, cy), "tilt_deg": tilt, "image_size": (900, 600)}


def test_enough_requires_all_cells_and_tilt_diversity() -> None:
    # One centred, fronto-parallel view: one cell + one tilt bin -> NOT enough, with gaps.
    st = coverage([_det(450, 300, 0)], grid=(3, 3), tilt_bins=3, min_views=6)
    assert isinstance(st, CoverageState)
    assert st.enough is False and len(st.gaps) > 0

    # Nine cells across three tilt bins, >= min_views -> enough, no gaps.
    dets = []
    for gx in range(3):
        for gy in range(3):
            dets.append(_det(150 + gx * 300, 100 + gy * 200, [0.0, 15.0, 30.0][(gx + gy) % 3]))
    st2 = coverage(dets, grid=(3, 3), tilt_bins=3, min_views=6)
    assert st2.enough is True and st2.gaps == []
    assert st2.cells_filled == 9 and st2.tilt_bins_filled == 3


def test_all_cells_but_no_tilt_diversity_is_not_enough() -> None:
    # Every cell hit but all fronto-parallel (one tilt bin) -> intrinsics need tilts -> not enough.
    dets = [_det(150 + gx * 300, 100 + gy * 200, 0.0) for gx in range(3) for gy in range(3)]
    st = coverage(dets, grid=(3, 3), tilt_bins=3, min_views=6)
    assert st.enough is False
    assert any("tilt" in g for g in st.gaps)


def test_gaps_name_the_missing_cells() -> None:
    # Only the top-left cell (r1c1) filled -> it is NOT a gap; the other cells are.
    st = coverage([_det(150, 100, 0.0)], grid=(3, 3), tilt_bins=3, min_views=1)
    assert st.cells_filled == 1
    assert "r1c1" not in st.gaps       # filled
    assert "r2c2" in st.gaps and "r3c3" in st.gaps  # missing cells named (1-indexed)


# ---- corner coverage (2026-10-20): count the cells where CORNERS land, not the board centre ----
# A board that fills most of the frame can never put its centre in an edge cell (Matt's 13-view run
# stayed at 1/9 cells), but its corners already cover most of the frame in one view.
import numpy as np  # noqa: E402

from vention_printer_interface.vision.coverage import corner_cells  # noqa: E402


def _grid_corners(x0: float, y0: float, x1: float, y1: float, n: int = 3) -> np.ndarray:
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    return np.array([(x, y) for y in ys for x in xs], float)


def _cdet(corners: np.ndarray, tilt: float) -> dict:
    c = corners.mean(axis=0)
    return {"centroid_px": (float(c[0]), float(c[1])), "tilt_deg": tilt,
            "image_size": (900, 600), "corners_px": corners.tolist()}


def test_one_frame_filling_board_covers_many_cells() -> None:
    big = _grid_corners(60, 40, 840, 560)  # 3x3 corners spanning the frame
    cells = corner_cells([big], (900, 600))
    assert sum(c for row in cells for c in row) == 9
    st = coverage([_cdet(big, 0.0)], grid=(3, 3), tilt_bins=3, min_views=1)
    assert st.cells_filled == 9


def test_manual_gate_needs_six_views_six_cells_two_tilts() -> None:
    six_cells = _grid_corners(60, 40, 840, 290)  # top two rows only -> 6 cells
    dets = [_cdet(six_cells, [0.0, 15.0][i % 2]) for i in range(6)]
    assert coverage(dets).enough is True
    assert coverage(dets[:5]).enough is False  # 5 views
    assert coverage([_cdet(six_cells, 0.0)] * 6).enough is False  # one tilt range
    five_cells = np.vstack([_grid_corners(60, 40, 840, 40), _grid_corners(60, 290, 450, 290)])
    assert coverage([_cdet(five_cells, [0.0, 15.0][i % 2]) for i in range(6)]).enough is False


def test_old_descriptors_without_corners_still_count_their_centroid_cell() -> None:
    st = coverage([_det(150, 100, 0.0)], grid=(3, 3), tilt_bins=3, min_views=1)
    assert st.cells_filled == 1 and "r1c1" not in st.gaps
