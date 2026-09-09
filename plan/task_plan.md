# Task plan — Vention Printer Interface

Spec: `docs/superpowers/specs/2026-09-08-vention-printer-interface-design.md`.
Plans: `docs/superpowers/plans/2026-09-08-backend-core.md` (Plan 1), Plan 2 recipe engine, Plan 3 UI.

## Plan 1 — backend core (2026-09-08/09)
- [x] T1 scaffold · T2 routes · T3 parsers · T4 registry · T5 simulator · T6 real transport
- [x] T7 PrinterDevice · T8 safety · T9 controller · T10 limits store · T11 recorder
- [x] T12 API + CORS + WS · T13 vpi-serve · T14 vpi-probe/monitor · T15 docs/CI
- Verification: `uv run pytest` 102 passed (1 hardware test skipped); ruff + mypy strict clean;
  `vpi-serve --backend simulated` live: connect → arm → home → move 100 mm applied → 403 on
  cross-origin write without header.
- Findings during TDD: (a) `clear_fault` must refuse while the last read failed, not just when the
  stale sample looks clean; (b) a fault's heater-off can fail while the link is down, so FAULT
  re-enforces stop + heater-off on every successful poll.

## Review pass 1 (2026-09-09, independent read-only review of Plan 1) — all fixed, test-first
- C1 heater state never observed on hardware (outputs not subscribed) → subscribe
  `devices/+/+/digital-output/#`; tri-state `heater_on`; watchdog counts from commanded-on.
- C2 MQTT never-connected reported healthy → require CONNACK, check publish rc, clear cache on
  disconnect; unknown `estop/status` is a trip.
- C3 `/api/estop` always `{ok:true}` → latches FAULT itself, reports per-step outcome, 502 on failure.
- H1 gate race → FAULT+disarm latched before stop; guarded actions check under the IO lock;
  faulted state re-enforces stop/heater-off every poll.
- H2/H3/H4 disarm ordering, arm needs fresh clean sample, clear-fault needs post-fault sample
  with heater observed off and disarms.
- H5 relative move needs fresh sample + idle axis. H6 stale age measured after the read.
  H7 per-attach poll event; orphaned reads ignored. M2 health refreshed every 10 polls.
  M3 e-stop release waits for drives ready. M4 simulator end-stops instead of target clamping;
  `estop_on_boot`, `read_delay_s`, `health_reachable`, `suppress_output_echo` knobs.
- Open from review: whether `G28` blocks the HTTP reply until homed (homing is issued outside
  the IO lock with a 330 s timeout; confirm in the lab). Citations corrected.

## Plan 2 — recipe engine (2026-09-09)
- [x] T1 RecipePlan + compile_recipe · T2 RecipeController · T3 store + layers.csv · T4 API · T5 docs
- Verification: 164 backend tests; ruff + mypy strict clean.

## Plan 3 — Studio UI (2026-09-09)
- [x] Shell ported from FLIR (theme verbatim + vpi keyframes + axis trace tokens; styles; studio components)
- [x] lib: layout (vpi.layout.v1), operator (vpi.operator.v1, :8020), api (31 routes locked by test), telemetry, recipe mirror (same 37/280 steps as backend), machineview geometry, format/gates
- [x] MachineView (gantries + pistons to scale, limit bands, heater glyph, recipe cursor, click-to-jog), TimePlot (% of travel), sections (connection/arm/axes/heater/recipe/recording), StatusBar (never green, unknown = amber)
- [x] Gating as T&C: controllable = connected && armed; STOP / heater OFF / E-STOP / DISARM / pause / abort on connected only; confirm on START PRINT and heater ON
- Verification: `npm test` 28 passed; `npm run build` green; browser against `vpi-serve --backend simulated`:
  connect → ARM → home all (positions → 0, plot shows it) → start dry run (step 6/280, REC auto-log) →
  pause → E-STOP (FAULT latched, recipe aborted, run closed with manifest) → release → clear fault → read-only.
- Not done: screenshots on disk (browser pane only); the lab wireframe is not embedded (schematic drawn in its style).

## Plan 3b — console redesign (2026-09-09, after user review "this is a 3D printer controller")
- Spec §6 rewritten: share FLIR's design language, not its studio layout. Mockup approved (artifact "Binder Jet Console").
- Backend: `control/events.py` (ring + sinks, `/api/events`, status.events), `control/macros.py`
  (`load_cart` = home all then both pistons to bottom of travel; `clear_bed`) run through
  `RecipeController.start_macro`, `part_zero_mm` captured at start and re-captured after the setup
  home, `part_height_measured_mm` in the snapshot, `estimate_duration_s`; auto-log run now opens
  before the recipe starts so `recipe_started` is recorded once.
- Frontend rewritten: Print / Prepare / Control / Runs views; ARM lock + E-STOP in the top bar;
  fault banner with ordered recovery; Elevation drawing; layer-cycle strip; heater ring; layer stack
  vs powder budget; jog pads labelled by physical motion; park macros.
- User answers: no custom GUI on the Vention HMI (open question for Vention); load cart = pistons
  at bottom of travel + gantries homed, then manual placement; part height = measured (piston
  minus zero at start) with the recipe value beside it, amber on mismatch; current lab scripts
  to follow.
- Verification: backend 173 passed; frontend 27 passed; build green; browser: ARM → Control (jog
  pads live, macros gated) → Prepare (stack, 11:39 estimate, 280 steps) → START DRY RUN → Print
  view live (layer 0/12 setup, feed piston moving, REC open, event log).

## Blocked on the user (lab)
- [ ] Step 0-1: network + `vpi-probe --ip 192.168.0.2` → `plan/probe_report.json`
- [ ] Step 2: reconcile parsers/fixtures; update `plan/notes.md`
- [ ] Step 3-4: first ARMed motion; heater IO pin identification

## Open technical unknowns
- Reply JSON shapes (positions, complete, health) — SDK-derived only.
- `drive/+/motionComplete` payload and whether it fixes the V1.py completion quirk.
- Heater IO module id/pin (default `1,0` is a placeholder).
- Whether the controller's MQTT broker accepts external clients without auth (docs say yes).

## Next
- Lab commissioning (docs/commissioning.md), then reconcile fixtures from plan/probe_report.json.
- v2: MetPrint hot-folder sync per layer, FLIR/T&C links, deploy/ LaunchAgent, embed the wireframe.
