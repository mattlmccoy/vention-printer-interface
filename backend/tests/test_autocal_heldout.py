"""Leave-one-photo-out accuracy of an automatic calibration (vision/autocal_heldout.py).

Each photo is held out, the calibration refit without it, and its points mapped through the refit:
the error is the distance to where the board really is (board pose at the capture pose, moved by
the encoder reading along bed X). This is the measure the 2026-10-21 analysis used to compare
detection methods; on synthetic ground truth it must be small.
"""

from __future__ import annotations

from tests.autocal_synth import synth_views
from vention_printer_interface.vision.autocal_heldout import heldout_errors
from vention_printer_interface.vision.board_gen import resolve_preset

SPEC = resolve_preset("small_cylinder")


def test_heldout_error_is_small_on_ground_truth() -> None:
    views, truth = synth_views(spec=SPEC, with_markers=True)
    rows = heldout_errors(views, capture_recoater_mm=truth.capture_mm, image_size=(1920, 1080))
    assert len(rows) == len(views) - 1  # the capture-pose photo defines the reference
    assert max(r["rms_mm"] for r in rows) < 0.03
    assert all(r["max_mm"] >= r["rms_mm"] for r in rows)


def test_heldout_error_ignores_the_boards_own_scale_error() -> None:
    # The calibration is in encoder mm; a 0.2%-small engraved board must not read as map error.
    views, truth = synth_views(spec=SPEC, with_markers=True, board_scale=0.998)
    rows = heldout_errors(views, capture_recoater_mm=truth.capture_mm, image_size=(1920, 1080))
    assert max(r["rms_mm"] for r in rows) < 0.03
