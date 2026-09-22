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
