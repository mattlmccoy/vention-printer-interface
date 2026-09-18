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

PHASES = ("thin_precoat", "printing", "postcoat")
MAX_LAYERS = 500
MAX_HEATER_PASSES = 10
PURGE_MODES = ("every_pass", "per_layer", "every_n_layers")
# The three per-layer capture stages, in the order compile_print emits them. capture_stages_enabled
# is a subset of these (#2 per-stage selection); canonical order is always preserved on output.
CAPTURE_STAGE_ORDER = ("pre_jet", "post_jet", "post_heat")


def canonical_capture_stages(value: Any) -> tuple[str, ...]:
    """Filter untrusted input to the valid capture stages, deduped, in canonical order."""
    if not isinstance(value, list | tuple):
        return CAPTURE_STAGE_ORDER
    picked = {v for v in value if v in CAPTURE_STAGE_ORDER}
    return tuple(s for s in CAPTURE_STAGE_ORDER if s in picked)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


LAYER_HEIGHT_QUANTUM_MM = 0.1  # the MachineMotion build-piston position-readout floor


def _snap_layer_height(mm: float) -> float:
    """Snap a build-piston layer thickness to the achievable 0.1 mm readout grid. A value between
    quanta (0.05, 0.15, ...) can't be placed OR verified — the readout resolves nothing finer than
    0.1 mm — so it's rounded to the nearest 0.1 mm level, floored at one quantum. A non-positive
    thickness (a disabled phase) is preserved as 0. Mirrors the UI gate (lib/layer_height.ts)."""
    if mm <= 0:
        return 0.0
    tenths = max(1, round(mm / LAYER_HEIGHT_QUANTUM_MM + 1e-9))
    return round(tenths * LAYER_HEIGHT_QUANTUM_MM, 4)


@dataclass(frozen=True)
class PhasePlan:
    """Per-phase settings (V1.py lines 12-45)."""

    layer_thickness_mm: float = 2.0  # build-piston drop per layer
    feed_thickness_mm: float = 2.0  # feed-piston advance per layer (V1.py; distinct from the drop)
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
            layer_thickness_mm=_snap_layer_height(
                _clamp(num("layer_thickness_mm", base.layer_thickness_mm), 0.0, 50.0)
            ),
            feed_thickness_mm=_clamp(
                num("feed_thickness_mm", base.feed_thickness_mm), 0.0, 50.0
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
    """The whole print (V1.py lines 12-66). Heater is opt-in; V1.py never switched it.

    The thick precoats now live in the priming routine (they fill the runway + part cavity with the
    build piston fixed). The print begins at the thin precoats, where the build piston first drops.
    """

    thin_precoat: PhasePlan = field(
        default_factory=lambda: PhasePlan(
            layer_thickness_mm=0.2, feed_thickness_mm=0.4, n_layers=2
        )
    )
    printing: PhasePlan = field(
        default_factory=lambda: PhasePlan(
            layer_thickness_mm=2.0, feed_thickness_mm=0.4, n_layers=10
        )
    )
    postcoat: PhasePlan = field(
        default_factory=lambda: PhasePlan(
            layer_thickness_mm=5.0, feed_thickness_mm=0.0, n_layers=1
        )
    )
    n_jet_passes: int = 1
    pre_heater_drop_mm: float = 0.0
    postcoat_enabled: bool = True
    feed_end_mm: float = 145.0  # V1.py:48 (pendant says ~151)
    recoater_home_mm: float = 5.0
    recoater_return_mm: float = 350.0  # V1.py precoat recoater return position
    recoater_end_mm: float = 950.0
    heater_home_mm: float = 5.0
    heater_start_mm: float = 425.0  # V1.py heater sweep start
    heater_end_mm: float = 600.0
    printhead_home_mm: float = 5.0
    printhead_end_mm: float = 900.0
    printhead_multipass_return_mm: float = 250.0  # between multipass passes; home only on the last
    printhead_start_mm: float = 250.0  # printhead parks here after setup-home, before layer 1
    # Nozzle purge: firing is external, so this only DWELLS the printhead at printhead_start_mm
    # before a jet pass (a window for the external printhead controller to purge). 0 s = off.
    purge_dwell_s: float = 0.0
    purge_mode: str = "per_layer"  # "every_pass" | "per_layer" | "every_n_layers"
    purge_every_n_layers: int = 5  # used when purge_mode == "every_n_layers"
    # Absolute printhead position (mm) where the nozzle-purge dwell happens. None => fall back to
    # printhead_start_mm (preserves the original behavior of holding at the printhead start).
    purge_position_mm: float | None = None
    part_max_mm: float = 72.0  # final part-cylinder drop position (= part spill-safe depth)
    heater_speed: float = 50.0
    heater_accel: float = 250.0
    n_heater_passes: int = 1
    heater_enabled: bool = False
    settle_s: float = 1.0  # V1.py's time.sleep(1) after the feed piston move
    feed_backlash_mm: float = 0.0  # opt-in: drop the feed this much BEFORE the spread; the
    # post-spread feed-up covers it too (net advance unchanged, approached from below to take slop)
    # Opt-in anti-backlash on the BUILD-piston layer drop: overshoot DOWN past the layer target by
    # this much, then return UP to it (net descent = layer_thickness). The piston sweep (2026-09-16)
    # showed ~0.15 mm takes 0.1-0.3 mm layer steps from ~55-67% on-target to ~100% (backlash
    # <0.1 mm, so the drop/double "interlayer scatter" is real, compensable lost-motion). 0 = off.
    build_backlash_mm: float = 0.0
    feed_fast_speed: float = 5.0  # V1.py:95 used 1000 mm/s; bounded to the feed limit
    feed_fast_accel: float = 30.0  # V1.py:96 used 500
    # Heater-exposure model inputs (spec §8; consumed by heater_model.exposure).
    target_carbon_wt: float = 0.15
    part_area_mm2: float = 900.0
    powder_density_g_cm3: float = 1.01
    ink_carbon_wt: float = 0.25
    ipa_dhvap_j_g: float = 663.0
    heater_section_power_w: float = 75.0
    # When True, compile_print emits capture:pre_jet / capture:post_jet / capture:post_heat marks
    # at the commissioned overhead pose in each printing layer for the vision package to key stage
    # captures off of. OFF by default until the camera and capture pose are commissioned.
    capture_stages: bool = False
    # Which of the three stage marks compile_print emits when capture_stages is on (#2 per-stage
    # selection). Default = all three (so enabling captures behaves exactly as before). An operator
    # can trim this to capture just 1 or 2 stages and save disk. Canonical stage order is preserved.
    capture_stages_enabled: tuple[str, ...] = CAPTURE_STAGE_ORDER
    # Overhead science camera rides the recoater gantry. When >0 (and capture_stages on), the
    # per-layer capture drives the recoater to this ABSOLUTE pose (centred over the bed), dwells
    # capture_settle_s to let vibration settle, then shoots — imaging the freshly printed layer at
    # the constant recoat plane (so scale/focus don't drift across the build). 0 = fixed camera:
    # emit the capture mark in place, no capture move (the original behaviour).
    capture_recoater_mm: float = 0.0
    capture_settle_s: float = 0.5
    # Hold the machine still after a browser capture trigger. The trigger is asynchronous; without
    # this dwell, the next move can begin while the browser is exposing/transferring the frame.
    capture_hold_s: float = 2.0

    @property
    def total_thickness_mm(self) -> float:
        postcoat = self.postcoat.thickness_mm if self.postcoat_enabled else 0.0
        return self.thin_precoat.thickness_mm + self.printing.thickness_mm + postcoat

    @property
    def total_layers(self) -> int:
        postcoat = self.postcoat.n_layers if self.postcoat_enabled else 0
        return self.thin_precoat.n_layers + self.printing.n_layers + postcoat

    def phase(self, name: str) -> PhasePlan:
        return {
            "thin_precoat": self.thin_precoat,
            "printing": self.printing,
            "postcoat": self.postcoat,
        }[name]

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
            # A disabled postcoat is dropped from the compiled plan and excluded from the totals,
            # so its degenerate fields must not raise a validation reason.
            if name == "postcoat" and not self.postcoat_enabled:
                continue
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
            "printhead_multipass_return_mm": (PRINTHEAD, self.printhead_multipass_return_mm),
            "printhead_start_mm": (PRINTHEAD, self.printhead_start_mm),
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
        if "capture_stages_enabled" in d:  # asdict() emits a list; keep the field a tuple
            d["capture_stages_enabled"] = tuple(d["capture_stages_enabled"])
        thin = PhasePlan(**d.pop("thin_precoat")) if "thin_precoat" in d else base.thin_precoat
        printing = PhasePlan(**d.pop("printing")) if "printing" in d else base.printing
        postcoat = PhasePlan(**d.pop("postcoat")) if "postcoat" in d else base.postcoat
        return cls(
            thin_precoat=thin,
            printing=printing,
            postcoat=postcoat,
            **d,
        )

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
        jet_passes = d.get("n_jet_passes", base.n_jet_passes)
        jet_passes = int(jet_passes) if isinstance(jet_passes, int | float) else base.n_jet_passes
        p_mode = d.get("purge_mode", base.purge_mode)
        p_mode = p_mode if p_mode in PURGE_MODES else base.purge_mode
        p_every = d.get("purge_every_n_layers", base.purge_every_n_layers)
        p_every = int(p_every) if isinstance(p_every, int | float) else base.purge_every_n_layers
        p_pos_raw = d.get("purge_position_mm", base.purge_position_mm)
        # None keeps the printhead_start_mm fallback; a set value is clamped like other positions.
        p_pos = (
            limits.clamp_position(PRINTHEAD, float(p_pos_raw))
            if isinstance(p_pos_raw, int | float) and not isinstance(p_pos_raw, bool)
            else None
        )
        return cls(
            thin_precoat=PhasePlan.bounded(d.get("thin_precoat"), limits, base.thin_precoat),
            printing=PhasePlan.bounded(d.get("printing"), limits, base.printing),
            postcoat=PhasePlan.bounded(d.get("postcoat"), limits, base.postcoat),
            n_jet_passes=int(_clamp(jet_passes, 1, 10)),
            pre_heater_drop_mm=_clamp(
                num("pre_heater_drop_mm", base.pre_heater_drop_mm), 0.0, 50.0
            ),
            postcoat_enabled=bool(d.get("postcoat_enabled", base.postcoat_enabled)),
            feed_end_mm=limits.clamp_position(FEED, num("feed_end_mm", base.feed_end_mm)),
            recoater_home_mm=limits.clamp_position(
                RECOATER, num("recoater_home_mm", base.recoater_home_mm)
            ),
            recoater_return_mm=limits.clamp_position(
                RECOATER, num("recoater_return_mm", base.recoater_return_mm)
            ),
            recoater_end_mm=limits.clamp_position(
                RECOATER, num("recoater_end_mm", base.recoater_end_mm)
            ),
            heater_home_mm=limits.clamp_position(
                RECOATER, num("heater_home_mm", base.heater_home_mm)
            ),
            heater_start_mm=limits.clamp_position(
                RECOATER, num("heater_start_mm", base.heater_start_mm)
            ),
            heater_end_mm=limits.clamp_position(RECOATER, num("heater_end_mm", base.heater_end_mm)),
            printhead_home_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_home_mm", base.printhead_home_mm)
            ),
            printhead_end_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_end_mm", base.printhead_end_mm)
            ),
            printhead_multipass_return_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_multipass_return_mm", base.printhead_multipass_return_mm)
            ),
            printhead_start_mm=limits.clamp_position(
                PRINTHEAD, num("printhead_start_mm", base.printhead_start_mm)
            ),
            part_max_mm=limits.clamp_position(PART, num("part_max_mm", base.part_max_mm)),
            heater_speed=limits.clamp_speed(RECOATER, num("heater_speed", base.heater_speed)),
            heater_accel=limits.clamp_accel(RECOATER, num("heater_accel", base.heater_accel)),
            n_heater_passes=int(_clamp(passes, 0, MAX_HEATER_PASSES)),
            heater_enabled=bool(d.get("heater_enabled", base.heater_enabled)),
            settle_s=_clamp(num("settle_s", base.settle_s), 0.0, 30.0),
            feed_backlash_mm=_clamp(num("feed_backlash_mm", base.feed_backlash_mm), 0.0, 50.0),
            build_backlash_mm=_clamp(num("build_backlash_mm", base.build_backlash_mm), 0.0, 5.0),
            purge_dwell_s=_clamp(num("purge_dwell_s", base.purge_dwell_s), 0.0, 60.0),
            purge_mode=p_mode,
            purge_every_n_layers=int(_clamp(p_every, 1, MAX_LAYERS)),
            purge_position_mm=p_pos,
            feed_fast_speed=limits.clamp_speed(FEED, num("feed_fast_speed", base.feed_fast_speed)),
            feed_fast_accel=limits.clamp_accel(FEED, num("feed_fast_accel", base.feed_fast_accel)),
            target_carbon_wt=_clamp(
                num("target_carbon_wt", base.target_carbon_wt), 0.0, 0.95
            ),
            part_area_mm2=_clamp(num("part_area_mm2", base.part_area_mm2), 1e-6, 1e6),
            powder_density_g_cm3=_clamp(
                num("powder_density_g_cm3", base.powder_density_g_cm3), 1e-6, 1e3
            ),
            ink_carbon_wt=_clamp(num("ink_carbon_wt", base.ink_carbon_wt), 0.0, 0.95),
            ipa_dhvap_j_g=_clamp(num("ipa_dhvap_j_g", base.ipa_dhvap_j_g), 1e-6, 1e5),
            heater_section_power_w=_clamp(
                num("heater_section_power_w", base.heater_section_power_w), 1e-6, 1e5
            ),
            capture_stages=bool(d.get("capture_stages", base.capture_stages)),
            capture_stages_enabled=(
                canonical_capture_stages(d["capture_stages_enabled"])
                if "capture_stages_enabled" in d
                else base.capture_stages_enabled
            ),
            capture_recoater_mm=_clamp(
                num("capture_recoater_mm", base.capture_recoater_mm), 0.0, base.recoater_end_mm
            ),
            capture_settle_s=_clamp(num("capture_settle_s", base.capture_settle_s), 0.0, 10.0),
            capture_hold_s=_clamp(num("capture_hold_s", base.capture_hold_s), 0.0, 10.0),
        )


@dataclass(frozen=True)
class Step:
    """One primitive action. kind: home_all | home | set_speed | set_accel | move_abs | move_rel |
    wait | dwell | heater | mark. `value` is mm, mm/s, mm/s^2, seconds, or 1/0 for heater."""

    index: int
    phase: str
    layer: int
    kind: str
    axis: int | None = None
    value: float | None = None
    label: str = ""
    part_height_mm: float = 0.0
    # For printing-phase capture marks: the 1-based PRINTING layer index (excludes precoats). The
    # `layer` above is the absolute layer_no; the CAD slice + layer labels key off this. Else None.
    print_layer: int | None = None


# The feed piston's hard floor (script FEED_HOME_POS): a feed advance that would carry the running
# feed position to or below this cannot supply another layer, so the compiler stops (see below).
FEED_FLOOR_MM = 0.0

# Precoat-style phases lay a cover layer only: spread -> feed advance -> recoater return to 350.
# thin_precoat drops the part one nominal layer; postcoat is a post-job cover pass that holds the
# part fixed (the FINISH drives part->max). The thick precoats now live in the priming routine.
_PRECOAT_PHASES = ("thin_precoat", "postcoat")
# Phases that drop the build piston one layer (grow the part height).
_PART_DROP_PHASES = ("thin_precoat", "printing")


def compile_print(plan: PrintSettings) -> tuple[Step, ...]:
    """Compile a plan into the faithful async-lab-script step sequence (fidelity spec 2026-09-10).

    Primed start: setup homes the two gantries ONLY (printhead, recoater); the part and feed pistons
    start from the captured primed bed, so no piston home and no feed pre-position move are emitted.
    Deterministic and unit-tested cycle-by-cycle against the script (``test_print_settings.py``).
    """
    out: list[Step] = []
    height = 0.0

    def add(
        phase: str,
        layer: int,
        kind: str,
        axis: int | None = None,
        value: float | None = None,
        label: str = "",
        print_layer: int | None = None,
    ) -> None:
        out.append(Step(len(out), phase, layer, kind, axis, value, label, height, print_layer))

    # --- SETUP (primed start): home GANTRIES ONLY, then an initial safe profile. No piston home,
    # no home_all, no feed pre-position move (the pistons are already at the primed bed). Each phase
    # overrides these profiles before it moves, so the setup profile is only the start state.
    add("setup", 0, "home", PRINTHEAD)
    add("setup", 0, "wait")
    add("setup", 0, "home", RECOATER)
    add("setup", 0, "wait")
    base = plan.thin_precoat  # a representative base profile for all four axes
    add("setup", 0, "set_speed", PART, base.part_speed)
    add("setup", 0, "set_accel", PART, base.part_accel)
    add("setup", 0, "set_speed", FEED, base.feed_speed)
    add("setup", 0, "set_accel", FEED, base.feed_accel)
    add("setup", 0, "set_speed", RECOATER, base.recoater_speed)
    add("setup", 0, "set_accel", RECOATER, base.recoater_accel)
    add("setup", 0, "set_speed", PRINTHEAD, base.printhead_speed)
    add("setup", 0, "set_accel", PRINTHEAD, base.printhead_accel)
    # No printhead park: after homing it stays home (5). Parking it mid-bed (e.g. 250) would sit it
    # right in the recoater's spread path and block coating. The pistons stay at the primed bed.

    # Running feed position: starts at the primed feed column top (feed_end_mm) and drops by each
    # feed advance. Mirrors the script's ``current_feed_pos`` guard: when the next advance would
    # reach/cross FEED_FLOOR the powder cannot supply another layer, so we home the recoater, mark
    # "feed_exhausted", and stop compiling (a terminal safety stop; the operator re-primes).
    feed_pos = plan.feed_end_mm

    layer_no = 0
    print_layer = 0  # 1-based index of printing-phase layers (for the nozzle-purge schedule)
    exhausted = False
    for name in PHASES:
        if name == "postcoat" and not plan.postcoat_enabled:
            continue
        ph = plan.phase(name)
        if ph.n_layers == 0:
            continue
        # Per-phase speeds/accels for all four axes (as the script sets at each stage boundary).
        add(name, layer_no, "set_speed", PART, ph.part_speed)
        add(name, layer_no, "set_accel", PART, ph.part_accel)
        add(name, layer_no, "set_speed", FEED, ph.feed_speed)
        add(name, layer_no, "set_accel", FEED, ph.feed_accel)
        add(name, layer_no, "set_speed", PRINTHEAD, ph.printhead_speed)
        add(name, layer_no, "set_accel", PRINTHEAD, ph.printhead_accel)
        add(name, layer_no, "set_speed", RECOATER, ph.recoater_speed)
        add(name, layer_no, "set_accel", RECOATER, ph.recoater_accel)
        for _idx in range(ph.n_layers):
            # Feed-exhaustion guard (checked before this layer commits any motion): if the feed
            # advance this layer needs would reach/cross the floor, stop before spreading.
            if ph.feed_thickness_mm > 0 and feed_pos - ph.feed_thickness_mm <= FEED_FLOOR_MM:
                add(name, layer_no + 1, "move_abs", RECOATER, plan.recoater_home_mm)
                add(name, layer_no + 1, "wait")
                add(name, layer_no + 1, "mark", label="feed_exhausted")
                exhausted = True
                break
            layer_no += 1
            if name in _PART_DROP_PHASES:
                height += ph.layer_thickness_mm

            add(name, layer_no, "mark", label="layer_start")
            # 1) PART DROP — thin_precoat & printing only (postcoat holds the part fixed). V1.py
            # drops the build piston FIRST, before the recoater repositions or the feed advances.
            # Opt-in anti-backlash: overshoot the drop DOWN by build_backlash_mm, then return UP to
            # the layer target, so the drop is always approached from one side (takes up slop;
            # the piston sweep proved this removes the drop/double interlayer scatter). Net descent
            # stays layer_thickness. build_backlash_mm = 0 keeps the single V1.py move.
            if name in _PART_DROP_PHASES:
                bl = plan.build_backlash_mm
                add(name, layer_no, "move_rel", PART, ph.layer_thickness_mm + bl)  # build down
                add(name, layer_no, "wait")
                if bl > 0:
                    add(name, layer_no, "move_rel", PART, -bl, "build backlash return")
                    add(name, layer_no, "wait")

            # 2) REPOSITION — recoater past the feed piston out to the far end, so it can spread on
            # the way back. Optional anti-backlash: drop the feed a little BEFORE this move (keeps
            # nozzles clear of powder; the feed-up then approaches from below, taking up slop).
            preload = plan.feed_backlash_mm if ph.feed_thickness_mm > 0 else 0.0
            if preload > 0:
                add(name, layer_no, "move_rel", FEED, preload, "feed backlash preload down")
                add(name, layer_no, "wait")
            add(name, layer_no, "move_abs", RECOATER, plan.recoater_end_mm)
            add(name, layer_no, "wait")

            # 3) FEED ADVANCE — every phase incl. printing (the feed piston is the powder supply).
            # Net advance stays feed_thickness; the up move also undoes the preload drop.
            if ph.feed_thickness_mm > 0:
                add(name, layer_no, "move_rel", FEED, -(ph.feed_thickness_mm + preload), "feed up")
                add(name, layer_no, "wait")
                add(name, layer_no, "dwell", value=plan.settle_s)  # script's time.sleep(1)
                feed_pos -= ph.feed_thickness_mm

            # 4) PRECOAT RETURN vs PRINT.
            if name in _PRECOAT_PHASES:
                add(name, layer_no, "move_abs", RECOATER, plan.recoater_return_mm)  # 350, not home
                add(name, layer_no, "wait")
                add(name, layer_no, "mark", label="layer_end")
                continue

            # ---- printing ----
            print_layer += 1
            cap_stages = plan.capture_stages_enabled if plan.capture_stages else ()

            def add_capture(
                stage: str,
                phase: str = name,
                absolute_layer: int = layer_no,
                printing_layer: int = print_layer,
            ) -> None:
                """Put the recoater-mounted camera at its calibrated pose and hold through the
                asynchronous browser exposure. A zero pose preserves fixed-camera operation."""
                if plan.capture_recoater_mm > 0:
                    add(phase, absolute_layer, "move_abs", RECOATER, plan.capture_recoater_mm)
                    add(phase, absolute_layer, "wait")
                    if plan.capture_settle_s > 0:
                        add(
                            phase,
                            absolute_layer,
                            "dwell",
                            value=plan.capture_settle_s,
                            label="camera settle",
                        )
                add(
                    phase,
                    absolute_layer,
                    "mark",
                    label=f"capture:{stage}",
                    print_layer=printing_layer,
                )
                if plan.capture_hold_s > 0:
                    add(
                        phase,
                        absolute_layer,
                        "dwell",
                        value=plan.capture_hold_s,
                        label="camera capture hold",
                    )

            if "pre_jet" in cap_stages:
                # Stop during the 950 -> home spreading return when the calibrated camera reaches
                # the bed. The image is pre-jet; the remaining spread and jet then resume together.
                add_capture("pre_jet")
            # Nozzle-purge schedule (firing is external; we only DWELL at the start position so the
            # printhead can fire): every pass, once per layer, or every N printing layers.
            purge_on = plan.purge_dwell_s > 0
            purge_every_pass = purge_on and plan.purge_mode == "every_pass"
            purge_first_pass = purge_on and (
                plan.purge_mode == "per_layer"
                or (
                    plan.purge_mode == "every_n_layers"
                    and (print_layer - 1) % max(plan.purge_every_n_layers, 1) == 0
                )
            )
            # Concurrent jet + retract: recoater retracts home WHILE the printhead jets; ONE wait
            # covers both moves. Multipass shuttles the printhead back only to
            # printhead_multipass_return_mm between passes (saves travel), home on the LAST pass.
            add(name, layer_no, "move_abs", RECOATER, plan.recoater_home_mm)
            # Where the purge dwell holds the printhead: purge_position_mm when set, else the
            # printhead start position (original behavior).
            purge_pos = (
                plan.purge_position_mm
                if plan.purge_position_mm is not None
                else plan.printhead_start_mm
            )
            # Heater OFF + no pre-heater drop: the printhead's return home and the recoater's
            # reposition to the spread start (950) are independent axes, so run them CONCURRENTLY
            # (one wait) instead of two serial returns. Heater ON keeps them serial (the printhead
            # must be home before the recoater sweeps 425->600).
            for pass_no in range(plan.n_jet_passes):
                if purge_every_pass or (purge_first_pass and pass_no == 0):
                    add(name, layer_no, "move_abs", PRINTHEAD, purge_pos)
                    add(name, layer_no, "wait")
                    add(name, layer_no, "dwell", value=plan.purge_dwell_s, label="nozzle purge")
                add(name, layer_no, "move_abs", PRINTHEAD, plan.printhead_end_mm)
                add(name, layer_no, "wait")
                last = pass_no == plan.n_jet_passes - 1
                back = plan.printhead_home_mm if last else plan.printhead_multipass_return_mm
                add(name, layer_no, "move_abs", PRINTHEAD, back)
                add(name, layer_no, "wait")
            if "post_jet" in cap_stages:
                add_capture("post_jet")
            if plan.pre_heater_drop_mm > 0:  # drop before heating (net descent stays one layer)
                add(name, layer_no, "move_rel", PART, plan.pre_heater_drop_mm, "pre-heater drop")
                add(name, layer_no, "wait")
            if plan.heater_enabled:
                # Heater sweep 425 -> 600 with a slow-follow recoater profile, then restore.
                add(name, layer_no, "move_abs", RECOATER, plan.heater_start_mm)  # 425
                add(name, layer_no, "wait")
                add(name, layer_no, "heater", value=1.0)
                add(name, layer_no, "set_speed", RECOATER, plan.heater_speed)
                add(name, layer_no, "set_accel", RECOATER, plan.heater_accel)
                add(name, layer_no, "move_abs", RECOATER, plan.heater_end_mm)  # 600
                add(name, layer_no, "wait")
                add(name, layer_no, "heater", value=0.0)
                add(name, layer_no, "set_speed", RECOATER, ph.recoater_speed)  # restore
                add(name, layer_no, "set_accel", RECOATER, ph.recoater_accel)
            if plan.pre_heater_drop_mm > 0:  # raise back -> net descent is exactly one layer
                add(
                    name, layer_no, "move_rel", PART, -plan.pre_heater_drop_mm, "raise to layer"
                )
                add(name, layer_no, "wait")
            # NO end-of-layer recoater reposition. The recoater stays where the spread (home) or the
            # heater sweep (600) left it, and repositions out to the spread start (950) at the NEXT
            # layer's START -- AFTER that layer's anti-backlash feed preload. Parking it at 950 here
            # made the next layer's preload land too late (recoater already at 950); the feed must
            # drop BEFORE the recoater moves out. (Precoat layers return to 350 above.)
            if "post_heat" in cap_stages:
                add_capture("post_heat")
            add(name, layer_no, "mark", label="layer_end")
        if exhausted:
            break

    if exhausted:
        # Terminal stop: the recoater is already parked home and the fault is marked. Do NOT drive
        # the part to max after an unexpected feed-out; leave the finish to operator intervention.
        return tuple(out)

    # --- FINISH: home the gantries, then drive the part cylinder to its max travel.
    add("finish", layer_no, "home", PRINTHEAD)
    add("finish", layer_no, "wait")
    add("finish", layer_no, "home", RECOATER)
    add("finish", layer_no, "wait")
    add("finish", layer_no, "move_abs", PART, plan.part_max_mm)
    add("finish", layer_no, "wait")
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
        if step.kind == "home" and step.axis is not None:
            # primed start homes only gantries; charge ~half that axis's travel at its homing speed
            pending = max(pending, _TRAVEL[step.axis] / _HOMING[step.axis] * 0.5)
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
