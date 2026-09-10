"""Persist the primed bed state (piston positions a print starts from) under the data root.

Mirrors priming_store's JSON load/save pattern: reads are wrapped so a missing or unreadable
file yields ``None`` rather than raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATE_NAME = ".primed.json"


@dataclass(frozen=True)
class PrimedState:
    """A snapshot of the piston positions captured as the primed bed state."""

    part_mm: float
    feed_mm: float
    captured_at: float

    def to_dict(self) -> dict[str, float]:
        return {
            "part_mm": self.part_mm,
            "feed_mm": self.feed_mm,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimedState:
        return cls(
            part_mm=float(data["part_mm"]),
            feed_mm=float(data["feed_mm"]),
            captured_at=float(data["captured_at"]),
        )


def load_primed(root: Path) -> PrimedState | None:
    try:
        data = json.loads((root / STATE_NAME).read_text())
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return PrimedState.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None


def save_primed(root: Path, state: PrimedState) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / STATE_NAME).write_text(json.dumps(state.to_dict(), indent=2))
