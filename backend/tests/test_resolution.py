"""Unit tests for Siemens-star resolution (pure, no hardware)."""

from __future__ import annotations

from vention_printer_interface.vision.resolution import ResolutionResult, siemens_resolution


def test_contrast_crossings_give_expected_lpmm() -> None:
    # Contrast falls as radius shrinks (spatial frequency rises).
    radii = [200.0, 160.0, 120.0, 90.0, 60.0, 40.0, 25.0]
    contrast = [0.95, 0.9, 0.8, 0.6, 0.4, 0.2, 0.08]
    r = siemens_resolution(radii, contrast, n_spokes=72, mm_per_px=0.01)
    assert isinstance(r, ResolutionResult)
    assert r.lpmm_at[0.5] < r.lpmm_at[0.1]  # MTF50 freq is below the MTF10 freq
    assert r.passed(target_lpmm=r.lpmm_at[0.1] - 1) is True
    assert r.passed(target_lpmm=r.lpmm_at[0.1] + 5) is False


def test_low_contrast_never_reaches_target() -> None:
    r = siemens_resolution([100.0, 50.0], [0.05, 0.02], n_spokes=72, mm_per_px=0.01)
    assert r.lpmm_at[0.1] == 0.0
    assert r.passed(target_lpmm=10) is False


def test_all_high_contrast_resolves_to_the_finest_measured() -> None:
    # Every measured freq stays above thresholds -> limit = the finest (highest-freq) point.
    radii = [200.0, 100.0, 50.0]
    r = siemens_resolution(radii, [0.9, 0.85, 0.8], n_spokes=72, mm_per_px=0.01)
    finest = 72 / (2 * 3.141592653589793 * 50.0 * 0.01)
    assert abs(r.lpmm_at[0.1] - finest) < 1e-6
