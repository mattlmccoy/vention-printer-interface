from pathlib import Path

from vention_printer_interface.control.print_settings import PrintSettings
from vention_printer_interface.control.print_settings_store import (
    CONFIG_NAME,
    load_print_settings,
    save_print_settings,
)
from vention_printer_interface.control.safety import SafetyLimits


def test_round_trip(tmp_path: Path) -> None:
    plan = PrintSettings.bounded(
        {"printing": {"n_layers": 3}, "heater_enabled": True}, SafetyLimits()
    )
    save_print_settings(tmp_path, plan)
    assert (tmp_path / CONFIG_NAME).exists()
    assert load_print_settings(tmp_path, SafetyLimits()) == plan


def test_missing_or_corrupt_gives_defaults(tmp_path: Path) -> None:
    assert load_print_settings(tmp_path, SafetyLimits()) == PrintSettings()
    (tmp_path / CONFIG_NAME).write_text("nope")
    assert load_print_settings(tmp_path, SafetyLimits()) == PrintSettings()


def test_hand_edited_is_rebounded(tmp_path: Path) -> None:
    (tmp_path / CONFIG_NAME).write_text('{"recoater_end_mm": 99999, "heater_speed": 99999}')
    p = load_print_settings(tmp_path, SafetyLimits())
    assert p.recoater_end_mm == 972.0 and p.heater_speed == SafetyLimits().max_speed[4]
