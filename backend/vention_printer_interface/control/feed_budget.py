"""Feed-powder budget: will the powder in the feed column last the whole print?

The print consumes ``feed_thickness_mm`` of feed per layer (the feed piston rises that much each
layer — distinct from, and typically ~2x, the build piston's layer drop). Priming used to size the
feed from the build-piston thickness instead, and the print's exhaustion guard counted from a FULL
column (``feed_end_mm``) rather than the real feed position, so a short fill ran dry silently
(2026-09-22: a 184-layer job ran out of powder at layer ~52 with no warning).

The budget is computed by compiling the plan from the REAL feed position and seeing where its own
exhaustion guard fires, so the warning and the print can never disagree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from vention_printer_interface.control.print_settings import (
    FEED,
    PHASES,
    PrintSettings,
    compile_print,
)


@dataclass(frozen=True)
class FeedBudget:
    demand_mm: float  # feed the print consumes (sum of feed/layer x layers, enabled phases)
    available_mm: float | None  # powder column height at start; None = can't be verified
    layers_total: int  # layers the plan would run with unlimited powder
    layers_supported: int | None  # layers that run before the safe stop; None = unknown
    sufficient: bool | None  # None = unknown (never report "unknown" as enough)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def print_feed_demand_mm(plan: PrintSettings) -> float:
    """Feed the print consumes: feed per layer x layers over every phase that runs."""
    total = 0.0
    for name in PHASES:
        if name == "postcoat" and not plan.postcoat_enabled:
            continue
        ph = plan.phase(name)
        total += ph.feed_thickness_mm * ph.n_layers
    return total


def _layers_started(plan: PrintSettings, feed_start_mm: float | None) -> tuple[int, bool]:
    steps = compile_print(plan, feed_start_mm=feed_start_mm)
    started = sum(1 for s in steps if s.kind == "mark" and s.label == "layer_start")
    exhausted = bool(steps) and steps[-1].kind == "mark" and steps[-1].label == "feed_exhausted"
    return started, exhausted


def feed_budget(plan: PrintSettings, available_mm: float | None) -> FeedBudget:
    """Budget for ``plan`` given ``available_mm`` of powder in the feed (None = unknown)."""
    demand = print_feed_demand_mm(plan)
    total, _ = _layers_started(plan, None)
    if available_mm is None:
        return FeedBudget(demand, None, total, None, None)
    supported, exhausted = _layers_started(plan, available_mm)
    return FeedBudget(demand, available_mm, total, supported, not exhausted)


def live_feed_available_mm(snapshot: dict[str, Any]) -> tuple[float | None, str | None]:
    """Powder column height from a controller snapshot, or ``(None, reason)`` when it can't be
    trusted. The feed position is its depth below flush (0 = flush = empty), so the column height
    IS the position — but only once the axis is referenced: incremental drives read ~0 after a
    power-cycle until homed, and that must never pass as a real (empty or full) reading."""
    tel = snapshot.get("telemetry") if isinstance(snapshot, dict) else None
    if not tel:
        return None, "no controller telemetry — connect the printer"
    key = str(FEED)
    pos = (tel.get("positions") or {}).get(key)
    if not isinstance(pos, int | float):
        return None, "the feed piston position isn't reported"
    if not (tel.get("referenced") or {}).get(key):
        return None, ("the feed piston hasn't been homed since power-on, so its position (and the "
                      "powder it holds) can't be verified")
    return float(pos), None


__all__ = ["FeedBudget", "feed_budget", "live_feed_available_mm", "print_feed_demand_mm"]
