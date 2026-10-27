"""Partial chessboard detection must refuse an irregular grid (vision/registration.py).

``findChessboardCornersSBWithMeta`` is not deterministic: on the SAME 2026-10-27 certified-plate
photo it returned the full 17x17 grid on most tries and, on others, a grid that skips every other
column (51 corners, steps of 2 squares). Scored as-is that produced a 24 mm "validation failure".
Fixtures are both real detections of that photo (validations/cal-20261027T175542Z/
20261027T175626224020Z/raw.jpg).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vention_printer_interface.vision.registration import first_regular_grid, grid_is_regular

FIX = Path(__file__).parent / "fixtures" / "chessboard_detect"


def _load(name: str) -> tuple[np.ndarray, np.ndarray]:
    d = np.load(FIX / f"plate_{name}_20261027.npz")
    return d["points"], d["grid"]


def test_the_full_plate_grid_is_regular() -> None:
    pts, grid = _load("good")
    assert len(pts) == 289
    assert grid_is_regular(pts, grid)


def test_a_grid_that_skips_columns_is_refused() -> None:
    pts, grid = _load("bad")
    assert len(pts) == 51
    assert not grid_is_regular(pts, grid)


def test_detection_retries_past_an_irregular_grid() -> None:
    bad, good = _load("bad"), _load("good")
    tries: list[int] = []

    def attempts():  # what the detector returned on successive tries
        for i, r in enumerate([None, bad, good, bad]):
            tries.append(i)
            yield r

    out = first_regular_grid(attempts())
    assert out is not None and len(out[0]) == 289
    assert tries == [0, 1, 2]  # stops at the first regular grid


def test_no_regular_grid_means_no_detection() -> None:
    assert first_regular_grid(iter([None, _load("bad")])) is None
