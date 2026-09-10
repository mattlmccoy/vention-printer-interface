"""Persist PrimingSettings as a dotfile under experiments_root; loading always re-bounds."""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.control.priming import PrimingSettings
from vention_printer_interface.control.safety import SafetyLimits

CONFIG_NAME = ".priming.json"


def load_priming(root: Path, limits: SafetyLimits) -> PrimingSettings:
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return PrimingSettings()
    if not isinstance(data, dict):
        return PrimingSettings()
    return PrimingSettings.bounded(data, limits)


def save_priming(root: Path, settings: PrimingSettings) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_NAME).write_text(json.dumps(settings.to_dict(), indent=2))
