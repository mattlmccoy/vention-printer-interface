"""Absolute corner labels for a certified-chessboard calibration sweep.

The plate (DEvision Q18-100-4.5: 17 x 17 inner corners, 4.5 mm) has no marker IDs, and the
detector numbers each photo's grid from whatever corner it starts at, in any orientation. The sweep
solve needs every corner's TRUE plate position, so:

* **Orientation** comes from the photo: column labels increase toward image +x and row labels
  toward image +y (valid while the plate is within 45 degrees of square to the photo).
* **Whole-plate photos** (all ``cols x rows`` corners; the plate fits the photo near the capture
  pose) are then labelled absolutely.
* **Partial photos** (the plate runs off the photo further along the sweep) are only known up to an
  integer (column, row) shift. Mapped through the reference whole-plate photo, the plate appears
  moved by delta * v, where delta is the encoder offset and v is fitted from the whole-plate photos
  and refitted as photos are accepted, nearest first. The shift is the nearest whole square; a
  photo whose shift lands near half a square is dropped as ambiguous, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

AMBIGUOUS_FRAC = 0.25  # a shift must land within a quarter square of a whole square


@dataclass(frozen=True)
class PlateView:
    recoater_mm: float  # encoder readback
    points: np.ndarray  # Nx2 px
    grid: np.ndarray  # Nx2 detector (col, row) indices, any orientation
    placement: int = 0


Labelled = tuple[np.ndarray, np.ndarray] | str  # (object_points Nx3 mm, ids Nx1) or why not


def orient_grid(points: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """(col, row) labels with col increasing toward image +x, row toward +y, minimum (0, 0)."""
    g = np.asarray(grid, float).reshape(-1, 2)
    pts = np.asarray(points, float).reshape(-1, 2)
    design = np.column_stack([g, np.ones(len(g))])
    coef, *_ = np.linalg.lstsq(design, pts, rcond=None)
    e_col, e_row = coef[0], coef[1]  # image step per detector column / row
    if abs(e_col[0]) >= abs(e_row[0]):
        lab = np.column_stack([g[:, 0] * np.sign(e_col[0]), g[:, 1] * np.sign(e_row[1])])
    else:
        lab = np.column_stack([g[:, 1] * np.sign(e_row[0]), g[:, 0] * np.sign(e_col[1])])
    lab = lab - lab.min(axis=0)
    out: np.ndarray = np.rint(lab).astype(int)
    return out


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    import cv2

    h, _ = cv2.findHomography(src.astype(np.float64), dst.astype(np.float64), 0)
    return np.asarray(h, float)


def _apply(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.column_stack([pts, np.ones(len(pts))]) @ h.T
    out: np.ndarray = p[:, :2] / p[:, 2:3]
    return out


def _fit_v(deltas: list[float], shifts: list[np.ndarray]) -> np.ndarray:
    d = np.asarray(deltas, float)
    s = np.asarray(shifts, float).reshape(-1, 2)
    out: np.ndarray = (d[:, None] * s).sum(axis=0) / float((d ** 2).sum())
    return out


def _label_placement(views: list[PlateView], *, cols: int, rows: int, pitch_mm: float,
                     capture_mm: float, placement: int) -> list[Labelled]:
    rel = [orient_grid(v.points, v.grid) for v in views]
    full = [i for i, lab in enumerate(rel)
            if len(lab) == cols * rows and tuple(lab.max(axis=0)) == (cols - 1, rows - 1)]
    if len(full) < 2:
        raise ValueError(
            f"placement {placement + 1}: need at least 2 photos showing the whole plate "
            f"({cols} x {rows} corners); got {len(full)}. Sweep around the capture pose, where "
            "the plate fits the photo")
    ref = min(full, key=lambda i: abs(views[i].recoater_mm - capture_mm))
    h_ref = _homography(np.asarray(views[ref].points, float), rel[ref] * pitch_mm)

    def shift(i: int, lab: np.ndarray) -> np.ndarray:
        mapped = _apply(h_ref, np.asarray(views[i].points, float))
        out: np.ndarray = np.median(mapped - lab * pitch_mm, axis=0)
        return out

    out: list[Labelled] = ["not labelled"] * len(views)
    labels: dict[int, np.ndarray] = {i: rel[i] for i in full}
    deltas = [views[i].recoater_mm - views[ref].recoater_mm for i in full]
    shifts = [shift(i, rel[i]) for i in full]
    if not any(abs(d) > 0 for d in deltas):
        raise ValueError(f"placement {placement + 1}: the whole-plate photos were all taken at "
                         "one recoater position; the sweep must move")
    partial = sorted((i for i in range(len(views)) if i not in labels),
                     key=lambda i: abs(views[i].recoater_mm - views[ref].recoater_mm))
    for i in partial:
        delta = views[i].recoater_mm - views[ref].recoater_mm
        v = _fit_v(deltas, shifts)
        off = (shift(i, rel[i]) - delta * v) / pitch_mm
        whole = np.rint(off)
        frac = float(np.abs(off - whole).max())
        if frac > AMBIGUOUS_FRAC:
            out[i] = (f"ambiguous: the plate's shift in this photo is {frac:.2f} of a square from "
                      "a whole square, so its corners cannot be numbered safely")
            continue
        lab = rel[i] + whole.astype(int)
        if lab.min() < 0 or lab[:, 0].max() >= cols or lab[:, 1].max() >= rows:
            out[i] = "the numbered corners fall outside the plate; photo dropped"
            continue
        labels[i] = lab
        deltas.append(delta)
        shifts.append(shift(i, lab))
    for i, lab in labels.items():
        obj = np.column_stack([lab * pitch_mm, np.zeros(len(lab))])
        out[i] = (obj, (lab[:, 1] * cols + lab[:, 0]).reshape(-1, 1).astype(np.int32))
    return out


def label_plate_sweep(views: list[PlateView], *, cols: int, rows: int, pitch_mm: float,
                      capture_mm: float) -> list[Labelled]:
    """Per photo (same order): ``(object_points Nx3 mm, ids Nx1)`` with ids = row * cols + col,
    or the reason it was dropped. Raises ``ValueError`` when a placement has fewer than two
    whole-plate photos (its labels cannot be anchored)."""
    out: list[Labelled] = ["not labelled"] * len(views)
    for p in sorted({v.placement for v in views}):
        idx = [i for i, v in enumerate(views) if v.placement == p]
        res = _label_placement([views[i] for i in idx], cols=cols, rows=rows, pitch_mm=pitch_mm,
                               capture_mm=capture_mm, placement=p)
        for i, r in zip(idx, res, strict=True):
            out[i] = r
    return out
