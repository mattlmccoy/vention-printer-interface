"""Tests for seaborn/matplotlib figure export (skipped when the `plots` extra isn't installed)."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")  # the whole module needs the optional plots extra

from vention_printer_interface.analysis.plotting import (  # noqa: E402
    plots_available,
    render_backlash,
    render_layer_accuracy,
    render_sweep,
    render_validation,
)


def test_plots_available_true_when_extra_installed() -> None:
    assert plots_available() is True


def test_render_backlash_png_and_pdf_are_nonempty_valid_files() -> None:
    positions = [
        {"ref_mm": 15.0, "reps_mm": [-0.1, -0.1, 0.0, -0.1], "backlash_median_mm": -0.1,
         "backlash_mag_median_mm": 0.1},
        {"ref_mm": 30.0, "reps_mm": [0.0, -0.1, -0.1, -0.1], "backlash_median_mm": -0.1,
         "backlash_mag_median_mm": 0.1},
        {"ref_mm": 45.0, "reps_mm": [0.0, 0.0, 0.0, -0.1], "backlash_median_mm": 0.0,
         "backlash_mag_median_mm": 0.0},
    ]
    png = render_backlash(positions, recommended=0.1, tol_mm=0.1, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000  # real PNG
    pdf = render_backlash(positions, recommended=0.1, tol_mm=0.1, fmt="pdf")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000            # real PDF


def test_render_backlash_handles_empty_positions() -> None:
    png = render_backlash([], recommended=None, tol_mm=0.1, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # still a valid (empty-state) figure, no crash


# Rows captured verbatim from a real run's layer_accuracy.csv
# (experiments/20260918_193542_FGM_square_20mm_10L/layer_accuracy.csv), which has columns
# layer,phase,commanded_mm,actual_mm,deviation_mm,commanded_cum_mm,actual_cum_mm.
_LAYER_ROWS = [
    {"layer": 1, "phase": "thin_precoat", "commanded_mm": 0.6, "actual_mm": 0.6,
     "deviation_mm": 0.0, "commanded_cum_mm": 0.6, "actual_cum_mm": 0.6},
    {"layer": 2, "phase": "printing", "commanded_mm": 0.2, "actual_mm": 0.2,
     "deviation_mm": 0.0, "commanded_cum_mm": 0.8, "actual_cum_mm": 0.8},
    {"layer": 3, "phase": "printing", "commanded_mm": 0.2, "actual_mm": 0.2,
     "deviation_mm": 0.0, "commanded_cum_mm": 1.0, "actual_cum_mm": 1.0},
]


def test_render_layer_accuracy_png_pdf() -> None:
    png = render_layer_accuracy(_LAYER_ROWS, tol_mm=0.1, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
    pdf = render_layer_accuracy(_LAYER_ROWS, tol_mm=0.1, fmt="pdf")
    assert pdf[:5] == b"%PDF-"


def test_render_layer_accuracy_tolerates_missing_actual() -> None:
    # recorder.py:130 documents actual_mm/deviation_mm as None when a layer window has no
    # telemetry; a CSV round-trip surfaces that as "" (shape-only synthetic case).
    rows = _LAYER_ROWS + [
        {"layer": 4, "phase": "printing", "commanded_mm": 0.2, "actual_mm": "",
         "deviation_mm": "", "commanded_cum_mm": 1.2, "actual_cum_mm": ""},
    ]
    png = render_layer_accuracy(rows, tol_mm=0.1, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # None/"" actual dropped, no crash


def test_render_validation_histogram() -> None:
    # ScaleResult.residuals_mm shape (vision/validation.py): absolute per-gap errors in mm.
    residuals = [0.012, 0.031, 0.008, 0.045, 0.019, 0.027, 0.006, 0.038]
    png = render_validation(residuals, target_mm=0.05, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
    pdf = render_validation(residuals, target_mm=0.05, fmt="pdf")
    assert pdf[:5] == b"%PDF-"


def test_render_sweep_hysteresis() -> None:
    # Rows match scripts/piston_sweep.py:276 dict shape (pass/step_size/direction/index/
    # commanded_mm/actual_mm/deviation_mm/step_cmd_mm/step_actual_mm/step_err_mm).
    rows = [
        {"pass": 1, "step_size": 1.0, "direction": "down", "index": 0, "commanded_mm": 10.0,
         "actual_mm": 10.0, "deviation_mm": 0.0, "step_cmd_mm": 1.0, "step_actual_mm": 1.0,
         "step_err_mm": 0.0},
        {"pass": 1, "step_size": 1.0, "direction": "down", "index": 1, "commanded_mm": 11.0,
         "actual_mm": 11.0, "deviation_mm": 0.0, "step_cmd_mm": 1.0, "step_actual_mm": 1.0,
         "step_err_mm": 0.0},
        {"pass": 1, "step_size": 1.0, "direction": "up", "index": 0, "commanded_mm": 11.0,
         "actual_mm": 10.9, "deviation_mm": -0.1, "step_cmd_mm": -1.0, "step_actual_mm": -0.9,
         "step_err_mm": 0.1},
        {"pass": 1, "step_size": 1.0, "direction": "up", "index": 1, "commanded_mm": 10.0,
         "actual_mm": 9.9, "deviation_mm": -0.1, "step_cmd_mm": -1.0, "step_actual_mm": -1.0,
         "step_err_mm": 0.0},
    ]
    png = render_sweep(rows, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
