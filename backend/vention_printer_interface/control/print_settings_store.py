"""Persist the PrintSettings as a dotfile under experiments_root; loading always re-bounds."""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.control.print_settings import PrintSettings
from vention_printer_interface.control.safety import SafetyLimits

CONFIG_NAME = ".print_settings.json"


def load_print_settings(root: Path, limits: SafetyLimits) -> PrintSettings:
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return PrintSettings()
    if not isinstance(data, dict):
        return PrintSettings()
    return PrintSettings.bounded(data, limits)


def save_print_settings(root: Path, plan: PrintSettings) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_NAME).write_text(json.dumps(plan.to_dict(), indent=2))
