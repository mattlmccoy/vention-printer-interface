"""Why a certified-chessboard validation passed or failed, drawn on the validation photo itself.

2026-10-26: a validation FAILED (worst 0.129 mm, RMS 0.075 mm, scale bias 1.0027) and the page
showed only numbers. This draws every corner on the actual photo, coloured by its error against
the target, with an arrow towards where the calibration says that corner should be (enlarged),
greys out corners outside the calibrated area, outlines that area, and reports how much of the
error is a pure scale error (a similarity fit removes it) versus everything else.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from vention_printer_interface.vision.overlay import bed_to_raw_px, fit_width

_GREEN, _AMBER, _RED, _GREY, _AREA = (70, 200, 70), (0, 170, 255), (40, 40, 230), (150, 150, 150), (
    80, 220, 120)


def similarity_residuals(measured_mm: np.ndarray, known_mm: np.ndarray) -> np.ndarray:
    """Per-point residual after the best rotation + translation + ONE scale (scale removed)."""
    m, k = np.asarray(measured_mm, float), np.asarray(known_mm, float)
    mm_, km = m.mean(axis=0), k.mean(axis=0)
    u, sv, vt = np.linalg.svd((k - km).T @ (m - mm_))
    d = np.sign(np.linalg.det(u @ vt))
    r = u @ np.diag([1.0, d]) @ vt
    s = float((sv * np.array([1.0, d])).sum() / ((m - mm_) ** 2).sum())
    out: np.ndarray = s * (m - mm_) @ r.T + km - k
    return out


def annotate_validation(
    image: np.ndarray, *, raw_px: np.ndarray, scored: np.ndarray, predicted_mm: np.ndarray,
    error_mm: np.ndarray, target_mm: float, calib: Any, region: list[Any] | None,
    summary: list[str],
) -> np.ndarray:
    """The validation photo with each corner's verdict.

    ``raw_px``: every detected corner (photo px); ``scored``: mask of those inside the area;
    ``predicted_mm``: for scored corners, where the certified grid says they are (bed mm, after
    the rigid fit); ``error_mm``: their error magnitudes."""
    import cv2

    out = (image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)).copy()
    w = out.shape[1]
    t = max(1, round(w / 1000))  # line/text weight scales with the photo (5 at 5120 px)
    r = max(3, round(w / 260))
    k, dist = calib.camera_matrix, (calib.dist_coeffs if calib.dist_coeffs is not None
                                    else np.zeros(5))
    if region and k is not None:
        poly = bed_to_raw_px(np.asarray(region, float), k, dist, calib.H)
        cv2.polylines(out, [np.round(poly).astype(np.int32).reshape(-1, 1, 2)], True, _AREA,
                      t * 2, cv2.LINE_AA)
    pts = np.asarray(raw_px, float).reshape(-1, 2)
    for p in pts[~scored]:
        cv2.circle(out, (round(p[0]), round(p[1])), r, _GREY, t, cv2.LINE_AA)
    sp = pts[scored]
    if len(sp) and k is not None:
        pred_px = bed_to_raw_px(np.asarray(predicted_mm, float), k, dist, calib.H)
        vec = pred_px - sp
        mags = np.linalg.norm(vec, axis=1)
        p95 = float(np.percentile(mags, 95)) if len(mags) else 0.0
        gain = 0.03 * w / p95 if p95 > 0 else 1.0
        for p, v, e in zip(sp, vec, np.asarray(error_mm, float), strict=True):
            col = _GREEN if e <= target_mm else _AMBER if e <= 2 * target_mm else _RED
            cv2.arrowedLine(out, (round(p[0]), round(p[1])),
                            (round(p[0] + v[0] * gain), round(p[1] + v[1] * gain)), col, t,
                            cv2.LINE_AA, tipLength=0.3)
            cv2.circle(out, (round(p[0]), round(p[1])), r, col, -1, cv2.LINE_AA)
        summary = [*summary, f"arrows x{gain:.0f}: towards where each corner should be"]
    fs = 0.32 * t + 0.1
    y = round(30 * fs) + 8
    for line in summary:
        for colr, th in (((20, 20, 20), t * 3), ((255, 255, 255), t)):
            cv2.putText(out, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, fs, colr, th, cv2.LINE_AA)
        y += round(34 * fs)
    fw, fh = fit_width((out.shape[1], out.shape[0]))
    if (fw, fh) != (out.shape[1], out.shape[0]):
        out = cv2.resize(out, (fw, fh), interpolation=cv2.INTER_AREA)
    return out
