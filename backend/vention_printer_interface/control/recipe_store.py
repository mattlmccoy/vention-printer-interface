"""Persist the RecipePlan as a dotfile under experiments_root; loading always re-bounds."""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.control.recipe import RecipePlan
from vention_printer_interface.control.safety import SafetyLimits

CONFIG_NAME = ".recipe.json"


def load_recipe(root: Path, limits: SafetyLimits) -> RecipePlan:
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return RecipePlan()
    if not isinstance(data, dict):
        return RecipePlan()
    return RecipePlan.bounded(data, limits)


def save_recipe(root: Path, plan: RecipePlan) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / CONFIG_NAME).write_text(json.dumps(plan.to_dict(), indent=2))
