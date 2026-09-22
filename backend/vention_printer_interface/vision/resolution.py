"""Siemens-star resolution (pure, hardware-free).

Given the star's contrast (modulation) sampled at a set of radii, convert each radius to a spatial
frequency (the spokes make ``n_spokes`` line pairs around the circle, so at radius ``r`` px the
frequency is ``n_spokes / (2*pi*r*mm_per_px)`` lp/mm), build the MTF curve, and read the limiting
resolution at the MTF thresholds. The same analyzer works on an IMAGED star (optical resolution) and
later on a PRINTED star (process resolution / minimum printable feature). The image → contrast-by-
radius extraction lives in the API adapter; this core is pure math. No IO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolutionResult:
    lpmm_at: dict[float, float]           # MTF threshold -> limiting frequency (lp/mm)
    curve: list[tuple[float, float]]      # (frequency lp/mm, contrast) ascending in frequency

    def passed(self, target_lpmm: float) -> bool:
        # The MTF10 frequency is the conventional resolution limit.
        return self.lpmm_at.get(0.1, 0.0) >= target_lpmm


def _cross_freq(pts: list[tuple[float, float]], threshold: float) -> float:
    """Frequency where contrast crosses ``threshold`` as frequency rises (contrast falls). 0.0 if
    even the lowest frequency is already below threshold; the finest measured frequency if contrast
    never falls below it."""
    if not pts:
        return 0.0
    if pts[0][1] < threshold:
        return 0.0
    for i in range(1, len(pts)):
        f0, c0 = pts[i - 1]
        f1, c1 = pts[i]
        if c1 < threshold <= c0:
            if c0 == c1:
                return f1
            frac = (c0 - threshold) / (c0 - c1)
            return f0 + frac * (f1 - f0)
    return pts[-1][0]


def siemens_resolution(
    radii_px: list[float],
    contrast: list[float],
    n_spokes: int,
    mm_per_px: float,
    mtf: tuple[float, ...] = (0.5, 0.1),
) -> ResolutionResult:
    """MTF-based limiting resolution from contrast-vs-radius samples of a Siemens star."""
    pts: list[tuple[float, float]] = []
    for r, c in zip(radii_px, contrast, strict=False):
        if r > 0 and mm_per_px > 0:
            freq = n_spokes / (2.0 * math.pi * r * mm_per_px)
            pts.append((freq, float(c)))
    pts.sort(key=lambda x: x[0])  # ascending frequency
    lpmm_at = {t: _cross_freq(pts, t) for t in mtf}
    return ResolutionResult(lpmm_at=lpmm_at, curve=pts)
