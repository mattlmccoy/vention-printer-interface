"""Absolute corner labels for a certified-chessboard sweep (vision/plate_labels.py).

A plain chessboard has no IDs and the plate runs off the photo as the camera sweeps, so each
photo's detector grid is only known up to orientation and an integer shift. Fixtures are REAL
detections of crops of the 2026-10-27 plate photo (validations/cal-20261027T175542Z/
20261027T175712265073Z/raw.jpg, 5120 x 3840). Shifting the crop window by k px stands in for the
camera moving k px along the sweep: the pixels are real, the MOTION is synthetic (no real plate
sweep exists yet). Crop (600, 3000) came back transposed (16 x 17), as the real detector does.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vention_printer_interface.vision.plate_labels import PlateView, label_plate_sweep, orient_grid

FIX = Path(__file__).parent / "fixtures" / "plate_sweep" / "plate_crops_20261027.npz"
PX_MM = 0.0247  # science camera at 5120 x 3840 (cal-20261027T175542Z provenance px_mm)
CAPTURE_MM = 463.7
CROPS = [(0, 3600), (120, 3600), (240, 3600), (600, 3000), (840, 3000)]


def _crop(y0: int, h: int) -> tuple[np.ndarray, np.ndarray]:
    d = np.load(FIX)
    return d[f"y{y0}_h{h}_points"], d[f"y{y0}_h{h}_grid"]


def _view(y0: int, h: int, *, error_mm: float = 0.0) -> PlateView:
    pts, grid = _crop(y0, h)
    return PlateView(recoater_mm=CAPTURE_MM + y0 * PX_MM + error_mm, points=pts, grid=grid)


def _truth() -> tuple[np.ndarray, np.ndarray]:
    """Full-photo labels: the crop at y0 = 0 sees all 289 corners."""
    pts, grid = _crop(0, 3600)
    return pts, orient_grid(pts, grid)


def _labels_match_truth(view: PlateView, y0: int, ids: np.ndarray) -> bool:
    tpts, tlab = _truth()
    full = view.points + np.array([0.0, y0])  # back into whole-photo pixels
    for p, i in zip(full, np.asarray(ids).ravel(), strict=True):
        k = int(np.argmin(np.linalg.norm(tpts - p, axis=1)))
        if np.linalg.norm(tpts[k] - p) > 5 or int(tlab[k, 1]) * 17 + int(tlab[k, 0]) != int(i):
            return False
    return True


def test_orientation_does_not_depend_on_how_the_detector_numbered_the_grid() -> None:
    pts, grid = _crop(0, 3600)
    want = orient_grid(pts, grid)
    n = 16
    for flip_c in (False, True):
        for flip_r in (False, True):
            for swap in (False, True):
                g = grid.copy()
                if flip_c:
                    g[:, 0] = n - g[:, 0]
                if flip_r:
                    g[:, 1] = n - g[:, 1]
                if swap:
                    g = g[:, ::-1]
                assert np.array_equal(orient_grid(pts, g), want)


def test_labels_increase_with_image_x_and_y() -> None:
    pts, lab = _truth()
    assert lab.min() == 0 and lab.max() == 16
    corner0 = pts[(lab[:, 0] == 0) & (lab[:, 1] == 0)][0]
    assert corner0[0] < pts[:, 0].mean() and corner0[1] < pts[:, 1].mean()  # top-left


def test_every_photo_of_a_sweep_gets_the_same_labels_as_the_full_plate() -> None:
    views = [_view(y0, h) for y0, h in CROPS]
    out = label_plate_sweep(views, cols=17, rows=17, pitch_mm=4.5, capture_mm=CAPTURE_MM)
    for (y0, _), view, r in zip(CROPS, views, out, strict=True):
        assert not isinstance(r, str), r
        obj, ids = r
        assert len(ids) == len(view.points)
        assert _labels_match_truth(view, y0, ids)
        # object points are the certified grid in mm
        lab = np.column_stack([np.asarray(ids).ravel() % 17, np.asarray(ids).ravel() // 17])
        assert np.allclose(np.asarray(obj)[:, :2], lab * 4.5) and np.allclose(np.asarray(obj)[:, 2], 0)


def test_a_photo_whose_shift_is_ambiguous_is_dropped_not_mislabelled() -> None:
    # Encoder reading off by half a square: the shift could be either neighbouring label.
    views = [_view(0, 3600), _view(120, 3600), _view(240, 3600), _view(840, 3000, error_mm=2.25)]
    out = label_plate_sweep(views, cols=17, rows=17, pitch_mm=4.5, capture_mm=CAPTURE_MM)
    assert isinstance(out[3], str) and "ambiguous" in out[3]


def test_a_sweep_needs_two_photos_of_the_whole_plate() -> None:
    views = [_view(0, 3600), _view(600, 3000), _view(840, 3000)]
    with pytest.raises(ValueError, match="whole plate"):
        label_plate_sweep(views, cols=17, rows=17, pitch_mm=4.5, capture_mm=CAPTURE_MM)
