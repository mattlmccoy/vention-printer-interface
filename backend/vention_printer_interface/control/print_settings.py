"""Print settings and pure compiler (spec §4).

``PrintSettings`` is seeded from the constants in ``vention/python/V1.py`` (the lab's print script).
``compile_print`` turns a plan into a deterministic step list in exactly V1.py's order so the
step machine (``print_controller.py``) never has to know about phases. No IO here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from vention_printer_interface.control.safety import SafetyLimits

# Axis roles from vention/json/configuration.json (drive order) and V1.py lines 63-66.
PART = 1
FEED = 2
PRINTHEAD = 3
RECOATER = 4  # the recoater gantry also carries the IR heater (V1.py HEATER_* use recoater_axis)

PHASES = ("precoat", "printing", "postcoat")
MAX_LAYERS = 500
MAX_HEATER_PASSES = 10


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


@dataclass(frozen=True)
class PhasePlan:
    """Per-phase settings (V1.py lines 12-45)."""

    layer_thickness_mm: float = 2.0
    n_layers: int = 1
    part_speed: float = 2.5
    part_accel: float = 15.0
    feed_speed: float = 2.5
    feed_accel: float = 15.0
    printhead_speed: float = 100.0
    printhead_accel: float = 500.0
    recoater_speed: float = 100.0
    recoater_accel: float = 500.0

    @property
    def thickness_mm(self) -> float:
        return self.layer_thickness_mm * self.n_layers

    @classmethod
    def bounded(
        cls, data: dict[str, Any] | None, limits: SafetyLimits, base: PhasePlan
    ) -> PhasePlan:
        d = dict(data or {})

        def num(name: str, default: float) -> float:
            v = d.get(name, default)
            return float(v) if isinstance(v, int | float) else default

        n_layers = d.get("n_layers", base.n_layers)
        n_layers = int(n_layers) if isinstance(n_layers, int | float) else base.n_layers
        return cls(
            layer_thickness_mm=_clamp(
                num("layer_thickness_mm", base.layer_thickness_mm), 0.0, 50.0
            ),
            n_layers=int(_clamp(n_layers, 0, MAX_LAYERS)),
            part_speed=limits.clamp_speed(PART, num("part_speed", base.part_speed)),
            part_accel=limits.clamp_accel(PART, num("part_accel", base.part_accel)),
            feed_speed=limits.clamp_speed(FEED, num("feed_speed", base.feed_speed)),
            feed_accel=limits.clamp_accel(FEED, num("feed_accel", base.feed_accel)),
            printhead_speed=limits.clamp_speed(
                PRINTHEAD, num("printhead_speed", base.printhead_speed)
            ),
            printhead_accel=limits.clamp_accel(
                PRINTHEAD, num("printhead_accel", base.printhead_accel)
            ),
            recoater_speed=limits.clamp_speed(RECOATER, num("recoater_speed", base.recoater_speed)),
            recoater_accel=limits.clamp_accel(RECOATER, num("recoater_accel", base.recoater_accel)),
        )


@dataclass(frozen=True)
class PrintSettings:
    """The whole print (V1.py lines 12-66). Heater is opt-in; V1.py never switched it."""

    precoat: PhasePlan = field(
        default_factory=lambda: PhasePlan(layer_thickness_mm=5.0, n_layers=1)
    )
    printing: PhasePlan = field(
        default_factory=lambda: PhasePlan(layer_thickness_mm=2.0, n_layers=10)
    )
    postcoat: PhasePlan = field(
        default_factory=lambda: PhasePlan(layer_thickness_mm=5.0, n_layers=1)
    )
    feed_end_mm: float = 145.0  # V1.py:48 (pendant says ~151)
    recoater_home_mm: float = 5.0
    recoater_end_mm: float = 930.0
    heater_home_mm: float = 5.0
    heater_end_mm: float = 600.0
    printhead_home_mm: float = 5.0
    printhead_end_mm: float = 840.0
    heater_speed: float = 50.0
    heater_accel: float = 250.0
    n_heater_passes: int = 1
    heater_enabled: bool = False
    settle_s: float = 1.0  # V1.py's time.sleep(1) after the feed piston move
    feed_fast_speed: float = 5.0  # V1.py:95 used 1000 mm/s; bounded to the feed limit
    feed_fast_accel: float = 30.0  # V1.py:96 used 500

    @property
    def total_thickness_mm(self) -> float:
        return self.precoat.thickness_mm + self.printing.thickness_mm + self.postcoat.thickness_mm

    @property
    def total_layers(self) -> int:
        return self.precoat.n_layers + self.printing.n_layers + self.postcoat.n_layers

    def phase(self, name: str) -> PhasePlan:
        return {"precoat": self.precoat, "printing": self.printing, "postcoat": self.postcoat}[name]

    def validate(self, limits: SafetyLimits | None = None) -> list[str]:
        """Printability + travel checks (V1.py:74-78). Empty list = valid."""
        lim = limits or SafetyLimits()
        reasons: list[str] = []
        if self.total_thickness_mm > self.feed_end_mm:
            reasons.append(
                f"total thickness {self.total_thickness_mm:.1f} mm exceeds feed travel "
                f"{self.feed_end_mm:.1f} mm (V1.py printability check)"
            )
        for name in PHASES:
            ph = self.phase(name)
            if ph.n_layers > 0 and ph.layer_thickness_mm <= 0:
                reasons.append(f"{name}.layer_thickness_mm must be > 0 when n_layers > 0")
        positions = {
            "feed_end_mm": (FEED, self.feed_end_mm),
            "recoater_home_mm": (RECOATER, self.recoater_home_mm),
            "recoater_end_mm": (RECOATER, self.recoater_end_mm),
            "heater_home_mm": (RECOATER, self.heater_home_mm),
            "heater_end_mm": (RECOATER, self.heater_end_mm),
            "printhead_home_mm": (PRINTHEAD, self.printhead_home_mm),
            "printhead_end_mm": (PRINTHEAD, self.printhead_end_mm),
        }
        for label, (axis, value) in positions.items():
            lo, hi = lim.travel_min[axis], lim.travel_max[axis]
            if not lo <= value <= hi:
                reasons.append(f"{label}={value} outside axis {axis} travel [{lo}, {hi}]")
        if self.total_layers == 0:
            reasons.append("no layers to print")
        return reasons

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrintSettings:
        d = dict(data)
        base = cls()
        precoat = PhasePlan(**d.pop("precoat")) if "precoat" in d else base.precoat
        printing = PhasePlan(**d.pop("printing")) if "printing" in d else base.printing
        postcoat = PhasePlan(**d.pop("postcoat")) if "postcoat" in d else base.postcoat
        return cls(precoat=precoat, printing=printing, postcoat=postcoat, **d)

    @classmethod
    def bounded(cls, data: dict[str, Any] | None, limits: SafetyLimits) -> PrintSettings:
        """Build a plan from untrusted input, clamping every field into limits (tighten-only)."""
        base = cls()
        d = dict(data or {})

        def num(name: str, default: float) -> float:
            v = d.get(name, default)
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default

        passes = d.get("n_heater_passes", base.n_heater_passes)
        passes = int(passes) if isinstance(passes, int | float) else base.n_heater_passes
        return cls(
            precoat=PhasePlan.bounded(d.get("precoat"), limits, base.precoat),
            printing=PhasePlan.bounded(d.get("printing"), limits, base.printing),
            postcoat=PhasePlan.bounded(d.get("postcoat"), limits, base.postcoat),
            feed_end_mm=limits.clamp_position(FEED, num("feed_end_mm", base.feed_end_mm)),
            recoater_home_mm=limits.clamp_position(
                RECOATER, num("recoater_home_mm", base.recoater_home_mm)
            ),
            recoater_end_mm=limits.clamp_position(
                RECOATER, num("recoater_end_mm", base.recoater_end_mm)
            ),
            heater_home_mm=limits.clamp_position(
                RECOATER, num("heater_home_mm", base.heater_home_mm)
            ),
            heater_end_mm=limits.clamp_position(RECOATER, num("heater_end_mm", base.heater_end_mm)),
            printhead_home_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_home_mm", base.printhead_home_mm)
            ),
            printhead_end_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_end_mm", base.printhead_end_mm)
            ),
            heater_speed=limits.clamp_speed(RECOATER, num("heater_speed", base.heater_speed)),
            heater_accel=limits.clamp_accel(RECOATER, num("heater_accel", base.heater_accel)),
            n_heater_passes=int(_clamp(passes, 0, MAX_HEATER_PASSES)),
            heater_enabled=bool(d.get("heater_enabled", base.heater_enabled)),
            settle_s=_clamp(num("settle_s", base.settle_s), 0.0, 30.0),
            feed_fast_speed=limits.clamp_speed(FEED, num("feed_fast_speed", base.feed_fast_speed)),
            feed_fast_accel=limits.clamp_accel(FEED, num("feed_fast_accel", base.feed_fast_accel)),
        )


@dataclass(frozen=True)
class Step:
    """One primitive action. kind: home_all | set_speed | set_accel | move_abs | move_rel |
    wait | dwell | heater | mark. `value` is mm, mm/s, mm/s^2, seconds, or 1/0 for heater."""

    index: int
    phase: str
    layer: int
    kind: str
    axis: int | None = None
    value: float | None = None
    label: str = ""
    part_height_mm: float = 0.0


def compile_print(plan: PrintSettings) -> tuple[Step, ...]:
    """V1.py lines 80-190, phase by phase. Deterministic; unit-tested against the script."""
    out: list[Step] = []
    height = 0.0

    def add(
        phase: str,
        layer: int,
        kind: str,
        axis: int | None = None,
        value: float | None = None,
        label: str = "",
    ) -> None:
        out.append(Step(len(out), phase, layer, kind, axis, value, label, height))

    # Print setup (V1.py:80-97): home all, then feed piston down at "fast" speed.
    add("setup", 0, "home_all")
    add("setup", 0, "wait")
    add("setup", 0, "set_speed", FEED, plan.feed_fast_speed)
    add("setup", 0, "set_accel", FEED, plan.feed_fast_accel)
    add("setup", 0, "move_abs", FEED, plan.feed_end_mm)
    add("setup", 0, "wait")

    layer_no = 0
    for name in PHASES:
        ph = plan.phase(name)
        if ph.n_layers == 0:
            continue
        # Phase speeds/accels (V1.py:101-108, 133-138, 165-172).
        add(name, layer_no, "set_speed", PART, ph.part_speed)
        add(name, layer_no, "set_accel", PART, ph.part_accel)
        add(name, layer_no, "set_speed", FEED, ph.feed_speed)
        add(name, layer_no, "set_accel", FEED, ph.feed_accel)
        add(name, layer_no, "set_speed", PRINTHEAD, ph.printhead_speed)
        add(name, layer_no, "set_accel", PRINTHEAD, ph.printhead_accel)
        add(name, layer_no, "set_speed", RECOATER, ph.recoater_speed)
        add(name, layer_no, "set_accel", RECOATER, ph.recoater_accel)
        for idx in range(ph.n_layers):
            layer_no += 1
            t = ph.layer_thickness_mm
            height += t
            if name == "printing" and idx > 0:
                # V1.py:125-127 resets recoater speed at the top of each print layer
                # (the heater passes changed it).
                add(name, layer_no, "set_speed", RECOATER, ph.recoater_speed)
                add(name, layer_no, "set_accel", RECOATER, ph.recoater_accel)
            add(name, layer_no, "mark", label="layer_start")
            add(name, layer_no, "move_rel", PART, t)  # part piston down
            add(name, layer_no, "wait")
            add(name, layer_no, "move_abs", RECOATER, plan.recoater_end_mm)  # spread
            add(name, layer_no, "wait")
            add(name, layer_no, "move_rel", FEED, -t)  # feed piston up (negative = up)
            add(name, layer_no, "wait")
            add(name, layer_no, "dwell", value=plan.settle_s)  # V1.py's time.sleep(1)
            add(name, layer_no, "move_abs", RECOATER, plan.recoater_home_mm)
            add(name, layer_no, "wait")
            if name == "printing":
                add(name, layer_no, "move_abs", PRINTHEAD, plan.printhead_end_mm)  # jet pass
                add(name, layer_no, "wait")
                add(name, layer_no, "move_abs", PRINTHEAD, plan.printhead_home_mm)
                add(name, layer_no, "wait")
                add(name, layer_no, "set_speed", RECOATER, plan.heater_speed)  # evaporate ink
                add(name, layer_no, "set_accel", RECOATER, plan.heater_accel)
                if plan.heater_enabled:
                    add(name, layer_no, "heater", value=1.0)
                for _ in range(plan.n_heater_passes):
                    add(name, layer_no, "move_abs", RECOATER, plan.heater_end_mm)
                    add(name, layer_no, "wait")
                    add(name, layer_no, "move_abs", RECOATER, plan.heater_home_mm)
                    add(name, layer_no, "wait")
                if plan.heater_enabled:
                    add(name, layer_no, "heater", value=0.0)
            add(name, layer_no, "mark", label="layer_end")
    return tuple(out)


# Homing speeds (mm/s) from vention/json/configuration.json; travel from safety.TRAVEL_MM.
_HOMING = {PART: 68.8, FEED: 68.8, PRINTHEAD: 66.3, RECOATER: 66.3}
_TRAVEL = {PART: 145.0, FEED: 145.0, PRINTHEAD: 970.0, RECOATER: 972.0}


def estimate_duration_s(plan: PrintSettings, min_wait_s: float = 0.5) -> float:
    """Rough wall-clock estimate: constant-velocity moves at the commanded speed, dwells, and
    homing at the configured homing speed; acceleration is ignored (mirrored in the UI)."""
    speed = {PART: 5.0, FEED: 5.0, PRINTHEAD: 100.0, RECOATER: 100.0}
    pos = dict.fromkeys(speed, 0.0)
    total = 0.0
    pending = 0.0
    for step in compile_print(plan):
        if step.kind == "home_all":
            pending = max(_TRAVEL[a] / _HOMING[a] for a in speed) * 0.5  # typically half travel
        elif step.kind == "set_speed" and step.axis is not None:
            speed[step.axis] = max(float(step.value or 0.1), 0.1)
        elif step.kind in ("move_abs", "move_rel") and step.axis is not None:
            target = (
                float(step.value or 0.0)
                if step.kind == "move_abs"
                else pos[step.axis] + float(step.value or 0.0)
            )
            pending = max(pending, abs(target - pos[step.axis]) / speed[step.axis])
            pos[step.axis] = target
        elif step.kind == "wait":
            total += max(pending, min_wait_s)
            pending = 0.0
        elif step.kind == "dwell":
            total += float(step.value or 0.0)
    return round(total + pending, 1)
