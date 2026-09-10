"""Persist the referenced-axis set + the positions at which they were referenced, so reference
survives a software disconnect/restart when the MachineMotion kept power (and thus its positions).

On reconnect the app compares the MM's current positions to these; axes that came back unchanged
are still referenced (the MM never lost its count), while a real power-cycle collapses them to ~0
and they are dropped. Dotfile under experiments_root, mirroring primed_state / print_settings.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_NAME = ".reference.json"


def save_reference(root: Path, axes: set[int], positions: dict[int, float]) -> None:
    (root / CONFIG_NAME).write_text(
        json.dumps(
            {"axes": sorted(axes), "positions": {str(k): v for k, v in positions.items()}},
            indent=2,
        )
    )


def load_reference(root: Path) -> tuple[set[int], dict[int, float]] | None:
    """Return (referenced axes, positions) or None if absent/unreadable."""
    try:
        data = json.loads((root / CONFIG_NAME).read_text())
    except (OSError, ValueError):
        return None
    try:
        axes = {int(a) for a in data.get("axes", [])}
        positions = {int(k): float(v) for k, v in dict(data.get("positions", {})).items()}
    except (TypeError, ValueError):
        return None
    return axes, positions
