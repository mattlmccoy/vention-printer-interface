#!/usr/bin/env python3
"""Build-piston characterization sweep — a one-off diagnostic to find WHERE per-step build-piston
moves come out short/double (the "one layer zero, next layer double" effect), and whether it is
deterministic (position- / direction- / step-size-dependent) so it can be compensated.

RUN THIS ONLY WHILE ATTACHED TO THE REAL MACHINE, with an EMPTY bed (the piston travels ~span mm).
It drives the operator (not the MachineMotion directly), so the operator's arming, limits, and
e-stop all still apply. It refuses unless the machine is connected, armed, the build piston is
referenced, the heater is off, and no print/routine is running. It returns the piston to its start
position when done (and on Ctrl-C).

    uv run python scripts/piston_sweep.py --span 20 --passes 3
    uv run python scripts/piston_sweep.py --step-sizes 0.2 --span 10 --passes 5    # focused

Isolation: only the build piston (axis 1) moves — no feed, recoater, printhead, or heater. Each
target is an ABSOLUTE move; after it settles we record commanded target vs actual position, so the
per-step delta (actual moved vs commanded step) exposes a dropped or doubled step.

Output: sweep_<timestamp>.csv (pass, step_size, direction, index, commanded_mm, actual_mm,
deviation_mm, step_cmd_mm, step_actual_mm, step_err_mm) plus a printed analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PART_AXIS = 1
SAFE_MAX_MM = 140.0  # keep clear of the 145 mm hard travel
SAFE_MIN_MM = 0.0
READOUT_MM = 0.1  # MM2 build-piston encoder readout resolution: positions land on a 0.1 mm grid


# ---- pure analysis (unit-tested) ----------------------------------------------------------------
def settle_update(
    window: list[float], pos: float, *, complete: bool, tol: float = READOUT_MM, need: int = 3
) -> tuple[list[float], float | None]:
    """Fold one telemetry sample into the settle window and decide if the axis is at rest.

    The axis is settled once motion is complete AND the last ``need`` positions span no more than
    ``tol`` (default one encoder count). That lets a position which flickers by a single 0.1 mm
    readout count at rest still latch — the previous exact-equality test (``abs(pos-last) < 1e-4``,
    1000x finer than the 0.1 mm readout) could never latch on a boundary-parked position and so
    spun until the 30 s timeout. Returns the updated window and the settled position (``None`` until
    settled). While motion is incomplete the window resets, so a pre-completion reading can't count.
    """
    if not complete:
        return [], None
    window = (window + [pos])[-need:]
    if len(window) >= need and (max(window) - min(window)) <= tol + 1e-9:
        return window, window[-1]
    return window, None


def settle_ready(saw_incomplete: bool, elapsed_s: float, start_grace_s: float) -> bool:
    """Whether settle() may start ACCEPTING a completed+stable reading. Guards against the V1.py
    race where motion_complete is still True from the PREVIOUS move for a few polls after a new move
    is issued — accepting then would return the stale pre-move position. Ready once we've seen the
    move register (motion_complete went False) OR the start grace elapsed (a no-op move already at
    target never goes incomplete, so don't wait forever)."""
    return saw_incomplete or elapsed_s >= start_grace_s


def wall_reached(actual_steps: list[float], step_mm: float) -> bool:
    """True once the piston stops advancing against its mechanical end: the last two up-steps
    together advance less than half of ONE commanded step (motion is being lost). Requires two
    samples so a single quantization-zero mid-travel can't false-trip it."""
    if len(actual_steps) < 2:
        return False
    return (actual_steps[-1] + actual_steps[-2]) <= step_mm * 0.5 + 1e-9


def median(values: list[float]) -> float:
    """Median of the values (mean of the two middles for an even count); 0.0 for an empty list.
    Used to summarize the per-rep backlash robustly — one sticky rep can't skew it like a mean."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else round((s[mid - 1] + s[mid]) / 2, 4)


def backlash_from_pair(approached_descending: float, approached_ascending: float) -> float:
    """Bidirectional backlash at a target = the gap between the settled position reached moving
    DOWN (descending, position increasing) and moving UP (ascending) to the SAME commanded target.
    Positive = lost motion (lash)."""
    return round(approached_descending - approached_ascending, 4)


# ---- pure analysis (unit-tested) ----------------------------------------------------------------
def analyze_sweep(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a sweep: per step-size accuracy, direction (backlash) asymmetry, and whether the
    per-step error recurs at the same absolute positions across passes (determinism).

    Each row needs: step_size, direction ('down'/'up'), commanded_mm, step_cmd_mm, step_actual_mm,
    step_err_mm (actual step minus commanded step). Rows with step_cmd_mm == 0 (the first target of
    a pass, no preceding step) are ignored.
    """
    steps = [r for r in rows if abs(float(r.get("step_cmd_mm") or 0.0)) > 1e-9]

    def stats(sel: list[dict[str, Any]]) -> dict[str, float]:
        errs = [abs(float(r["step_err_mm"])) for r in sel]
        if not errs:
            return {"n": 0, "mean_abs_err_mm": 0.0, "max_abs_err_mm": 0.0, "frac_bad": 0.0}
        bad = sum(1 for e in errs if e > 0.05)  # a step off by >50 µm is a real miss
        return {
            "n": len(errs),
            "mean_abs_err_mm": round(sum(errs) / len(errs), 4),
            "max_abs_err_mm": round(max(errs), 4),
            "frac_bad": round(bad / len(errs), 3),
        }

    by_step: dict[str, dict[str, Any]] = {}
    for ss in sorted({float(r["step_size"]) for r in steps}):
        sel = [r for r in steps if abs(float(r["step_size"]) - ss) < 1e-9]
        down = [r for r in sel if r["direction"] == "down"]
        up = [r for r in sel if r["direction"] == "up"]
        by_step[f"{ss:g}"] = {"all": stats(sel), "down": stats(down), "up": stats(up)}

    # Determinism: bucket step errors by (step_size, direction, rounded start position) and see if
    # the error repeats across passes at the same location (low spread = deterministic).
    buckets: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for r in steps:
        start_pos = float(r["commanded_mm"]) - float(r["step_cmd_mm"])
        key = (f"{float(r['step_size']):g}", r["direction"], round(start_pos, 1))
        buckets[key].append(float(r["step_err_mm"]))
    recurring = []
    for key, errs in buckets.items():
        if len(errs) < 2:
            continue
        mean = sum(errs) / len(errs)
        spread = max(errs) - min(errs)
        if abs(mean) > 0.05 and spread <= 0.05:  # consistent, non-trivial error at this location
            recurring.append(
                {"step_size": key[0], "direction": key[1], "from_mm": key[2],
                 "mean_err_mm": round(mean, 4), "spread_mm": round(spread, 4), "passes": len(errs)}
            )
    recurring.sort(key=lambda d: -abs(d["mean_err_mm"]))
    return {
        "by_step_size": by_step,
        "deterministic_error_locations": recurring,
        "verdict": (
            "DETERMINISTIC — errors recur at the same positions (compensable)"
            if recurring else
            "no consistent per-location error found (random / within tolerance)"
        ),
    }


# ---- operator API client ------------------------------------------------------------------------
class Operator:
    def __init__(self, base: str, timeout: float = 10.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json", "x-vpi-client": "piston-sweep"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def status(self) -> dict[str, Any]:
        return self._req("GET", "/api/status")

    def move_abs(self, axis: int, mm: float) -> dict[str, Any]:
        return self._req("POST", "/api/motion/move", {"axis": axis, "mode": "abs", "mm": mm})

    def set_print_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self._req("PUT", "/api/print-settings", patch)

    def settle(self, axis: int, poll_s: float = 0.05, stable_needed: int = 3,
               timeout_s: float = 30.0, tol: float = READOUT_MM,
               start_grace_s: float = 0.4) -> float:
        """Wait until the axis reports motion complete and its position is at rest (stable to within
        one encoder count across a few polls); return the settled position. First waits for the move
        to REGISTER (motion_complete going False, or the start grace for a no-op move) so a stale
        'still complete from the last move' reading can't return the pre-move position. On timeout
        the error says whether motion_complete was ever seen (physical stall vs a dithering pos)."""
        window: list[float] = []
        complete_ever = False
        saw_incomplete = False
        seen: list[float] = []
        t0 = time.monotonic()
        end = t0 + timeout_s
        while time.monotonic() < end:
            tel = (self.status().get("controller") or {}).get("telemetry") or {}
            complete = bool((tel.get("motion_complete") or {}).get(str(axis)))
            pos = (tel.get("positions") or {}).get(str(axis))
            complete_ever = complete_ever or complete
            if not complete:
                saw_incomplete = True
            ready = settle_ready(saw_incomplete, time.monotonic() - t0, start_grace_s)
            if ready and pos is not None:
                seen = (seen + [float(pos)])[-8:]
                window, settled = settle_update(
                    window, float(pos), complete=complete, tol=tol, need=stable_needed
                )
                if settled is not None:
                    return settled
            elif pos is not None:
                window = []  # move not registered yet — drop pre-move samples (no false "stable")
            time.sleep(poll_s)
        raise TimeoutError(
            f"axis {axis} did not settle within {timeout_s}s "
            f"(motion_complete seen: {complete_ever}; last positions: {seen})"
        )


def preflight(op: Operator) -> float:
    """Refuse unless it is safe to sweep; return the referenced start position of the piston."""
    st = op.status()
    c = st.get("controller") or {}
    tel = c.get("telemetry") or {}
    problems = []
    if c.get("state") != "connected":
        problems.append(f"controller not connected (state={c.get('state')})")
    if not c.get("armed"):
        problems.append("not armed — press ARM in the UI first")
    if (tel.get("referenced") or {}).get(str(PART_AXIS)) is not True:
        problems.append("build piston is not referenced — home or reference-at-current first")
    if c.get("read_error"):
        problems.append(f"telemetry read error: {c.get('read_error')}")
    if (c.get("heater") or {}).get("on"):
        problems.append("heater is ON — turn it off before sweeping")
    pr = st.get("print") if isinstance(st.get("print"), dict) else None
    if pr and pr.get("state") in ("running", "paused"):
        problems.append("a print/routine is running")
    if problems:
        sys.exit("Refusing to sweep:\n  - " + "\n  - ".join(problems))
    pos = (tel.get("positions") or {}).get(str(PART_AXIS))
    if pos is None:
        sys.exit("No build-piston position reported.")
    return float(pos)


def build_targets(start: float, span: float, step: float, direction: str) -> list[float]:
    n = max(1, round(span / step))
    if direction == "down":  # piston descends: position increases
        return [round(start + i * step, 4) for i in range(1, n + 1)]
    return [round(start + (n - i) * step, 4) for i in range(1, n + 1)]  # back up to start


def run_sweep(op: Operator, start: float, span: float, step_sizes: list[float],
              passes: int, dwell_s: float) -> list[dict[str, Any]]:
    lo, hi = start, start + span
    if hi > SAFE_MAX_MM or lo < SAFE_MIN_MM:
        sys.exit(f"Sweep window [{lo:.1f}, {hi:.1f}] mm is outside the safe range "
                 f"[{SAFE_MIN_MM}, {SAFE_MAX_MM}]. Lower --span or re-reference.")
    rows: list[dict[str, Any]] = []
    for step in step_sizes:
        for p in range(1, passes + 1):
            for direction in ("down", "up"):
                anchor = start if direction == "down" else start + span
                op.move_abs(PART_AXIS, anchor)  # park at the pass's starting end
                prev_actual = op.settle(PART_AXIS)
                prev_cmd = anchor
                for idx, target in enumerate(build_targets(start, span, step, direction)):
                    op.move_abs(PART_AXIS, target)
                    actual = op.settle(PART_AXIS)
                    time.sleep(dwell_s)
                    step_cmd = round(target - prev_cmd, 4)        # what we asked this step to move
                    step_actual = round(actual - prev_actual, 4)  # what it actually moved
                    rows.append({
                        "pass": p, "step_size": step, "direction": direction, "index": idx,
                        "commanded_mm": round(target, 4), "actual_mm": round(actual, 4),
                        "deviation_mm": round(actual - target, 4),
                        "step_cmd_mm": step_cmd,
                        "step_actual_mm": step_actual,
                        "step_err_mm": round(step_actual - step_cmd, 4),
                    })
                    prev_cmd, prev_actual = target, actual
            print(f"  step {step:g} mm  pass {p}/{passes}  done")
    op.move_abs(PART_AXIS, start)  # return to where we found it
    op.settle(PART_AXIS)
    return rows


# ---- targeted confirmation: find the travel wall + measure backlash (--mode confirm) -------------
def probe_wall(op: Operator, start_mm: float, step_mm: float, max_mm: float,
               ) -> tuple[float | None, list[dict[str, Any]]]:
    """Fine-step the piston DOWN toward its mechanical end (position increasing) from ``start_mm``,
    stopping the instant motion is lost (``wall_reached``). Never commands past ``max_mm``. Returns
    ``(wall_mm | None, rows)`` where ``wall_mm`` is the last position that still tracked."""
    op.move_abs(PART_AXIS, start_mm)
    prev = op.settle(PART_AXIS)
    rows: list[dict[str, Any]] = []
    steps: list[float] = []
    wall: float | None = None
    pos = start_mm
    while round(pos + step_mm, 4) <= max_mm + 1e-9:
        target = round(pos + step_mm, 4)
        op.move_abs(PART_AXIS, target)
        actual = op.settle(PART_AXIS)
        adv = round(actual - prev, 4)
        steps.append(adv)
        rows.append({"mode": "wall", "ref_mm": None, "rep": None, "commanded_mm": target,
                     "actual_mm": round(actual, 4), "deviation_mm": round(actual - target, 4),
                     "step_actual_mm": adv, "backlash_mm": None})
        if wall_reached(steps, step_mm):
            wall = round(prev, 4)
            break
        prev, pos = actual, target
    return wall, rows


def probe_backlash(op: Operator, positions: list[float], d_mm: float, reps: int,
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """At each position, reach the target from BOTH directions (down then up) ``reps`` times and
    record the bidirectional gap = backlash. Returns ``(rows, per-position summary)``."""
    rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for p in positions:
        vals: list[float] = []
        for r in range(1, reps + 1):
            op.move_abs(PART_AXIS, round(p - d_mm, 4))
            op.settle(PART_AXIS)
            op.move_abs(PART_AXIS, p)
            a_desc = op.settle(PART_AXIS)   # target reached descending (position increasing)
            op.move_abs(PART_AXIS, round(p + d_mm, 4))
            op.settle(PART_AXIS)
            op.move_abs(PART_AXIS, p)
            a_asc = op.settle(PART_AXIS)    # target reached ascending (position decreasing)
            bl = backlash_from_pair(a_desc, a_asc)
            vals.append(bl)
            rows.append({"mode": "backlash", "ref_mm": p, "rep": r, "commanded_mm": p,
                         "actual_mm": round(a_asc, 4), "deviation_mm": None,
                         "step_actual_mm": None, "backlash_mm": bl})
        mags = [abs(v) for v in vals]
        summary.append({
            "ref_mm": p,
            "backlash_median_mm": median(vals),
            "backlash_mag_median_mm": median(mags),  # recommended comp magnitude at this position
            "backlash_min_mm": min(vals),
            "backlash_max_mm": max(vals),
            "reps": vals,
        })
    return rows, summary


def run_confirm(op: Operator, start: float, args: argparse.Namespace,
                ) -> tuple[float | None, float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Short targeted characterization: locate the travel wall, then measure backlash below it.
    Returns ``(wall_mm, recommended_comp_mm, per-position summary, rows)`` where the recommended
    comp is the median backlash magnitude across positions (snapped to the 0.1 mm readout)."""
    wall_from = args.wall_from
    print(f"Wall probe: fine {args.wall_step:g} mm steps from {wall_from:.1f} up to "
          f"<= {args.wall_max:.1f} mm; stops the instant motion is lost.")
    wall, wall_rows = probe_wall(op, wall_from, args.wall_step, args.wall_max)
    if wall is None:
        print(f"  no wall up to {args.wall_max:.1f} mm — piston tracked the whole way.")
    else:
        print(f"  WALL ~{wall:.1f} mm (commands above this are not reached).")
    ceiling = wall if wall is not None else args.wall_max
    op.move_abs(PART_AXIS, round(ceiling - 5.0, 4))  # back off the end
    op.settle(PART_AXIS)
    positions = [p for p in args.backlash_at if p < ceiling - 2.0]
    print(f"Backlash probe: {args.backlash_reps}x +/-{args.backlash_d:g} mm reversal at "
          f"{positions} mm.")
    bl_rows, bl_summary = probe_backlash(op, positions, args.backlash_d, args.backlash_reps)
    op.move_abs(PART_AXIS, start)  # return to where we started
    op.settle(PART_AXIS)
    # Recommended anti-backlash comp = median across positions of each position's median |backlash|,
    # snapped to the 0.1 mm readout (never below one count when any lash was seen).
    per_pos = [float(s["backlash_mag_median_mm"]) for s in bl_summary]
    recommended = round(median(per_pos) / READOUT_MM) * READOUT_MM if per_pos else 0.0
    if per_pos and recommended < READOUT_MM and max(per_pos) > 0:
        recommended = READOUT_MM
    recommended = round(recommended, 4)
    print(f"  recommended build_backlash_mm ~ {recommended:g} mm "
          f"(median |lash| across {len(per_pos)} positions).")
    return wall, recommended, bl_summary, wall_rows + bl_rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="piston-sweep", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8020", help="operator base URL")
    ap.add_argument("--mode", choices=("sweep", "confirm"), default="sweep",
                    help="'sweep' = span accuracy sweep; 'confirm' = travel wall + backlash")
    ap.add_argument("--span", type=float, default=20.0, help="distance (mm) the piston travels")
    ap.add_argument("--step-sizes", type=float, nargs="+", default=[0.1, 0.2, 0.5, 1.0])
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--dwell", type=float, default=0.1, help="extra dwell after settle (s)")
    # --mode confirm: HOME the piston in the UI first so positions are from home. Fine-steps up from
    # --wall-from and STOPS the instant motion is lost (never rams the end); caps at --wall-max.
    # DEFAULTS ASSUME THE BUILD PISTON IS ATTACHED (usable range ~72 mm — the normal case). For the
    # BARE actuator (~130 mm stroke) pass --wall-from 120 --wall-max 138 --backlash-at 30 70 110.
    ap.add_argument("--wall-from", type=float, default=55.0, help="confirm: wall-probe start (mm)")
    ap.add_argument("--wall-step", type=float, default=0.2, help="confirm: wall-probe step (mm)")
    ap.add_argument("--wall-max", type=float, default=74.0, help="confirm: hard cap (mm)")
    ap.add_argument("--backlash-at", type=float, nargs="+", default=[15.0, 30.0, 45.0, 55.0],
                    help="confirm: positions to measure backlash (mm, kept below the wall)")
    # A 2 mm reversal fully develops the ~0.5 mm attached-piston lash (0.5 mm barely cleared it);
    # 8 reps + a median summary reject the occasional sticky rep.
    ap.add_argument("--backlash-d", type=float, default=2.0, help="confirm: reversal distance (mm)")
    ap.add_argument("--backlash-reps", type=int, default=8, help="confirm: reversals per position")
    ap.add_argument("--apply", action="store_true",
                    help="confirm: write the recommended build_backlash_mm into the print settings")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.wall_max > SAFE_MAX_MM:
        sys.exit(f"--wall-max {args.wall_max} exceeds the safe ceiling {SAFE_MAX_MM} mm.")

    op = Operator(args.url)
    start = preflight(op)

    if args.mode == "confirm":
        print(f"Build-piston CONFIRM: start={start:.3f} mm. Wall probe "
              f"{args.wall_from:.0f}->{args.wall_max:.0f} mm @ {args.wall_step:g} mm (stops on "
              f"lost motion, never rams the end); backlash {args.backlash_reps}x "
              f"+/-{args.backlash_d:g} mm at {args.backlash_at} mm.")
        print("EMPTY BED ONLY. HOME the piston in the UI first so positions are from home. "
              f"Returns to {start:.3f} mm when done.")
        if not args.yes and input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
        try:
            wall, recommended, bl_summary, rows = run_confirm(op, start, args)
        except KeyboardInterrupt:
            print("\ninterrupted — returning piston to start")
            try:
                op.move_abs(PART_AXIS, start)
            except urllib.error.URLError:
                pass
            return 130
        if args.apply:
            try:
                op.set_print_settings({"build_backlash_mm": recommended})
                print(f"applied build_backlash_mm={recommended:g} mm to the print settings.")
            except urllib.error.URLError as exc:
                print(f"could not apply build_backlash_mm ({exc}); set it manually.")
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out = args.out or Path(f"piston_confirm_{ts}.csv")
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nwrote {len(rows)} rows -> {out}")
        print(json.dumps({"wall_mm": wall,
                          "usable_ceiling_mm": None if wall is None else round(wall, 1),
                          "recommended_build_backlash_mm": recommended,
                          "backlash": bl_summary}, indent=2))
        return 0

    n_targets = sum(max(1, round(args.span / s)) for s in args.step_sizes) * args.passes * 2
    print(f"Build-piston sweep: start={start:.3f} mm, span={args.span} mm, "
          f"step sizes {args.step_sizes} mm, {args.passes} passes, both directions.")
    print(f"~{n_targets} moves; the piston travels between {start:.1f} and "
          f"{start + args.span:.1f} mm. EMPTY BED ONLY. It returns to {start:.3f} mm when done.")
    if not args.yes and input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
        return 1

    try:
        rows = run_sweep(op, start, args.span, args.step_sizes, args.passes, args.dwell)
    except KeyboardInterrupt:
        print("\ninterrupted — returning piston to start")
        try:
            op.move_abs(PART_AXIS, start)
        except urllib.error.URLError:
            pass
        return 130

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = args.out or Path(f"sweep_{ts}.csv")
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {out}")
    print(json.dumps(analyze_sweep(rows), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
