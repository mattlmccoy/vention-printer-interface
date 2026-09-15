"""Per-run dimensional analysis + persistence (Lane A, v1 report-only).

``analyze_run`` picks a run's gold-standard registered still, reads its ``mm_per_px``
calibration, locates each test feature (manual ROIs, or best-effort auto-location off the
Ø100 mm outer circle), runs the four vendored analyzers, derives a structured
compensation, and persists an honest report to ``<run>/analysis/dimensional.json``.

Honesty contract (no false-green): every failure mode returns a distinct, non-"ok"
status with an explanatory message and NO fabricated metrics —
  * ``no_capture``     — no usable registered capture in the run,
  * ``no_calibration`` — a capture exists but carries no ``registered_space.mm_per_px``,
  * ``roi_failed``     — auto-location could not anchor on the outer circle.

AUTO-LOCATION CAVEAT: the per-feature mm-boxes below are grounded in the geometry
generator (``code/rfam_tool/generate_dimensional_geometry.py``), but auto-location has
NOT been verified against a real on-powder registered capture. The trusted path is
manual ``rois`` supplied by the caller/frontend; auto-location degrades to ``roi_failed``
rather than emitting guessed numbers.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from vention_printer_interface.vision.store import read_manifest

from .compensation import to_compensation
from .feature_analysis import (
    FEATURE_ANALYSIS_VERSION,
    analyze_checkerboard,
    analyze_concentric_rings,
    analyze_dot_array,
    analyze_pitch_ruler,
)

logger = logging.getLogger(__name__)

# Nominal dimensions of the gold-standard test geometry (physical mm, DPI-independent).
# Source: code/rfam_tool/generate_dimensional_geometry.py.
DEFAULTS: dict[str, Any] = {
    "outer_circle": {"diameter_mm": 100.0},
    "dot": {"diameter_mm": 2.0, "spacing_mm": 6.0},
    "checkerboard": {"square_mm": 2.0},
    "rings": {"line_mm": 0.5, "gap_mm": 0.5, "count": 20},
    # The fixture's results.csv includes the 6 mm base as the first pitch width.
    "pitch": {"widths_mm": [6.0, 4.0, 2.0, 1.0, 0.8, 0.6, 0.4, 0.2, 0.1]},
}

# Feature bounding boxes for auto-location, in center-based mm (+x right, +y UP), given as
# (top_left_x_mm, top_left_y_mm, width_mm, height_mm) with the circle center as origin.
# Grounded in generate_dimensional_geometry.py; padded ~2 mm. Provisional (see caveat).
_AUTO_LAYOUT_MM: dict[str, tuple[float, float, float, float]] = {
    # dot grid center (-9.1, +22.0), 5x5 @ 6 mm pitch (24 mm span) + 2 mm dots -> ~26 mm box
    "dot": (-24.1, 35.0, 30.0, 30.0),
    # checkerboard center (15.4, 15.4), 8x8 @ 2 mm -> 16 mm box
    "checkerboard": (5.4, 25.4, 20.0, 20.0),
    # rings center (-12.6, -15.0), 20 rings @ 1 mm pitch -> radius 20 mm -> 40 mm box
    "rings": (-34.6, 7.0, 44.0, 44.0),
    # pitch L-ruler, base bottom-left (10.5, -16.6); generous box over base + bars
    "pitch": (9.0, 8.0, 26.0, 26.0),
}

_ANALYSIS_SUBDIR = "analysis"
_REPORT_NAME = "dimensional.json"


@dataclass(frozen=True)
class DimensionalReport:
    """A persisted, JSON-serializable dimensional-accuracy report.

    All fields hold plain JSON types so ``to_dict``/``from_dict`` round-trip exactly.
    """

    run: str
    status: str  # "ok" | "no_capture" | "no_calibration" | "roi_failed"
    generated_utc: str
    message: str = ""
    captured_from: dict[str, Any] | None = None
    px_per_mm: float | None = None
    mm_per_px: float | None = None
    rois: dict[str, list[int]] | None = None
    features: dict[str, Any] = field(default_factory=dict)
    compensation: dict[str, Any] | None = None
    tool_provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DimensionalReport:
        return cls(**data)


def mm_box_to_px_rect(
    center_px: tuple[float, float],
    px_per_mm: float,
    box_mm: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    """Map a center-based mm bounding box to a top-left-origin pixel rect.

    ``box_mm`` = (top_left_x_mm, top_left_y_mm, width_mm, height_mm) in the geometry's
    center-based frame where +x is right and +y is UP (matching the generator's
    ``mm_to_px``). Returns ``(x, y, w, h)`` in pixels with the image's top-left origin.
    """
    cx, cy = center_px
    x_mm, y_mm, w_mm, h_mm = box_mm
    x_px = int(round(cx + x_mm * px_per_mm))
    y_px = int(round(cy - y_mm * px_per_mm))  # +y mm is up -> smaller pixel row
    w_px = int(round(w_mm * px_per_mm))
    h_px = int(round(h_mm * px_per_mm))
    return (x_px, y_px, w_px, h_px)


def _feature_boxes() -> dict[str, tuple[float, float, float, float]]:
    """The single source of the per-feature auto-location mm-boxes.

    Both ``_auto_rois`` (after HoughCircles locates the center) and ``rois_from_circle``
    (given a marked center) iterate this so their ROI geometry stays identical.
    """
    return _AUTO_LAYOUT_MM


def px_per_mm_from_circle(radius_px: float, diameter_mm: float) -> float:
    """px/mm implied by the marked Ø``diameter_mm`` outer circle (radius in px)."""
    return (2.0 * radius_px) / diameter_mm


def rois_from_circle(
    center_px: tuple[float, float], px_per_mm: float, nominals: dict[str, Any]
) -> dict[str, list[int]]:
    """Feature ROIs from a known circle center — same math as ``_auto_rois``, no Hough.

    ``nominals`` is accepted for signature parity with ``_auto_rois``/``analyze_run``; the
    feature boxes come from ``_feature_boxes()`` (the shared source), not from ``nominals``.
    """
    rois: dict[str, list[int]] = {}
    for feature, box_mm in _feature_boxes().items():
        rois[feature] = list(mm_box_to_px_rect(center_px, px_per_mm, box_mm))
    return rois


def _report_path(run_dir: Path) -> Path:
    return Path(run_dir) / _ANALYSIS_SUBDIR / _REPORT_NAME


def load_report(run_dir: Path) -> dict[str, Any] | None:
    """Return the persisted report dict for a run, or None if it hasn't been analyzed."""
    p = _report_path(run_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _provenance() -> dict[str, Any]:
    return {
        "module": "feature_analysis",
        "source": "code/rfam_tool/feature_analysis.py",
        "vendored": "2026-09-14",
        "feature_analysis_version": FEATURE_ANALYSIS_VERSION,
    }


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _fail(run: str, status: str, message: str, **extra: Any) -> DimensionalReport:
    """Build a non-ok report with no fabricated metrics."""
    return DimensionalReport(
        run=run,
        status=status,
        generated_utc=_now_utc(),
        message=message,
        tool_provenance=_provenance(),
        **extra,
    )


def _select_capture(
    records: list[dict[str, Any]], layer: int | None, stage: str
) -> dict[str, Any] | None:
    """Pick the gold-standard capture: prefer (layer, stage); else first available image.

    A caller-specified ``layer`` is honored strictly — we never silently substitute a
    different layer.
    """
    pool = [r for r in records if isinstance(r.get("registered"), str) and r.get("registered")]
    if not pool:
        return None
    match = next(
        (
            r
            for r in pool
            if r.get("stage") == stage and (layer is None or r.get("layer") == layer)
        ),
        None,
    )
    if match is not None:
        return match
    if layer is None:
        return pool[0]  # "first available" fallback when no layer was pinned
    return None


def _sidecar_path_for(run_dir: Path, registered_rel: str) -> Path:
    stem, _, _ext = registered_rel.rpartition(".")
    return Path(run_dir) / f"{stem or registered_rel}.json"


def _read_mm_per_px(sidecar_path: Path) -> float | None:
    if not sidecar_path.exists():
        return None
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    space = data.get("registered_space")
    if not isinstance(space, dict):
        return None
    val = space.get("mm_per_px")
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _locate_outer_circle(
    gray: np.ndarray, px_per_mm: float, diameter_mm: float
) -> tuple[float, float] | None:
    """Best-effort: find the Ø``diameter_mm`` outer circle center via HoughCircles.

    Returns (cx, cy) in pixels, or None when no plausible circle is found.
    """
    expected_r = 0.5 * diameter_mm * px_per_mm
    if expected_r <= 0:
        return None
    blurred = cv2.GaussianBlur(gray, (9, 9), 2)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.5,
        minDist=max(1.0, expected_r),
        param1=120,
        param2=60,
        minRadius=int(expected_r * 0.7),
        maxRadius=int(expected_r * 1.3),
    )
    if circles is None or len(circles) == 0:
        return None
    c = np.round(circles[0, :]).astype(float)
    cx, cy, _r = c[0]
    return (float(cx), float(cy))


def _crop(image: np.ndarray, rect: list[int] | tuple[int, int, int, int]) -> np.ndarray | None:
    """Clamp a rect to the image and return the crop, or None if it is empty."""
    h, w = image.shape[:2]
    x, y, rw, rh = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + rw), min(h, y + rh)
    if x1 <= x0 or y1 <= y0:
        return None
    return image[y0:y1, x0:x1]


def _run_analyzer(
    feature: str, crop: np.ndarray, px_per_mm: float, nominals: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch one feature ROI to its vendored analyzer, returning the summary dict."""
    if feature == "dot":
        summary, _details = analyze_dot_array(
            crop,
            px_per_mm=px_per_mm,
            nominal_diameter_mm=nominals["dot"]["diameter_mm"],
            nominal_spacing_mm=nominals["dot"]["spacing_mm"],
        )
        return summary
    if feature == "checkerboard":
        return analyze_checkerboard(
            crop, px_per_mm=px_per_mm, nominal_square_mm=nominals["checkerboard"]["square_mm"]
        )
    if feature == "rings":
        return analyze_concentric_rings(
            crop,
            px_per_mm=px_per_mm,
            nominal_line_width_mm=nominals["rings"]["line_mm"],
            nominal_spacing_mm=nominals["rings"]["gap_mm"],
            num_rings=nominals["rings"]["count"],
        )
    if feature in ("pitch", "pitch_x", "pitch_y"):
        orientation = "y" if feature == "pitch_y" else "x"
        return analyze_pitch_ruler(
            crop,
            px_per_mm=px_per_mm,
            nominal_widths_mm=nominals["pitch"]["widths_mm"],
            orientation=orientation,
        )
    return {"algorithm_error": f"unknown_feature: {feature}"}


def _auto_rois(
    image: np.ndarray, px_per_mm: float, nominals: dict[str, Any]
) -> dict[str, list[int]] | None:
    """Auto-locate feature ROIs off the outer circle. None if the anchor can't be found."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    center = _locate_outer_circle(gray, px_per_mm, nominals["outer_circle"]["diameter_mm"])
    if center is None:
        return None
    rois: dict[str, list[int]] = {}
    for feature, box_mm in _feature_boxes().items():
        rois[feature] = list(mm_box_to_px_rect(center, px_per_mm, box_mm))
    return rois


def analyze_run(
    run_dir: Path | str,
    *,
    layer: int | None = None,
    stage: str = "post_jet",
    rois: dict[str, list[int]] | None = None,
    nominals: dict[str, Any] = DEFAULTS,
) -> DimensionalReport:
    """Analyze one recorded run's gold-standard capture and persist the report.

    Parameters
    ----------
    run_dir : path
        The recorded run directory (contains ``vision/manifest.json`` + captures).
    layer, stage : capture selectors
        Which registered still to analyze. ``stage`` defaults to ``post_jet``.
    rois : {feature: [x, y, w, h]}, optional
        Manual pixel ROIs (trusted). When omitted, auto-location is attempted.
    nominals : dict
        Nominal geometry (defaults to the gold standard).
    """
    run_dir = Path(run_dir)
    run = run_dir.name

    records = read_manifest(run_dir)
    chosen = _select_capture(records, layer, stage)
    if chosen is None:
        return _fail(
            run,
            "no_capture",
            f"no registered capture for layer={layer} stage={stage!r} in this run",
        )

    registered_rel = str(chosen["registered"])
    image_path = run_dir / registered_rel
    if not image_path.exists():
        return _fail(run, "no_capture", f"capture file missing on disk: {registered_rel}")

    mm_per_px = _read_mm_per_px(_sidecar_path_for(run_dir, registered_rel))
    if mm_per_px is None:
        return _fail(
            run,
            "no_calibration",
            f"capture {registered_rel} has no registered_space.mm_per_px (not registered)",
            captured_from={"layer": chosen.get("layer"), "stage": chosen.get("stage")},
        )

    image = cv2.imread(str(image_path))
    if image is None:
        return _fail(run, "no_capture", f"capture image unreadable: {registered_rel}")

    px_per_mm = 1.0 / mm_per_px

    if rois is None:
        rois = _auto_rois(image, px_per_mm, nominals)
        if rois is None:
            return _fail(
                run,
                "roi_failed",
                "could not auto-locate the Ø100 mm outer circle to anchor ROIs; "
                "supply manual rois",
                captured_from={"layer": chosen.get("layer"), "stage": chosen.get("stage")},
                px_per_mm=px_per_mm,
                mm_per_px=mm_per_px,
            )

    features: dict[str, Any] = {}
    used_rois: dict[str, list[int]] = {}
    for feature, rect in rois.items():
        crop = _crop(image, rect)
        if crop is None:
            features[feature] = {"algorithm_error": "empty_roi"}
            used_rois[feature] = list(rect)
            continue
        features[feature] = _run_analyzer(feature, crop, px_per_mm, nominals)
        used_rois[feature] = [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])]

    comp = to_compensation(
        dot=features.get("dot"),
        checkerboard=features.get("checkerboard"),
    )

    report = DimensionalReport(
        run=run,
        status="ok",
        generated_utc=_now_utc(),
        message="",
        captured_from={"layer": chosen.get("layer"), "stage": chosen.get("stage")},
        px_per_mm=px_per_mm,
        mm_per_px=mm_per_px,
        rois=used_rois,
        features=features,
        compensation=asdict(comp),
        tool_provenance=_provenance(),
    )

    _persist(run_dir, report)
    return report


def _persist(run_dir: Path, report: DimensionalReport) -> None:
    out = _report_path(run_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
