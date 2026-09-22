"""Unit tests for world-space scale validation (pure, no hardware)."""

from __future__ import annotations

from vention_printer_interface.vision.validation import ScaleResult, scale_residuals


def _grid(square_mm: float, nx: int, ny: int, scale: float = 1.0, shear: float = 0.0):
    pts = []
    for j in range(ny):
        for i in range(nx):
            x = i * square_mm * scale
            y = j * square_mm + shear * x
            pts.append((x, y))
    return pts, (nx, ny)


def test_exact_grid_has_near_zero_error() -> None:
    pts, dims = _grid(5.0, 6, 5)
    r = scale_residuals(pts, dims, square_mm=5.0)
    assert isinstance(r, ScaleResult)
    assert r.max < 1e-6 and r.mean < 1e-6
    assert r.passed(0.05) is True


def test_scaled_grid_fails_tolerance() -> None:
    pts, dims = _grid(5.0, 6, 5, scale=1.02)  # 2% too wide -> 0.1 mm at a 5 mm square
    r = scale_residuals(pts, dims, square_mm=5.0)
    assert r.max > 0.05 and r.passed(0.05) is False


def test_residuals_cover_both_axes_and_report_rms() -> None:
    pts, dims = _grid(4.0, 4, 4, shear=0.01)  # slight shear stretches vertical spacings
    r = scale_residuals(pts, dims, square_mm=4.0)
    assert len(r.residuals_mm) > 0
    assert r.rms >= r.mean >= 0.0
