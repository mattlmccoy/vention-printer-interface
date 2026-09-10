"""Priming = job SETUP (spec §6): build/part piston UP (flush), feed piston DOWN to open a powder
cavity, HOLD for the operator to load powder, then the THICK PRECOATS that fill the runway and the
part-piston cavity. The part piston is FIXED throughout the thick precoats (backfill) — the thin
precoats, where the part piston first drops, are the start of the Print routine. Never homes a
piston.

Sign conventions: part/feed move_abs to a SMALL value = UP/flush, LARGE = DOWN; a feed move_rel of a
NEGATIVE amount advances the feed piston UP (supplies powder), matching compile_print.
Defaults are calibration-pending starting points, not validated values.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from vention_printer_interface.control.print_settings import FEED, PART, RECOATER, Step
from vention_printer_interface.control.safety import SafetyLimits

MAX_THICK_PRECOATS = 20


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


@dataclass(frozen=True)
class PrimingSettings:
    part_top_mm: float = 0.0
    feed_cavity_mm: float = 30.0
    level_recoat_end_mm: float = 925.0
    level_recoat_start_mm: float = 350.0
    n_thick_precoats: int = 3
    thick_feed_mm: float = 7.0
    part_speed: float = 2.5
    part_accel: float = 15.0
    feed_speed: float = 2.5
    feed_accel: float = 15.0
    recoater_speed: float = 100.0
    recoater_accel: float = 500.0
    settle_s: float = 1.0

    def validate(self, limits: SafetyLimits | None = None) -> list[str]:
        lim = limits or SafetyLimits()
        reasons: list[str] = []
        checks = (
            ("part_top_mm", PART, self.part_top_mm),
            ("feed_cavity_mm", FEED, self.feed_cavity_mm),
            ("level_recoat_end_mm", RECOATER, self.level_recoat_end_mm),
            ("level_recoat_start_mm", RECOATER, self.level_recoat_start_mm),
        )
        for label, axis, v in checks:
            lo, hi = lim.travel_min[axis], lim.travel_max[axis]
            if not lo <= v <= hi:
                reasons.append(f"{label}={v} outside axis {axis} travel [{lo}, {hi}]")
        if self.n_thick_precoats <= 0:
            reasons.append("n_thick_precoats must be > 0")
        return reasons

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimingSettings:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})

    @classmethod
    def bounded(cls, data: dict[str, Any] | None, limits: SafetyLimits) -> PrimingSettings:
        base = cls()
        d = dict(data or {})

        def num(name: str) -> float:
            v = d.get(name, getattr(base, name))
            if isinstance(v, int | float) and not isinstance(v, bool):
                return float(v)
            return float(getattr(base, name))

        passes = d.get("n_thick_precoats", base.n_thick_precoats)
        passes = int(passes) if isinstance(passes, int | float) else base.n_thick_precoats
        return cls(
            part_top_mm=limits.clamp_position(PART, num("part_top_mm")),
            feed_cavity_mm=limits.clamp_position(FEED, num("feed_cavity_mm")),
            level_recoat_end_mm=limits.clamp_position(RECOATER, num("level_recoat_end_mm")),
            level_recoat_start_mm=limits.clamp_position(RECOATER, num("level_recoat_start_mm")),
            n_thick_precoats=int(_clamp(passes, 1, MAX_THICK_PRECOATS)),
            thick_feed_mm=_clamp(num("thick_feed_mm"), 0.0, 50.0),
            part_speed=limits.clamp_speed(PART, num("part_speed")),
            part_accel=limits.clamp_accel(PART, num("part_accel")),
            feed_speed=limits.clamp_speed(FEED, num("feed_speed")),
            feed_accel=limits.clamp_accel(FEED, num("feed_accel")),
            recoater_speed=limits.clamp_speed(RECOATER, num("recoater_speed")),
            recoater_accel=limits.clamp_accel(RECOATER, num("recoater_accel")),
            settle_s=_clamp(num("settle_s"), 0.0, 30.0),
        )


def compile_priming_setup(s: PrimingSettings, limits: SafetyLimits) -> tuple[Step, ...]:
    """Position pistons -> HOLD for the powder load -> THICK PRECOATS that fill the runway and the
    part cavity. Each thick precoat spreads powder across the bed and advances the feed piston; the
    part piston NEVER moves (it stays fixed to backfill). The spread IS the leveling — there is no
    separate level step. Never homes a piston."""
    out: list[Step] = []

    def add(kind: str, axis: int | None = None, value: float | None = None,
            label: str = "") -> None:
        out.append(Step(len(out), "setup", 0, kind, axis, value, label, 0.0))

    add("set_speed", PART, limits.clamp_speed(PART, s.part_speed))
    add("set_accel", PART, limits.clamp_accel(PART, s.part_accel))
    add("set_speed", FEED, limits.clamp_speed(FEED, s.feed_speed))
    add("set_accel", FEED, limits.clamp_accel(FEED, s.feed_accel))
    add("set_speed", RECOATER, limits.clamp_speed(RECOATER, s.recoater_speed))
    add("set_accel", RECOATER, limits.clamp_accel(RECOATER, s.recoater_accel))

    add("move_abs", PART, s.part_top_mm, "build piston up")
    add("wait")
    add("move_abs", FEED, s.feed_cavity_mm, "feed piston down (open powder cavity)")
    add("wait")
    add("hold", None, None, "Load powder into the feed cavity, then Resume")
    for _ in range(s.n_thick_precoats):
        # Part piston stays FIXED for every thick precoat — the feed advance backfills the runway
        # and fills the part cavity; the part piston first drops only in the print's thin precoats.
        add("move_abs", RECOATER, s.level_recoat_start_mm, "move to start (past feed piston)")
        add("wait")
        add("move_abs", RECOATER, s.level_recoat_end_mm, "spread across the bed")
        add("wait")
        add("move_rel", FEED, -s.thick_feed_mm, "feed up — supply powder")  # part FIXED
        add("wait")
        add("dwell", value=s.settle_s)
    add("mark", label="priming_done")
    return tuple(out)
