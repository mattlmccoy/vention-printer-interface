"""Piston backlash-calibration core (hardware-independent).

Ports the validated measurement from ``scripts/piston_sweep.py`` (``probe_backlash`` +
``run_confirm``) into a reusable, unit-tested routine driven through a small ``Mover`` protocol,
so the operator can run it in-process and tests can run it against a fake piston.

At each reference position ``p`` the target is reached from BOTH directions ``reps`` times:
``p-d -> p`` (descending, position increasing) gives ``a_desc``; ``p+d -> p`` (ascending, position
decreasing) gives ``a_asc``. The bidirectional gap ``a_desc - a_asc`` is the lost motion (lash).
The recommended anti-backlash compensation is the median across positions of each position's
median |lash|, snapped to the 0.1 mm encoder readout (and never rounded below one count when any
lash was seen).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

READOUT_MM = 0.1  # MM2 build/feed piston position readout quantum


class Mover(Protocol):
    """The minimal motion surface the routine needs. The operator backs this with the real
    controller; tests back it with a fake piston."""

    def move_abs(self, axis: int, mm: float) -> None: ...

    def settle(self, axis: int) -> float: ...


@dataclass(frozen=True)
class PositionResult:
    ref_mm: float
    backlash_median_mm: float
    backlash_mag_median_mm: float
    reps_mm: tuple[float, ...]


@dataclass(frozen=True)
class BacklashResult:
    axis: int
    positions: tuple[PositionResult, ...]
    recommended_mm: float
    cancelled: bool


def median(values: list[float]) -> float:
    """Median (mean of the two middles for an even count); 0.0 for an empty list. Robust to a
    single sticky rep in a way a mean is not."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else round((s[mid - 1] + s[mid]) / 2, 4)


def backlash_from_pair(approached_descending: float, approached_ascending: float) -> float:
    """Bidirectional backlash at a target = settled-descending minus settled-ascending. Positive
    means lost motion (lash)."""
    return round(approached_descending - approached_ascending, 4)


def recommend_comp(per_position_mag_medians: list[float]) -> float:
    """Recommended anti-backlash comp = median of the per-position |lash| medians, snapped to the
    0.1 mm readout. Floored to one count when any position saw lash, so a tiny-but-real lash never
    rounds to 0 (which would silently disable compensation)."""
    if not per_position_mag_medians:
        return 0.0
    rec = round(median(per_position_mag_medians) / READOUT_MM) * READOUT_MM
    if rec < READOUT_MM and max(per_position_mag_medians) > 0:
        rec = READOUT_MM
    return round(rec, 4)


def default_positions(
    max_mm: float,
    fractions: tuple[float, ...] = (0.2, 0.4, 0.6, 0.75),
    edge_mm: float = 3.0,
) -> list[float]:
    """Safe reference positions for a piston whose usable travel is ``[0, max_mm]``: the given
    fractions of travel, each clamped to ``[edge_mm, max_mm - edge_mm]`` so probing never rides an
    end, de-duplicated and sorted. For max 72 mm this is ~[14.4, 28.8, 43.2, 54.0] — the validated
    confirm-sweep recipe (15/30/45/55)."""
    lo, hi = edge_mm, max(edge_mm, max_mm - edge_mm)
    pts = {round(min(hi, max(lo, f * max_mm)), 4) for f in fractions}
    return sorted(pts)


def perturbed_positions(positions: list[float]) -> list[float]:
    """Midpoints between consecutive reference depths — for a VERIFY re-measure at DIFFERENT
    positions than the original cal. Re-measuring at the same depths can confirm a position-specific
    rut instead of ruling it out; probing the gaps tests whether the lash is a real mechanical
    property that holds across the travel. Midpoints are strictly interior, so they stay valid
    (each lies between two already-valid references). Needs >= 2 points; otherwise empty."""
    ordered = sorted(positions)
    return [round((a + b) / 2.0, 4) for a, b in zip(ordered, ordered[1:], strict=False)]


def validate_probe(max_mm: float, positions: list[float], d_mm: float) -> None:
    """Raise ``ValueError`` unless every probe stays inside the usable travel. Each reference is
    reached from both sides (``p - d`` and ``p + d``), so both must lie in ``[0, max_mm]``. Guards a
    routine from driving the attached piston into an end stop."""
    if d_mm <= 0:
        raise ValueError("dither d_mm must be positive")
    if not positions:
        raise ValueError("no probe positions")
    for p in positions:
        if p - d_mm < 0.0:
            raise ValueError(f"probe {p:g} - {d_mm:g} mm dither goes below 0")
        if p + d_mm > max_mm:
            raise ValueError(f"probe {p:g} + {d_mm:g} mm dither exceeds the {max_mm:g} mm max")


def preflight_problems(snapshot: dict[str, Any], axis: int, print_running: bool) -> list[str]:
    """Return the reasons it is NOT safe to run a backlash calibration on ``axis`` (empty = safe).
    Mirrors the offline sweep's ``preflight`` against a controller ``snapshot`` dict: the controller
    must be connected, armed, reporting no read error, with the heater off, the axis referenced, and
    no print/routine already running."""
    problems: list[str] = []
    if snapshot.get("state") != "connected":
        problems.append(f"controller not connected (state={snapshot.get('state')})")
    if not snapshot.get("armed"):
        problems.append("not armed — press ARM first")
    if snapshot.get("read_error"):
        problems.append(f"telemetry read error: {snapshot.get('read_error')}")
    if (snapshot.get("heater") or {}).get("on"):
        problems.append("heater is ON — turn it off first")
    tel = snapshot.get("telemetry") or {}
    if (tel.get("referenced") or {}).get(str(axis)) is not True:
        problems.append(f"axis {axis} is not referenced — home or reference it first")
    if print_running:
        problems.append("a print/routine is running")
    return problems


def measure_backlash(
    mover: Mover,
    axis: int,
    positions: list[float],
    d_mm: float,
    reps: int,
    on_progress: Callable[[int, int, PositionResult], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> BacklashResult:
    """Measure bidirectional lash at each reference position and return the per-position summary
    plus the recommended compensation. ``on_progress(done, total, position)`` is called once per
    position with the just-completed ``PositionResult`` (``done`` counting completed positions), so
    a caller can stream results live; ``is_cancelled`` is polled before each position so a routine
    stops promptly and reports what it measured so far."""
    total = len(positions)
    results: list[PositionResult] = []
    cancelled = False
    for ref in positions:
        if is_cancelled is not None and is_cancelled():
            cancelled = True
            break
        vals: list[float] = []
        for _ in range(reps):
            mover.move_abs(axis, round(ref - d_mm, 4))
            mover.settle(axis)
            mover.move_abs(axis, ref)
            a_desc = mover.settle(axis)  # reached descending (position increasing)
            mover.move_abs(axis, round(ref + d_mm, 4))
            mover.settle(axis)
            mover.move_abs(axis, ref)
            a_asc = mover.settle(axis)  # reached ascending (position decreasing)
            vals.append(backlash_from_pair(a_desc, a_asc))
        mags = [abs(v) for v in vals]
        results.append(
            PositionResult(
                ref_mm=ref,
                backlash_median_mm=median(vals),
                backlash_mag_median_mm=median(mags),
                reps_mm=tuple(vals),
            )
        )
        if on_progress is not None:
            on_progress(len(results), total, results[-1])
    recommended = recommend_comp([p.backlash_mag_median_mm for p in results])
    return BacklashResult(
        axis=axis, positions=tuple(results), recommended_mm=recommended, cancelled=cancelled
    )
