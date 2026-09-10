"""Powder-prep / priming ("priming job") routine — the operator's powder-handling script compiled
to the same Step list the print engine runs (2026-09-09).

Runs FIRST, before a print: it lays thick precoat layers, then nominal feed layers, spreading powder
across the bed until the feed piston is exhausted, then homes the recoater. It NEVER homes a piston
(homing a piston drives it fully up/flush and ejects powder); the part/feed pistons are positioned
by the earlier homing script and this routine only moves them relatively from there.

Sign conventions (piston mechanics): part piston move_rel + = DOWN, feed piston move_rel - = UP.
Faithful to the script's float loop so the compiled sequence is exactly what the script would run.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from vention_printer_interface.control.print_settings import FEED, PART, RECOATER, Step
from vention_printer_interface.control.safety import SafetyLimits

MAX_CYCLES_CAP = 1000


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


@dataclass(frozen=True)
class PrimingSettings:
    """The powder-handling script's parameters (defaults = the script's constants)."""

    thick_precoat_layer_mm: float = 5.0  # THICK_PRECOAT_LAYER
    thick_precoat_count: int = 3  # THICK_PRECOAT_COUNT
    nominal_layer_thickness_mm: float = 0.2  # NOMINAL_LAYER_THICKNESS (part descent)
    nominal_feed_thickness_mm: float = 0.8  # NOMINAL_FEED_THICKNESS (feed rise)
    piston_break_mm: float = 1.0  # PISTON_BREAK_DISTANCE (unstick move)
    part_speed: float = 2.5  # PART_SPEED
    part_accel: float = 15.0  # PART_ACCEL
    feed_speed: float = 2.5  # FEED_SPEED
    feed_accel: float = 15.0  # FEED_ACCEL
    recoater_speed: float = 100.0  # RECOATER_SPEED
    recoater_accel: float = 500.0  # RECOATER_ACCEL
    feed_floor_mm: float = 3.0  # FEED_PISTON_ABSOLUTE_POSITION (stop threshold)
    max_travel_mm: float = 60.0  # MAX_TRAVEL clamp on a single piston move
    recoater_end_mm: float = 925.0  # RECOATER_END_POSITION (spread stroke end)
    recoater_return_mm: float = 350.0  # RECOATER_RETURN_POSITION (park between layers)
    feed_start_mm: float = 30.0  # feed position handed off from the homing script
    settle_s: float = 1.0  # time.sleep(1) after each feed move
    max_cycles: int = 100  # script's range(100) upper bound

    def validate(self, limits: SafetyLimits | None = None) -> list[str]:
        lim = limits or SafetyLimits()
        reasons: list[str] = []
        for label, value in (
            ("recoater_end_mm", self.recoater_end_mm),
            ("recoater_return_mm", self.recoater_return_mm),
        ):
            lo, hi = lim.travel_min[RECOATER], lim.travel_max[RECOATER]
            if not lo <= value <= hi:
                reasons.append(f"{label}={value} outside recoater travel [{lo}, {hi}]")
        if self.nominal_feed_thickness_mm <= 0:
            reasons.append("nominal_feed_thickness_mm must be > 0 (the loop would never advance)")
        if self.feed_start_mm <= self.feed_floor_mm:
            reasons.append(
                f"feed_start_mm={self.feed_start_mm} must be above "
                f"feed_floor_mm={self.feed_floor_mm}"
            )
        if self.max_cycles <= 0:
            reasons.append("max_cycles must be > 0")
        return reasons

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrimingSettings:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})

    @classmethod
    def bounded(cls, data: dict[str, Any] | None, limits: SafetyLimits) -> PrimingSettings:
        """Build from untrusted input, clamping speeds/accels/positions into the safety limits."""
        base = cls()
        d = dict(data or {})

        def num(name: str, default: float) -> float:
            v = d.get(name, default)
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default

        count = d.get("thick_precoat_count", base.thick_precoat_count)
        count = int(count) if isinstance(count, int | float) else base.thick_precoat_count
        cycles = d.get("max_cycles", base.max_cycles)
        cycles = int(cycles) if isinstance(cycles, int | float) else base.max_cycles

        def mm(name: str, hi: float = 50.0) -> float:
            return _clamp(num(name, float(getattr(base, name))), 0.0, hi)

        def sp(axis: int, name: str) -> float:
            return limits.clamp_speed(axis, num(name, float(getattr(base, name))))

        def ac(axis: int, name: str) -> float:
            return limits.clamp_accel(axis, num(name, float(getattr(base, name))))

        def pos(name: str) -> float:
            return limits.clamp_position(RECOATER, num(name, float(getattr(base, name))))

        return cls(
            thick_precoat_layer_mm=mm("thick_precoat_layer_mm"),
            thick_precoat_count=int(_clamp(count, 0, 100)),
            nominal_layer_thickness_mm=mm("nominal_layer_thickness_mm"),
            nominal_feed_thickness_mm=mm("nominal_feed_thickness_mm"),
            piston_break_mm=mm("piston_break_mm", 10.0),
            part_speed=sp(PART, "part_speed"),
            part_accel=ac(PART, "part_accel"),
            feed_speed=sp(FEED, "feed_speed"),
            feed_accel=ac(FEED, "feed_accel"),
            recoater_speed=sp(RECOATER, "recoater_speed"),
            recoater_accel=ac(RECOATER, "recoater_accel"),
            feed_floor_mm=mm("feed_floor_mm", 145.0),
            max_travel_mm=mm("max_travel_mm", 145.0),
            recoater_end_mm=pos("recoater_end_mm"),
            recoater_return_mm=pos("recoater_return_mm"),
            feed_start_mm=mm("feed_start_mm", 145.0),
            settle_s=_clamp(num("settle_s", base.settle_s), 0.0, 30.0),
            max_cycles=int(_clamp(cycles, 1, MAX_CYCLES_CAP)),
        )


def compile_priming(s: PrimingSettings, limits: SafetyLimits) -> tuple[Step, ...]:
    """Expand the powder-handling script into a deterministic Step list. Mirrors the script's float
    loop exactly (so the compiled run == what the script would do). Homes only the recoater."""
    out: list[Step] = []

    def add(phase: str, layer: int, kind: str, axis: int | None = None,
            value: float | None = None, label: str = "") -> None:
        out.append(Step(len(out), phase, layer, kind, axis, value, label, 0.0))

    # Speeds/accels for all three moving axes (clamped). The script sets the recoater explicitly and
    # defines part/feed speeds as constants; we command all three so the routine isn't at the mercy
    # of whatever the pendant last set (a safety improvement over the raw script).
    add("setup", 0, "set_speed", PART, limits.clamp_speed(PART, s.part_speed))
    add("setup", 0, "set_accel", PART, limits.clamp_accel(PART, s.part_accel))
    add("setup", 0, "set_speed", FEED, limits.clamp_speed(FEED, s.feed_speed))
    add("setup", 0, "set_accel", FEED, limits.clamp_accel(FEED, s.feed_accel))
    add("setup", 0, "set_speed", RECOATER, limits.clamp_speed(RECOATER, s.recoater_speed))
    add("setup", 0, "set_accel", RECOATER, limits.clamp_accel(RECOATER, s.recoater_accel))

    # Initial thick-precoat drop of the part piston (script: before the loop).
    add("setup", 0, "move_rel", PART, s.thick_precoat_layer_mm, "thick precoat drop")
    add("setup", 0, "wait")

    current_feed = s.feed_start_mm
    cycle = 0
    while cycle < s.max_cycles:
        layer = cycle + 1
        thickness = (
            s.thick_precoat_layer_mm if cycle < s.thick_precoat_count
            else s.nominal_feed_thickness_mm
        )
        add("priming", layer, "mark", label="layer_start")
        if cycle >= s.thick_precoat_count:
            # nominal: drop part by (layer + break), then back up by the break distance
            down = min(s.nominal_layer_thickness_mm + s.piston_break_mm, s.max_travel_mm)
            add("priming", layer, "move_rel", PART, down, "part down")
            add("priming", layer, "wait")
            add("priming", layer, "move_rel", PART, -s.piston_break_mm, "piston break")
            add("priming", layer, "wait")
        add("priming", layer, "move_abs", RECOATER, s.recoater_end_mm, "spread")
        add("priming", layer, "wait")
        next_feed = current_feed - thickness
        if next_feed <= s.feed_floor_mm:
            add("priming", layer, "home", RECOATER, None, "feed exhausted → home recoater")
            add("priming", layer, "wait")
            add("priming", layer, "mark", label="layer_end")
            break
        add("priming", layer, "move_rel", FEED, -min(thickness, s.max_travel_mm), "feed up")
        add("priming", layer, "wait")
        current_feed = next_feed
        add("priming", layer, "move_abs", RECOATER, s.recoater_return_mm, "return")
        add("priming", layer, "wait")
        add("priming", layer, "dwell", value=s.settle_s)
        add("priming", layer, "mark", label="layer_end")
        cycle += 1
    return tuple(out)
