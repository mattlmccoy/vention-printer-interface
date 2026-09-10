# Priming walkthrough — design (amends redesign spec §6)

**Date:** 2026-09-10. **Supersedes** the "Priming as a full page" scope of Plan 4 Task 5 with a
guided, stepped **powder-loading + leveling walkthrough**. Approved in brainstorming 2026-09-10.

## Purpose
Priming is the manual setup that gets powder into the machine and levels the bed before a print:
position the pistons, open a feed cavity of the right depth, hold for the operator to pour powder,
then spread it level across the runway. The current page is one small module. Replace it with a
step-by-step walkthrough that exposes the recoater and piston controls the operator actually needs,
and computes how deep to open the feed cavity from the powder a print will consume.

## Grounding (verified in code — not invented)
- Pistons `PART=1`, `FEED=2` travel `0–145 mm` (`safety.TRAVEL_MM`). `move_abs` **large = DOWN**
  (opens a cavity), **small = UP/flush**. Homing a piston ejects powder — priming never homes one.
- The print routine **raises the feed piston by one layer-thickness per layer** to supply powder, so
  a whole job draws a feed column ≈ `PrintSettings.total_thickness_mm` = Σ(layer_thickness × n_layers)
  over `thick_precoat + thin_precoat + printing (+ postcoat)` — already the printability gate
  (`total_thickness_mm ≤ feed_end_mm = 145`, `print_settings.py:155`). So the powder to load maps
  **directly and exactly to a feed-piston fill depth in mm**. `total_thickness_mm` already includes
  the thick precoats (runway + part-cavity fill), which the operator required.
- **Unknown / not in code:** the feed- and part-cylinder cross-section **areas**. Without them we
  cannot convert depth → volume → grams. So Phase 1 shows **depth (mm)** only; grams is a documented
  future calibration hook, never computed from an invented area.

## Fill-depth calculation (new pure helper — `powder.py` + `powder.ts` mirror, TDD'd)
`feed_cavity_mm` (the depth the feed piston opens) is derived by one of three operator-chosen sources,
then `+ margin_mm`, clamped to `[0, feed travel = 145]`:
- **Paired to job** → `PrintSettings.total_thickness_mm + margin_mm`. Exact; reflects the selected
  sliced job (a selected job sets the printing phase's layers × thickness).
- **Manual — layers × thickness** → `n_layers × layer_thickness + margin_mm`, with an on-screen
  reminder that this must include the precoat layers (runway + part-piston fill).
- **Manual — depth** → operator types the mm directly.

`margin_mm` is an editable safety extra (default TBD-calibration, e.g. 5 mm). The helper is the seam
where a future **computed** value will land: feed depth from the powder **volume** needed to fill the
part-piston cavity + runway backfill, once the cylinder areas are measured. That path is documented
in `powder.py` with its required (currently-unknown) geometry inputs; it is NOT wired into the live
calc until those numbers exist.

## The walkthrough (stepped; operator triggers every motor move)
Each step shows a **model preview** of its move on the live diagram first (Task 4's `mode="model"`
violet ghost), then the operator presses **Run this step** to execute it live. The routine is the
existing `compile_priming_setup` (position → hold → level); the walkthrough drives it and can run it
a step at a time (`hold`/`resume` already exist).

1. **Amount** — pick source (job / manual layers×thickness / manual depth); show the resulting
   `feed_cavity_mm` and its **% of the 145 mm feed travel** as a fill gauge.
2. **Build piston up** — part piston → `part_top_mm` (~0, flush).
3. **Open feed cavity** — feed piston → `feed_cavity_mm` (down) — opens the cavity from Step 1.
4. **Load powder (HOLD)** — pour powder into the open cavity; live diagram; **Resume** when loaded.
5. **Level** — recoater spread/return across the runway. **Operator-repeatable**: a "Spread again"
   control the operator presses until the bed looks level (NOT a fixed pass count). Bounded recoater
   controls exposed here.
6. **Ready** — mark `priming_done`; summary; link to Print.

## Persistent surface (always visible beside/under the stepper)
- The live `Elevation` diagram with Task 4's **live-vs-model** markers, filling the page as the
  centerpiece (the "full page, not a little box" ask).
- A **bounded control strip** (per the operator's choice: bounded nudges + set-position, NOT full
  jog): recoater spread / return / nudge; pistons ± nudge and "move to X" — every target clamped to
  axis travel. Lets the operator correct at any step without leaving the flow.

## Piston movement arrows (new)
Each piston in the diagram shows a small **directional arrow that blinks only while that piston is in
motion** — up-arrow when the piston is moving up (position decreasing), down-arrow when moving down
(position increasing). Direction comes from the **sign of the piston's position delta** between
telemetry frames (a small pure helper `pistonArrow(prev, curr)` → `"up" | "down" | null`, TDD'd).
"In motion" reuses Task 4's `motion_complete[axis] === false`. The blink respects
`prefers-reduced-motion` (no blink → steady arrow) like the existing marker pulse.

## Primed positions become the print's start (user, 2026-09-10)
When priming finishes, the current piston positions ARE the print's starting positions. Decisions:
- **A print always requires a primed bed.** The Print run refuses (409) unless a valid primed-state
  record exists — there is no cold-home print path.
- **A primed print skips piston homing** (homing a piston ejects the powder just loaded) and **homes
  only the gantries** (printhead + recoater hold no powder). The feed and build pistons START from
  the saved primed positions; the per-layer feed-up loop then draws from the primed column (which the
  fill-depth calc sized to exactly this job).
- **Capture is server-side and trustworthy.** The walkthrough's final "Bed is primed — finish" action
  calls `POST /api/primed/capture`, which snapshots the controller's own live piston positions (NOT
  client-supplied numbers) into a persisted `PrimedState { part_mm, feed_mm, captured_at }`.
- `compile_print`'s setup changes: replace `home_all` + feed→feed_end with **home gantries only**
  (per-axis `home` for printhead + recoater), no piston home, no feed-to-145 move; the pistons are
  already primed. `part_zero_mm` is captured from the primed part position as today.

## Non-goals / deferred
- Grams / volume readout (needs cylinder areas — calibration).
- The computed feed-depth-from-part-volume calc (documented hook only).
- Any change to the Print routine, the compiler's semantics, or the piston sign convention.

## Verification
- Pure helpers (`powder` fill-depth, `pistonArrow` direction) are red-green TDD'd.
- Layout / diagram / walkthrough wiring is UI (not unit-testable): gate = tsc-clean `npm run build`
  + full suite green (incl. `theme.test.ts` no-`:root` / no-color-literal invariant) + a browser
  check by the coordinator before merge. `styles.css` stays tokens-only.
