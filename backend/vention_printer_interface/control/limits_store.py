"""Persist SafetyLimits as a dotfile under experiments_root; loading always re-clamps.

A hand-edited or stale file can never widen protection past a hard cap (spec §3).
"""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.control.safety import SafetyLimits

CONFIG_NAME = ".limits.json"


def load_limits(root: Path) -> SafetyLimits:
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return SafetyLimits()
    if not isinstance(data, dict):
        return SafetyLimits()
    return SafetyLimits.bounded(**data)


def save_limits(root: Path, limits: SafetyLimits) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_NAME).write_text(json.dumps(limits.to_dict(), indent=2))
