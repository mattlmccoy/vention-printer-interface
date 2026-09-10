# Faithful Print Routine — Implementation Plan (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax. This is safety-relevant motion code — **the compiled `Step` sequence is TDD'd against the async lab script** (`docs/superpowers/specs/2026-09-10-print-routine-fidelity.md`). Backend: uv/pytest/ruff/mypy-strict. Commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

**Goal:** Rewrite `compile_print` so the emitted step sequence faithfully mirrors the user's async lab script (stages, recoater return to 350, concurrent printhead-jet + recoater-retract, heater 425→600 slow-follow, feed-exhaustion safety, part→max finish) — with ONE user override: the feed piston advances every layer INCLUDING printing (it is the powder supply) — plus the approved enhancements (multi-pass jetting, pre-heater drop+return, postcoat toggle, IPA exposure) and the **primed-start** setup (home gantries only; pistons start from `PrimedState`; a print requires a primed bed).

**Architecture:** Least-churn — keep the phase model (`thick_precoat`/`thin_precoat`/`printing`/`postcoat`) but make the compiler phase-body faithful to the script, and add the missing per-phase / position fields. Branch `redesign/ux-visual`.

**Reference:** the fidelity spec (ground-truth sequence + discrepancy table). Read it first.

---

## Task 1: Model fields for the faithful routine (backend, TDD)

**Files:** `backend/vention_printer_interface/control/print_settings.py` + `backend/tests/test_print_settings.py`.

- [ ] **Step 1 (RED)** — add tests asserting new defaults/bounds exist:
  - `PhasePlan` gains `feed_thickness_mm: float` — the feed-piston advance per layer, distinct from
    `layer_thickness_mm` (the part-piston drop). Script defaults: thick `feed_thickness_mm=7.0`
    (part fixed → `layer_thickness_mm` unused for part in thick), thin `layer_thickness_mm=0.2` +
    `feed_thickness_mm=0.4`, printing `layer_thickness_mm=0.2` + `feed_thickness_mm=0.4` (feed
    ADVANCES during printing — USER OVERRIDE of the script; the feed piston is the powder supply).
  - `PrintSettings` gains position fields from the script: `recoater_return_mm=350.0`,
    `heater_start_mm=425.0` (heater_end_mm already 600.0), and `part_max_mm=75.0` (final part drop =
    `MAX_TRAVEL`). Update script-faithful defaults: `recoater_end_mm=925.0`, `printhead_end_mm=900.0`.
  - `bounded()` clamps each new field into axis travel (feed/recoater positions via
    `limits.clamp_position`, thicknesses via `_clamp(…, 0, 50)`); `to_dict`/`from_dict` round-trip them.
  Run `uv run pytest backend/tests/test_print_settings.py -k "field or default or bounded"` → RED.
- [ ] **Step 2 (GREEN)** — implement the fields + bounded clamps + defaults. Run → those tests green.
- [ ] **Step 3** — full `uv run pytest` will have MANY red assertions in the existing sequence tests
  (they encode the OLD compiler). That is expected — Task 2 rewrites the compiler and those tests
  together. For THIS task, only the new-field tests must pass; do NOT yet delete the old sequence
  assertions. If the suite is too red to commit cleanly, mark the known-failing sequence tests with a
  clear `@pytest.mark.skip(reason="rewritten in Plan 7 Task 2")` and REMOVE the skips in Task 2. ruff+mypy clean.
- [ ] **Step 4 — Commit** — `feat(print): add feed-thickness + script-faithful position fields`.

## Task 2: Rewrite `compile_print` faithful to the script (backend, TDD)

**Files:** `backend/vention_printer_interface/control/print_settings.py` (`compile_print`, `estimate_duration_s`) + `backend/tests/test_print_settings.py` (rewrite the sequence assertions to the script).

Target structure (mirror the fidelity spec exactly; `primed` = the print starts from the primed bed):

```
setup:
  home PRINTHEAD; wait
  home RECOATER;  wait          # gantries only — NO piston home (primed-start keeps the powder)
  set profiles (part, feed, recoater=precoat, printhead=base)
  # pistons already at the primed positions; NO feed→feed_end move

for each phase in (thick_precoat, thin_precoat, printing, postcoat):
  if phase == postcoat and not postcoat_enabled: continue
  if phase.n_layers == 0: continue
  set phase profiles (recoater precoat vs print; printhead base vs print)
  for layer in range(n_layers):
    # 1) SPREAD
    move_abs RECOATER recoater_end_mm; wait
    # 2) FEED ADVANCE — EVERY phase incl. printing (USER OVERRIDE: feed is the powder supply,
    #    it advances during printing too). Only skipped where feed_thickness_mm == 0.
    if feed_thickness_mm > 0:
        move_rel FEED -feed_thickness_mm; wait; dwell settle_s
        # (feed-exhaustion safety is enforced at run time by travel clamp + validate; the
        #  compiled guard: if projected feed position <= 0 the compiler stops emitting further
        #  layers and emits a final `move_abs RECOATER recoater_home_mm` + mark "feed_exhausted".)
    # 3) PART DROP — thick: none (build fixed, backfill); thin/printing: part += layer_thickness_mm
    if phase != thick_precoat and part_drop_enabled:
        move_rel PART layer_thickness_mm; wait          # (for thin this happens before the return)
    # 4) PRECOAT RETURN vs PRINT
    if phase in (thick_precoat, thin_precoat):
        move_abs RECOATER recoater_return_mm; wait; mark layer_end; continue
    # ---- printing ----
    # concurrent jet + retract: issue BOTH moves, then ONE wait
    move_abs RECOATER recoater_home_mm
    move_abs PRINTHEAD printhead_end_mm      # jets while recoater retracts
    wait
    move_abs PRINTHEAD printhead_home_mm; wait
    for _ in range(n_jet_passes - 1):        # extra passes (enhancement), sequential
        move_abs PRINTHEAD printhead_end_mm; wait
        move_abs PRINTHEAD printhead_home_mm; wait
    if pre_heater_drop_mm > 0: move_rel PART pre_heater_drop_mm; wait   # drop before heat
    if heater_enabled:
        move_abs RECOATER heater_start_mm; wait          # 425
        heater 1
        set_speed RECOATER heater_speed; set_accel RECOATER heater_accel   # slow follow
        move_abs RECOATER heater_end_mm; wait            # 600
        heater 0
        set_speed RECOATER printing.recoater_speed; set_accel …           # restore
    if pre_heater_drop_mm > 0: move_rel PART -pre_heater_drop_mm; wait     # raise → net one layer
    move_abs RECOATER recoater_end_mm; wait
    mark layer_end

finish:
  home PRINTHEAD; wait
  home RECOATER;  wait
  move_abs PART part_max_mm; wait     # drive the part cylinder to MAX_TRAVEL
```

- [ ] **Step 1 (RED)** — REWRITE the sequence tests to assert THIS structure, cycle by cycle:
  (a) setup homes printhead+recoater only, NO `home_all`, NO `home`/move of PART/FEED in setup;
  (b) a thick layer: spread→end, feed −feed_thickness, NO part move, return→`recoater_return_mm`;
  (c) a thin layer: spread→end, feed −feed_thickness(0.4), part +layer_thickness(0.2), return→350;
  (d) a printing layer: spread→end, feed −feed_thickness(0.4) (feed ADVANCES in printing), part +0.2, then `move_abs RECOATER home` immediately
      followed by `move_abs PRINTHEAD end` with a single `wait` after both (assert the two move steps
      are adjacent with no wait between), printhead home, then (heater on) heater@425→600, part→max finish;
  (e) `n_jet_passes>1` adds the extra printhead end/home pairs;
  (f) `pre_heater_drop_mm>0` brackets the heater with part down/up (net one layer);
  (g) `postcoat_enabled=False` omits the postcoat phase; the finish still drives part→`part_max_mm`.
  Run → RED (current compiler differs).
- [ ] **Step 2 (GREEN)** — rewrite `compile_print` to the target; update `estimate_duration_s` for the
  new setup (no home_all → homing only 2 gantries; use per-axis homing times). Remove any Task-1 skips.
  Run the full `test_print_settings.py` → green.
- [ ] **Step 3** — `uv run pytest` (whole backend) — fix EVERY stale assertion in other tests
  (test_api, test_controller, etc.) that encoded the old sequence/step counts; ruff + mypy strict clean.
- [ ] **Step 4 — Commit** — `feat(print): compile_print faithful to the async lab script + primed start`.

## Task 3: Require a primed bed + reconcile the frontend mirror (TDD)

**Files:** `backend/.../api/app.py` (print run guard) + its test; `frontend/src/lib/print_settings.ts`, `frontend/src/lib/estimate.ts` (+ their tests), `frontend/src/components/RoutinePanel.tsx` (expose the new fields), and the recipe-mirror test that asserts the same step count as the backend.

- [ ] **Step 1 (RED, backend)** — test: the print start route returns **409 "prime the bed first"**
  when `app.state.primed is None`, and proceeds when a `PrimedState` exists. Run → RED.
- [ ] **Step 2 (GREEN)** — add the guard to the print start handler. Run → green; full pytest green.
- [ ] **Step 3 (frontend)** — the frontend recipe mirror / `estimate.ts` reproduce the compiled step
  count for the UI. Update them to match the new `compile_print`, update their tests, add the new
  editable fields (`feed_thickness_mm`, `recoater_return_mm`, `heater_start_mm`, `part_max_mm`) to
  `RoutinePanel`. `npm test` green (mirror step-count test included) + `npm run build` clean. Surface
  the 409 "prime the bed first" via the existing error path.
- [ ] **Step 4 — Commit** — `feat(print): require a primed bed; frontend mirror matches faithful compile`.

---

## Self-review
- Covers every discrepancy in the fidelity spec (feed advances every layer incl. printing per the user
  override, 350 return, feed≠part thickness,
  concurrent jet+retract, heater 425→600, feed-exhaustion, part→max finish, primed-start setup) plus
  the approved enhancements (multi-pass, pre-heater drop+return, postcoat toggle, IPA exposure kept).
- The compiled sequence is the contract and is TDD'd cycle-by-cycle against the script.
- Coupling: Task 2 changes step counts → Task 3 reconciles the frontend mirror + all stale backend
  assertions in the SAME plan; nothing left half-updated.
