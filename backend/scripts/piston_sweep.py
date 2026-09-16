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

    def settle(self, axis: int, poll_s: float = 0.05, stable_needed: int = 3,
               timeout_s: float = 30.0) -> float:
        """Wait until the axis reports motion complete and its position is stable across a few
        polls; return the settled position."""
        last: float | None = None
        stable = 0
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            tel = (self.status().get("controller") or {}).get("telemetry") or {}
            complete = (tel.get("motion_complete") or {}).get(str(axis))
            pos = (tel.get("positions") or {}).get(str(axis))
            if complete and pos is not None:
                if last is not None and abs(pos - last) < 1e-4:
                    stable += 1
                    if stable >= stable_needed:
                        return float(pos)
                else:
                    stable = 0
                last = float(pos)
            time.sleep(poll_s)
        raise TimeoutError(f"axis {axis} did not settle within {timeout_s}s")


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="piston-sweep", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8020", help="operator base URL")
    ap.add_argument("--span", type=float, default=20.0, help="distance (mm) the piston travels")
    ap.add_argument("--step-sizes", type=float, nargs="+", default=[0.1, 0.2, 0.5, 1.0])
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--dwell", type=float, default=0.1, help="extra dwell after settle (s)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    op = Operator(args.url)
    start = preflight(op)
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
