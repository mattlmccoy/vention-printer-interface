from pathlib import Path

from vention_printer_interface.control.limits_store import CONFIG_NAME, load_limits, save_limits
from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits


def test_round_trip(tmp_path: Path) -> None:
    save_limits(tmp_path, SafetyLimits(heater_max_on_s=42))
    assert (tmp_path / CONFIG_NAME).exists()
    assert load_limits(tmp_path).heater_max_on_s == 42


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_limits(tmp_path) == SafetyLimits()


def test_hand_edited_file_is_reclamped(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text('{"heater_max_on_s": 999999}')
    assert load_limits(tmp_path).heater_max_on_s == HARD_BOUNDS["heater_max_on_s"][1]


def test_corrupt_file_gives_defaults(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text("not json")
    assert load_limits(tmp_path) == SafetyLimits()
    (tmp_path / CONFIG_NAME).write_text("[1,2]")
    assert load_limits(tmp_path) == SafetyLimits()
