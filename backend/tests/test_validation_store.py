"""Unit tests for the validation store + the calibration-trust warning."""

from __future__ import annotations

from pathlib import Path

from vention_printer_interface.vision.registration import (
    calibration_validation_warning,
    load_validation,
    save_validation,
)


def test_save_load_round_trips(tmp_path: Path) -> None:
    p = tmp_path / ".vision_validation.json"
    assert load_validation(p) is None
    save_validation(p, "cal-abc", {"max_mm": 0.03, "passed": True})
    got = load_validation(p)
    assert got is not None
    assert got["calibration_version"] == "cal-abc"
    assert got["scale"]["passed"] is True


def test_warning_is_none_only_for_a_passing_validation_of_the_active_version() -> None:
    passing = {"calibration_version": "v1", "scale": {"passed": True, "max_mm": 0.02}}
    assert calibration_validation_warning("v1", passing) is None
    # No validation at all -> warn.
    assert calibration_validation_warning("v1", None) is not None
    # Validation for a DIFFERENT (older) calibration version -> does not count.
    assert calibration_validation_warning("v2", passing) is not None
    # Validation exists for this version but FAILED -> warn.
    failed = {"calibration_version": "v1", "scale": {"passed": False, "max_mm": 0.5}}
    assert calibration_validation_warning("v1", failed) is not None
