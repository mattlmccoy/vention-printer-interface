# Priming Setup Routine — Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the current thick-precoat-loop "priming" with the real priming *setup* routine — build piston UP, feed piston DOWN to open a powder cavity, HOLD for the operator to load powder, then a calibrated leveling spread — matching spec §6. The thick-precoat loop moves to the Print routine in Plan 3 (deleted from priming here).

**Architecture:** Parameterized settings dataclass → `compile_priming_setup` → `Step` tuple → `PrintController.start_macro` → guarded `Controller`, same as everything else. A new `"hold"` step kind lets a routine pause for a manual step (the powder load) and resume. Pure logic (compiler, preview) is TDD'd; the panel is browser-gated.

**Tech Stack:** Python 3.13 + uv + pytest + ruff + mypy (backend); Vite + React + TS, `node --experimental-strip-types --test` (frontend).

Spec: `docs/superpowers/specs/2026-09-09-binderjet-console-redesign-design.md` §6. Branch: `redesign/binderjet-console`.

Piston sign conventions (critical): part/feed `move_abs` to a SMALL value = UP/flush; LARGE = DOWN. So "build UP" = `move_abs PART → ~0`; "feed DOWN to open cavity" = `move_abs FEED → feed_cavity_mm` (a larger number).

---

## Task 1: Add a `"hold"` step kind to the step engine

A `hold` step pauses the routine (state PAUSED) with a message; the operator resumes to continue. Reuses the existing pause/resume.

**Files:** Modify `backend/vention_printer_interface/control/print_controller.py`; Test: `backend/tests/test_print_controller.py`.

- [ ] **Step 1: Failing test** — add to `backend/tests/test_print_controller.py` (match the file's existing helpers `make()`, `wait()`, `tel()`; a `Step` is `Step(index, phase, layer, kind, axis, value, label, part_height_mm)` from `control.print_settings`):

```python
def test_hold_step_pauses_until_resume() -> None:
    from vention_printer_interface.control.print_settings import Step
    c, t = make()
    try:
        tel(c)
        c.arm()
        steps = (
            Step(0, "setup", 0, "mark", None, None, "start", 0.0),
            Step(1, "setup", 0, "hold", None, None, "Load powder, then Resume", 0.0),
            Step(2, "setup", 0, "mark", None, None, "end", 0.0),
        )
        c.printer.start_macro("test-hold", steps)  # if `printer` is not the attr name, use the controller's PrintController handle
        assert wait(lambda: c.printer.snapshot()["state"] == "paused")
        assert c.printer.snapshot()["current_step"]["kind"] == "hold"
        c.printer.resume()
        assert wait(lambda: c.printer.snapshot()["state"] == "done")
    finally:
        c.stop()
```
NOTE to implementer: this file drives the `PrintController` directly (not via the Controller). READ `test_print_controller.py` first and use however it already obtains the `PrintController` instance (likely constructs `PrintController(controller)` in `make()`); adapt the handle names (`c.printer` above is a placeholder). Keep the test's intent: a hold step → PAUSED with that step current → resume → DONE.

- [ ] **Step 2: Run, watch fail** — `cd backend && uv run pytest tests/test_print_controller.py::test_hold_step_pauses_until_resume -v` → FAIL (hold not handled; never pauses).

- [ ] **Step 3: Implement** in `print_controller.py`. In `_advance`, inside the `while self.step_index < len(self.steps):` loop, after `event = self._issue(step, now)` and the existing `if step.kind in ("wait", "dwell"):` block, add a hold branch BEFORE the `if event: return event`:
```python
            if step.kind == "hold":
                self.state = PrintState.PAUSED
                return ("hold", {"step_index": self.step_index, "message": step.label})
```
And in `_issue`, add a no-op arm for `hold` so it is a recognized kind (it does no IO): after the `elif step.kind == "mark":` block add:
```python
            elif step.kind == "hold":
                return None
```
Resume already sets state RUNNING and the loop continues from `self.step_index` (already advanced past the hold), so no further change is needed.

- [ ] **Step 4: Run, watch pass** — same pytest command → PASS. Then `uv run pytest tests/test_print_controller.py tests/test_controller.py -q` → PASS; `uv run ruff check vention_printer_interface && uv run mypy vention_printer_interface/control/print_controller.py` → clean.

- [ ] **Step 5: Commit** — `git add backend/vention_printer_interface/control/print_controller.py backend/tests/test_print_controller.py` then commit `feat(engine): add a hold step kind (pause for a manual step, resume to continue)` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Task 2: Rebuild the priming compiler (setup model)

Replace `PrimingSettings` + `compile_priming` in `priming.py` with the setup model. DELETE the thick-precoat-loop version entirely.

**Files:** Rewrite `backend/vention_printer_interface/control/priming.py`; Rewrite `backend/tests/test_priming.py`.

- [ ] **Step 1: Rewrite the test** `backend/tests/test_priming.py` to specify the setup model:

```python
"""Priming = job SETUP (spec §6): build piston UP, feed piston DOWN to open a powder cavity,
HOLD for the operator to load powder, then a calibrated leveling spread. NOT a layer loop."""
from __future__ import annotations

from vention_printer_interface.control.priming import PrimingSettings, compile_priming_setup
from vention_printer_interface.control.print_settings import FEED, PART, RECOATER
from vention_printer_interface.control.safety import SafetyLimits

LIM = SafetyLimits()


def kinds(steps):  # type: ignore[no-untyped-def]
    return [(s.kind, s.axis, s.value) for s in steps]


def test_positions_pistons_then_holds_then_levels() -> None:
    s = PrimingSettings()
    steps = compile_priming_setup(s, LIM)
    ks = kinds(steps)
    # speeds/accels set for all three moving axes
    assert ("set_speed", PART, s.part_speed) in ks
    assert ("set_speed", FEED, s.feed_speed) in ks
    assert ("set_speed", RECOATER, s.recoater_speed) in ks
    # build/part piston goes UP to the top; feed piston goes DOWN to open the cavity
    i_part = ks.index(("move_abs", PART, s.part_top_mm))
    i_feed = ks.index(("move_abs", FEED, s.feed_cavity_mm))
    i_hold = next(n for n, st in enumerate(steps) if st.kind == "hold")
    assert i_part < i_hold and i_feed < i_hold  # both positioned before the powder-load hold
    # exactly one hold, with an operator prompt mentioning powder
    holds = [st for st in steps if st.kind == "hold"]
    assert len(holds) == 1 and "powder" in holds[0].label.lower()
    # leveling spread happens AFTER the hold
    i_level = next(n for n, st in enumerate(steps)
                   if st.kind == "move_abs" and st.axis == RECOATER and n > i_hold)
    assert i_level > i_hold


def test_no_piston_is_ever_homed() -> None:
    steps = compile_priming_setup(PrimingSettings(), LIM)
    assert all(not (s.kind == "home" and s.axis in (PART, FEED)) for s in steps)


def test_level_passes_are_configurable() -> None:
    s = PrimingSettings(n_level_passes=2)
    steps = compile_priming_setup(s, LIM)
    ends = [st for st in steps if st.kind == "move_abs" and st.axis == RECOATER
            and st.value == s.level_recoat_end_mm]
    assert len(ends) == 2


def test_recoater_targets_within_travel() -> None:
    s = PrimingSettings()
    for st in compile_priming_setup(s, LIM):
        if st.kind == "move_abs" and st.axis == RECOATER and st.value is not None:
            assert LIM.travel_min[RECOATER] <= st.value <= LIM.travel_max[RECOATER]


def test_validate_flags_out_of_travel_and_bad_passes() -> None:
    assert any("recoat" in r for r in PrimingSettings(level_recoat_end_mm=5000.0).validate(LIM))
    assert any("passes" in r for r in PrimingSettings(n_level_passes=0).validate(LIM))
    assert PrimingSettings().validate(LIM) == []
```

- [ ] **Step 2: Run, watch fail** — `cd backend && uv run pytest tests/test_priming.py -q` → FAIL (no `compile_priming_setup`).

- [ ] **Step 3: Rewrite `backend/vention_printer_interface/control/priming.py`** entirely:

```python
"""Priming = job SETUP (spec §6): build/part piston UP (flush), feed piston DOWN to open a powder
cavity, HOLD for the operator to load powder, then a calibrated leveling spread across the runway.
NOT a layer loop (the thick/thin precoats live in the Print routine). Never homes a piston.

Sign conventions: part/feed move_abs to a SMALL value = UP/flush, LARGE = DOWN.
Defaults are calibration-pending starting points, not validated values.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from vention_printer_interface.control.print_settings import FEED, PART, RECOATER, Step
from vention_printer_interface.control.safety import SafetyLimits

MAX_LEVEL_PASSES = 20


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(float(v), lo), hi)


@dataclass(frozen=True)
class PrimingSettings:
    part_top_mm: float = 0.0        # build/part piston UP/flush
    feed_cavity_mm: float = 30.0    # feed piston DOWN to open a powder cavity (CALIBRATE)
    level_recoat_end_mm: float = 925.0   # spread stroke end (CALIBRATE)
    level_recoat_return_mm: float = 350.0  # park between passes (CALIBRATE)
    n_level_passes: int = 1         # leveling spreads after the powder load (CALIBRATE)
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
        for label, value in (
            ("part_top_mm", (PART, self.part_top_mm)),
            ("feed_cavity_mm", (FEED, self.feed_cavity_mm)),
            ("level_recoat_end_mm", (RECOATER, self.level_recoat_end_mm)),
            ("level_recoat_return_mm", (RECOATER, self.level_recoat_return_mm)),
        ):
            axis, v = value
            lo, hi = lim.travel_min[axis], lim.travel_max[axis]
            if not lo <= v <= hi:
                reasons.append(f"{label}={v} outside axis {axis} travel [{lo}, {hi}]")
        if self.n_level_passes <= 0:
            reasons.append("n_level_passes must be > 0")
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
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else float(getattr(base, name))

        passes = d.get("n_level_passes", base.n_level_passes)
        passes = int(passes) if isinstance(passes, int | float) else base.n_level_passes
        return cls(
            part_top_mm=limits.clamp_position(PART, num("part_top_mm")),
            feed_cavity_mm=limits.clamp_position(FEED, num("feed_cavity_mm")),
            level_recoat_end_mm=limits.clamp_position(RECOATER, num("level_recoat_end_mm")),
            level_recoat_return_mm=limits.clamp_position(RECOATER, num("level_recoat_return_mm")),
            n_level_passes=int(_clamp(passes, 1, MAX_LEVEL_PASSES)),
            part_speed=limits.clamp_speed(PART, num("part_speed")),
            part_accel=limits.clamp_accel(PART, num("part_accel")),
            feed_speed=limits.clamp_speed(FEED, num("feed_speed")),
            feed_accel=limits.clamp_accel(FEED, num("feed_accel")),
            recoater_speed=limits.clamp_speed(RECOATER, num("recoater_speed")),
            recoater_accel=limits.clamp_accel(RECOATER, num("recoater_accel")),
            settle_s=_clamp(num("settle_s"), 0.0, 30.0),
        )


def compile_priming_setup(s: PrimingSettings, limits: SafetyLimits) -> tuple[Step, ...]:
    """Position pistons → HOLD for the powder load → calibrated leveling spread. Never homes a piston."""
    out: list[Step] = []

    def add(kind: str, axis: int | None = None, value: float | None = None, label: str = "") -> None:
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
    for _ in range(s.n_level_passes):
        add("move_abs", RECOATER, s.level_recoat_end_mm, "level spread")
        add("wait")
        add("move_abs", RECOATER, s.level_recoat_return_mm, "return")
        add("wait")
        add("dwell", value=s.settle_s)
    add("mark", label="priming_done")
    return tuple(out)
```

- [ ] **Step 4: Run, watch pass** — `cd backend && uv run pytest tests/test_priming.py -q` → PASS; `uv run ruff check vention_printer_interface/control/priming.py && uv run mypy vention_printer_interface/control/priming.py` → clean.

- [ ] **Step 5: Commit** — `git add backend/vention_printer_interface/control/priming.py backend/tests/test_priming.py` then commit `feat(priming): rebuild as position-load-level setup routine (spec §6)` + trailer.

---

## Task 3: Update priming store, API payload, and API tests

`priming_store` already round-trips `PrimingSettings.bounded`, so it needs no change — but the API payload and its tests reference the old compiler.

**Files:** Modify `backend/vention_printer_interface/api/app.py` (the `priming_payload` and `run_priming`); Rewrite `backend/tests/test_api_priming.py`.

- [ ] **Step 1: Update the API** in `app.py`. Change `priming_payload()` to use the new compiler and a meaningful count: replace `steps = compile_priming(s, ctrl().limits)` and the `n_cycles` computation with:
```python
    def priming_payload() -> dict[str, Any]:
        s: PrimingSettings = app.state.priming
        steps = compile_priming_setup(s, ctrl().limits)
        return {
            "settings": s.to_dict(),
            "validation": s.validate(ctrl().limits),
            "n_steps": len(steps),
            "n_level_passes": s.n_level_passes,
            "limits": ctrl().limits.to_dict(),
        }
```
Update the import at the top of `app.py`: `from vention_printer_interface.control.priming import PrimingSettings, compile_priming_setup` (was `compile_priming`). In `run_priming()`, change `compile_priming(settings, ctrl().limits)` → `compile_priming_setup(settings, ctrl().limits)`.

- [ ] **Step 2: Rewrite `backend/tests/test_api_priming.py`** to the new shape (keep the `client`/`connect_arm` fixtures from the current file; READ it first):
```python
def test_priming_get_put_persists(client: TestClient) -> None:
    p = client.get("/api/priming").json()
    assert p["validation"] == []
    assert p["settings"]["feed_cavity_mm"] == 30.0 and p["n_level_passes"] == 1
    r = client.put("/api/priming", json={"feed_cavity_mm": 22.0, "n_level_passes": 2})
    assert r.status_code == 200 and r.json()["settings"]["feed_cavity_mm"] == 22.0
    assert client.get("/api/priming").json()["settings"]["feed_cavity_mm"] == 22.0

def test_priming_run_requires_arm_then_holds_for_powder(client: TestClient) -> None:
    assert client.post("/api/priming/run").status_code == 409  # not armed
    connect_arm(client)
    r = client.post("/api/priming/run")
    assert r.status_code == 200 and r.json()["macro"] == "priming"
    # positions pistons, then pauses at the powder-load hold
    import time
    for _ in range(200):
        st = client.get("/api/status").json()["print"]
        if st["state"] == "paused":
            break
        time.sleep(0.05)
    assert client.get("/api/status").json()["print"]["state"] == "paused"
    client.post("/api/print/abort")

def test_priming_bounded_clamps_recoater(client: TestClient) -> None:
    connect_arm(client)
    r = client.put("/api/priming", json={"level_recoat_end_mm": 5000.0})
    assert r.status_code == 200 and r.json()["settings"]["level_recoat_end_mm"] <= 972.0
```

- [ ] **Step 3: Run** — `cd backend && uv run pytest tests/test_api_priming.py tests/test_priming.py -q` → PASS. Then the FULL suite `uv run pytest -q` (exit 0) + `uv run ruff check vention_printer_interface tests` + `uv run mypy vention_printer_interface` → all clean. (Run the full suite because this touches shared app.py.)

- [ ] **Step 4: Commit** — `git add backend/vention_printer_interface/api/app.py backend/tests/test_api_priming.py` then commit `feat(api): priming payload/run use the setup compiler; hold-for-powder run` + trailer.

---

## Task 4: Rebuild the PrimingPanel (frontend)

**Files:** Modify `frontend/src/components/PrimingPanel.tsx` and `frontend/src/lib/api.ts` (`PrimingPayload` type); Create `frontend/src/lib/priming.ts` + `frontend/src/lib/priming.test.ts` (pure preview generator).

- [ ] **Step 1: Failing test** `frontend/src/lib/priming.test.ts`:
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { primingSteps } from "./priming.ts";

test("plain-language priming sequence: up, down, load, level", () => {
  const s = { part_top_mm: 0, feed_cavity_mm: 30, level_recoat_end_mm: 925, level_recoat_return_mm: 350, n_level_passes: 1 };
  const lines = primingSteps(s);
  assert.match(lines[0], /build.*piston.*up/i);
  assert.match(lines[1], /feed.*piston.*down/i);
  assert.ok(lines.some((l) => /load powder/i.test(l)));
  assert.ok(lines.some((l) => /level/i.test(l) && /925/.test(l)));
});
```
- [ ] **Step 2: Run, watch fail** — `cd frontend && node --experimental-strip-types --test src/lib/priming.test.ts` → FAIL.
- [ ] **Step 3: Implement** `frontend/src/lib/priming.ts`:
```ts
export interface PrimingSettings {
  part_top_mm: number; feed_cavity_mm: number; level_recoat_end_mm: number;
  level_recoat_return_mm: number; n_level_passes: number;
}
/** Plain-language "what this will do" lines for the priming setup routine. */
export function primingSteps(s: PrimingSettings): string[] {
  const lines = [
    `Raise the build piston to the top (${s.part_top_mm} mm)`,
    `Lower the feed piston to open a powder cavity (${s.feed_cavity_mm} mm)`,
    `HOLD — load powder into the feed, then Resume`,
  ];
  for (let i = 0; i < s.n_level_passes; i++)
    lines.push(`Level pass ${i + 1}: spread to ${s.level_recoat_end_mm} mm, return to ${s.level_recoat_return_mm} mm`);
  return lines;
}
```
- [ ] **Step 4: Run, watch pass** — same command → PASS.
- [ ] **Step 5: Update `api.ts`** — change `PrimingPayload` to `{ settings: Record<string, number>; validation: string[]; n_steps: number; n_level_passes: number; limits: Record<string, unknown> }`.
- [ ] **Step 6: Rebuild `PrimingPanel.tsx`** — READ it first. Replace the old param fields (feed start / thick layer / thick count / feed step / recoat end/return) with the new ones: `feed_cavity_mm`, `part_top_mm`, `level_recoat_end_mm`, `level_recoat_return_mm`, `n_level_passes` (all editable via the existing `field(k,label)` pattern + `api.setPriming`). Show the plain-language `primingSteps(settings)` list ("what this will do"). Keep RUN PRIMING (`api.primingRun`) + ABORT; ADD a **RESUME** button (`api.printResume`) shown when the print state is `paused`, labeled "Powder loaded — resume", so the operator can continue past the hold. Show `n_level_passes` and `n_steps` in the summary. Import `primingSteps` + `type PrimingSettings` from `../lib/priming.ts`; cast `p.settings` to `PrimingSettings` for the preview.
- [ ] **Step 7: Verify** — `cd frontend && node --experimental-strip-types --test src/lib/priming.test.ts` (PASS), full lib suite (all pass), `npm run build` (tsc clean).
- [ ] **Step 8: Commit** — `git add frontend/src/lib/priming.ts frontend/src/lib/priming.test.ts frontend/src/lib/api.ts frontend/src/components/PrimingPanel.tsx` then commit `feat(priming): panel for the setup routine — position, hold-for-powder, level` + trailer.

---

## Self-review notes
- Spec §6 coverage: build-up/feed-down/hold-load/level → Tasks 1,2,4; API → Task 3. Calibration-pending values (`feed_cavity_mm`, `level_recoat_*`, `n_level_passes`) are editable defaults, per spec §13.
- Type consistency: `PrimingSettings`, `compile_priming_setup`, `primingSteps`, `n_level_passes` used consistently across tasks. Old `compile_priming`/`n_cycles`/thick-precoat fields are fully removed.
- The thick-precoat loop is intentionally deleted here and re-created in Plan 3's print compiler.
