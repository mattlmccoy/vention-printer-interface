"""Dimensional-accuracy analysis (Lane A).

Vendored RFAM metrology (``feature_analysis``) + structured compensation
extraction + per-run orchestration/persistence. Report-only in v1.
"""

from .compensation import Compensation, to_compensation
from .feature_analysis import (
    analyze_checkerboard,
    analyze_concentric_rings,
    analyze_dot_array,
    analyze_pitch_ruler,
    recommend_compensation_overall,
)

__all__ = [
    "analyze_dot_array",
    "analyze_checkerboard",
    "analyze_concentric_rings",
    "analyze_pitch_ruler",
    "recommend_compensation_overall",
    "Compensation",
    "to_compensation",
]
