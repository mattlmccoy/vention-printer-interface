"""Persist the primed bed state (piston positions a print starts from) under the data root.

Mirrors priming_store's JSON load/save pattern: reads are wrapped so a missing or unreadable
file yields ``None`` rather than raising.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vention_printer_interface.control.print_settings import PrintSettings

STATE_NAME = ".primed.json"


@dataclass(frozen=True)
class PrimedState:
    """A snapshot of the piston positions captured as the primed bed state."""

    part_mm: float
    feed_mm: float
    captured_at: float
    plan_fingerprint: str | None = None
    consumed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_mm": self.part_mm,
            "feed_mm": self.feed_mm,
            "captured_at": self.captured_at,
            "plan_fingerprint": self.plan_fingerprint,
            "consumed_at": self.consumed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimedState:
        fp, used = data.get("plan_fingerprint"), data.get("consumed_at")
        return cls(
            part_mm=float(data["part_mm"]),
            feed_mm=float(data["feed_mm"]),
            captured_at=float(data["captured_at"]),
            plan_fingerprint=fp if isinstance(fp, str) else None,
            consumed_at=float(used) if isinstance(used, int | float) else None,
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


def plan_fingerprint(plan: PrintSettings) -> str:
    """A short hash of the plan fields that decide how much powder the bed and feed need:
    per-phase layer count / layer thickness / feed thickness, and whether the postcoat runs.
    Speeds, dwells and heater settings don't change the powder, so they don't change it."""
    phases = {
        name: [ph.n_layers, ph.layer_thickness_mm, ph.feed_thickness_mm]
        for name, ph in (("thin_precoat", plan.thin_precoat), ("printing", plan.printing),
                         ("postcoat", plan.postcoat))
    }
    blob = json.dumps({"phases": phases, "postcoat": plan.postcoat_enabled}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def primed_status(primed: PrimedState | None, plan: PrintSettings) -> dict[str, str]:
    """Is the captured bed ready for THIS plan? ``state`` is one of none / ready / other_plan /
    used / unverified. Only ``ready`` means yes; a capture made before plans were recorded is
    ``unverified`` (never assumed to match)."""
    if primed is None:
        return {"state": "none", "reason": "the bed hasn't been primed"}
    if primed.plan_fingerprint is None:
        return {"state": "unverified",
                "reason": "the bed was primed before the console recorded which plan it was for"}
    if primed.plan_fingerprint != plan_fingerprint(plan):
        return {"state": "other_plan",
                "reason": "the bed was primed for a different plan (layers or thickness changed)"}
    if primed.consumed_at is not None:
        return {"state": "used", "reason": "a print has already started from this primed bed"}
    return {"state": "ready", "reason": "primed for this plan"}
