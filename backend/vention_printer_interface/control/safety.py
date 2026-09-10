"""Protection layer as a pure function (spec §3). No threads, no IO, no hardware.

HARD_BOUNDS are tighten-only: the operator can narrow limits but never widen them. Travel comes
from our measured axis extents (V1.py), speed/accel caps from what V1.py/test.py actually ran
(gantries 100-200 mm/s @ 500 mm/s^2, pistons 2.5 mm/s @ 15 mm/s^2) with headroom. Defaults are
conservative starting values, NOT validated safe limits; revise in plan/notes.md after
commissioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vention_printer_interface.device.printer import Telemetry

# Measured axis end stops (mm): printhead 970, recoater 972 (2026-09-09).
TRAVEL_MM: dict[int, float] = {1: 145.0, 2: 145.0, 3: 970.0, 4: 972.0}
TRAVEL_FLOOR = -50.0  # axes home to negative positions (recoater ~-22 mm, 2026-09-09)

Bound = tuple[float, float]
MAX_SPEED_BOUNDS: dict[int, Bound] = {
    1: (0.1, 20.0),
    2: (0.1, 20.0),
    3: (0.1, 300.0),
    4: (0.1, 300.0),
}
MAX_ACCEL_BOUNDS: dict[int, Bound] = {
    1: (1.0, 100.0),
    2: (1.0, 100.0),
    3: (1.0, 2000.0),
    4: (1.0, 2000.0),
}
HEATER_MAX_ON_BOUNDS: Bound = (5.0, 600.0)
TELEMETRY_TIMEOUT_BOUNDS: Bound = (0.5, 5.0)
STALE_FAULT_BOUNDS: Bound = (2.0, 30.0)  # blind-period fault; must clear the per-request HTTP cap
NEAR_LIMIT_BOUNDS: Bound = (0.0, 20.0)
TRAVEL_TOLERANCE_BOUNDS: Bound = (0.0, 5.0)  # encoder drift at the ends (real: ~0.1 mm)

HARD_BOUNDS: dict[str, Any] = {
    "max_speed": MAX_SPEED_BOUNDS,  # mm/s
    "max_accel": MAX_ACCEL_BOUNDS,  # mm/s^2
    "travel": {n: (TRAVEL_FLOOR, t) for n, t in TRAVEL_MM.items()},  # mm
    "heater_max_on_s": HEATER_MAX_ON_BOUNDS,
    "telemetry_timeout_s": TELEMETRY_TIMEOUT_BOUNDS,
    "stale_fault_s": STALE_FAULT_BOUNDS,
    "near_limit_mm": NEAR_LIMIT_BOUNDS,
    "travel_tolerance_mm": TRAVEL_TOLERANCE_BOUNDS,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


def _per_axis(
    base: dict[int, float], override: Any, bounds: dict[int, Bound] | None
) -> dict[int, float]:
    out = dict(base)
    if isinstance(override, dict):
        for key, value in override.items():
            n = int(key)
            if n not in out:
                continue
            lo, hi = bounds[n] if bounds else (TRAVEL_FLOOR, TRAVEL_MM[n])
            out[n] = _clamp(float(value), lo, hi)
    return out


@dataclass(frozen=True)
class SafetyLimits:
    max_speed: dict[int, float] = field(
        default_factory=lambda: {1: 5.0, 2: 5.0, 3: 200.0, 4: 200.0}
    )
    max_accel: dict[int, float] = field(
        default_factory=lambda: {1: 30.0, 2: 30.0, 3: 1000.0, 4: 1000.0}
    )
    travel_min: dict[int, float] = field(default_factory=lambda: dict.fromkeys(TRAVEL_MM, -30.0))
    travel_max: dict[int, float] = field(default_factory=lambda: dict(TRAVEL_MM))
    heater_max_on_s: float = 120.0
    telemetry_timeout_s: float = 2.0  # freshness for commands; a slow read past this only WARNS
    stale_fault_s: float = 6.0  # blind period before a FAULT (tolerates HTTP stalls during motion)
    near_limit_mm: float = 5.0  # warning band
    travel_tolerance_mm: float = 2.0  # a hard fault only past the ends by more than this

    @classmethod
    def bounded(cls, **kw: Any) -> SafetyLimits:
        """Build limits clamped into HARD_BOUNDS (tighten-only). Accepts to_dict() output."""
        base = cls()
        tmin = _per_axis(base.travel_min, kw.get("travel_min"), None)
        tmax = _per_axis(base.travel_max, kw.get("travel_max"), None)
        for n in TRAVEL_MM:
            if tmin[n] > tmax[n]:
                tmin[n], tmax[n] = tmax[n], tmin[n]

        def scalar(name: str, bounds: Bound) -> float:
            value = kw.get(name)
            if not isinstance(value, int | float):
                return float(getattr(base, name))
            return _clamp(float(value), *bounds)

        timeout = scalar("telemetry_timeout_s", TELEMETRY_TIMEOUT_BOUNDS)
        # the blind-fault threshold must never sit below the freshness/warn threshold
        stale_fault = max(scalar("stale_fault_s", STALE_FAULT_BOUNDS), timeout)
        return cls(
            max_speed=_per_axis(base.max_speed, kw.get("max_speed"), MAX_SPEED_BOUNDS),
            max_accel=_per_axis(base.max_accel, kw.get("max_accel"), MAX_ACCEL_BOUNDS),
            travel_min=tmin,
            travel_max=tmax,
            heater_max_on_s=scalar("heater_max_on_s", HEATER_MAX_ON_BOUNDS),
            telemetry_timeout_s=timeout,
            stale_fault_s=stale_fault,
            near_limit_mm=scalar("near_limit_mm", NEAR_LIMIT_BOUNDS),
            travel_tolerance_mm=scalar("travel_tolerance_mm", TRAVEL_TOLERANCE_BOUNDS),
        )

    def _axis(self, table: dict[int, float], axis: int) -> float:
        if axis not in table:
            raise ValueError(f"unknown axis {axis}")
        return table[axis]

    def clamp_speed(self, axis: int, mm_s: float) -> float:
        return _clamp(mm_s, 0.1, self._axis(self.max_speed, axis))

    def clamp_accel(self, axis: int, mm_s2: float) -> float:
        return _clamp(mm_s2, 1.0, self._axis(self.max_accel, axis))

    def clamp_position(self, axis: int, mm: float) -> float:
        return _clamp(mm, self._axis(self.travel_min, axis), self._axis(self.travel_max, axis))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_speed": {str(k): v for k, v in self.max_speed.items()},
            "max_accel": {str(k): v for k, v in self.max_accel.items()},
            "travel_min": {str(k): v for k, v in self.travel_min.items()},
            "travel_max": {str(k): v for k, v in self.travel_max.items()},
            "heater_max_on_s": self.heater_max_on_s,
            "telemetry_timeout_s": self.telemetry_timeout_s,
            "stale_fault_s": self.stale_fault_s,
            "near_limit_mm": self.near_limit_mm,
            "travel_tolerance_mm": self.travel_tolerance_mm,
        }


@dataclass(frozen=True)
class SafetyDecision:
    trip: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def evaluate(
    telemetry: Telemetry,
    limits: SafetyLimits,
    telemetry_age_s: float,
    heater_on_s: float,
    move_pending: bool,
    home_in_progress: bool = False,
) -> SafetyDecision:
    reasons: list[str] = []
    warnings: list[str] = []
    # A read that SUCCEEDS but is slow (the controller stalls HTTP while servicing a jog/home)
    # still delivers current data, so a slow read only WARNS; a genuinely blind period (no fresh
    # sample for stale_fault_s) FAULTS. Read failures/timeouts fault via the poll loop separately.
    # This is what keeps jogging and homing from faulting on every motion (2026-09-09).
    if telemetry_age_s > limits.stale_fault_s:
        reasons.append(f"telemetry stale ({telemetry_age_s:.1f}s > {limits.stale_fault_s:.0f}s)")
    elif telemetry_age_s > limits.telemetry_timeout_s:
        warnings.append(f"telemetry slow ({telemetry_age_s:.1f}s)")
    if telemetry.estop_triggered is None:
        reasons.append("controller e-stop status unknown (no estop/status message yet)")
    elif telemetry.estop_triggered:
        reasons.append("controller e-stop asserted")
    if not telemetry.health_ok:
        reasons.append("controller health not ok (motion controller unreachable)")
    if move_pending and not telemetry.drives_ready:
        state = "unknown" if telemetry.drives_ready is None else "not ready"
        reasons.append(f"drives {state} while a move is pending")
    # Position out of the soft window is a WARNING, not a latched fault: commanded moves are
    # already clamped to the window (clamp_position) and the drive's own limit switches are the
    # hard guard, so an axis parked out of range (drift, an interrupted home) must NOT block the
    # operator from arming and HOMING to re-zero. Homing suspends even the warning (position is
    # being re-established).
    if not home_in_progress:
        for axis, pos in telemetry.positions.items():
            lo = limits.travel_min.get(axis, 0.0)
            hi = limits.travel_max.get(axis, TRAVEL_MM.get(axis, 0.0))
            tol = limits.travel_tolerance_mm
            if pos < lo - tol or pos > hi + tol:
                warnings.append(
                    f"axis {axis} at {pos:.1f} mm outside [{lo:.1f}, {hi:.1f}] — home it"
                )
            elif (lo > 0.0 and pos - lo < limits.near_limit_mm) or hi - pos < limits.near_limit_mm:
                warnings.append(f"axis {axis} near travel limit ({pos:.1f} mm)")
    # heater_on_s is measured from the earlier of "commanded on" and "observed on", so the
    # watchdog works even when the relay state is never echoed back (review C1).
    if heater_on_s > limits.heater_max_on_s:
        reasons.append(f"heater on {heater_on_s:.0f}s > watchdog {limits.heater_max_on_s:.0f}s")
    if telemetry.heater_on is None and heater_on_s > 0:
        warnings.append("heater commanded on but relay state not observed")
    return SafetyDecision(trip=bool(reasons), reasons=tuple(reasons), warnings=tuple(warnings))
