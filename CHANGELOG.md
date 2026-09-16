# Changelog

Notable changes to the Vention Printer Interface. Versions follow semantic versioning; each entry
corresponds to a tagged merge to `main`.

## v0.7.0 — 2026-09-16

### Added
- **Meteor printhead-firing readiness** — a pre-flight check so the operator never sweeps the printhead over a bed that will get no binder. `control/meteor.py` adds a `MeteorAdapter` interface with a real `HotFolderMeteorAdapter` (Meteor fires from the hot folder; `ready` only when the selected job is complete **and** under a watched root — absence, incompleteness, and an unwatched location are each a distinct non-ready reason, never a false green) plus a `SimulatedMeteorAdapter` for tests. `GET /api/meteor/status` reports readiness for the selected job (read-only — no motion, no firing). The Job tab's "job → motion" card now shows live **MetPrint firing** readiness in place of the old static "queue the TIFFs" placeholder. Design: `docs/superpowers/specs/2026-09-16-meteor-adapter-design.md`. Deferred (documented): the per-pass fire hook, the MachineMotion-output → Meteor external-PD trigger (blocked on two open hardware facts), and the PCMD_* control DLL (blocked on Windows + the Meteor SDK).

## v0.6.0 — 2026-09-16

### Added
- **Lane B deviation heatmap, end-to-end** — the Analysis tab now renders a per-layer CAD-vs-real deviation heatmap for an arbitrary part. `GET /api/analysis/{run}/lane-b?layer=N&folder=F` resolves the registered science capture and its CAD slice, extracts both outlines (Otsu, largest external contour — never a false empty shape), centroid-aligns the CAD to the print so the result is shape+size deviation independent of bed placement, and returns the signed deviation field plus the capture URL. The `LaneBCard` overlays a diverging blue→grey→red heatmap on the capture and shows mean|·| / RMS / max / area-ratio. Registration is centroid-translation only and its absolute numbers want validation on real on-powder captures.

## v0.5.0 — 2026-09-16

### Added
- **Live science-camera alignment stream** — the capture-pose calibration tool now streams live MJPEG from the science camera (`GET /api/vision/science/stream`, setup-only) under a start/stop toggle with the crosshair + circular-target overlay, so the overhead cam can be aimed smoothly before saving the capture pose.
- **Lane B deviation-field core** — `analysis/lane_b.py`: signed per-point CAD-vs-real deviation (the heatmap data) + summary stats (mean|·|, RMS, max, area ratio) for an arbitrary printed part vs its CAD slice. Pure + tested; the capture/CAD extraction + Analysis heatmap overlay are the next integration step (need real captures).

## v0.4.1 — 2026-09-16

### Added
- **Capture-pose calibration** — a Setup-tab aid to aim the overhead science camera over the bed: grab an on-demand science frame (`GET /api/vision/science/frame.jpg`), a centred crosshair + circular-target overlay, recoater jog, and a "Set capture pose" button that saves the recoater position as `capture_recoater_mm`.

## v0.4.0 — 2026-09-16

### Added
- **Camera-enabled print routine** — the overhead science camera (on the recoater gantry) can
  capture every layer: with `capture_stages` on and `capture_recoater_mm` set, each layer drives the
  recoater to a capture pose over the bed, dwells `capture_settle_s` to settle, then shoots the fresh
  layer at the constant recoat plane. `capture_recoater_mm = 0` keeps the fixed-camera behaviour.
  Both settings editable in Print Parameters → advanced.

### Fixed
- **Settled-phase layer accuracy** — per-layer build-piston height is sampled at the next layer's
  start (piston at rest), not at the completion instant mid pre-heater-swing. Proven on a real run:
  the earlier "0 then double" (±200 µm on two layers) was a measurement-sampling artifact; the piston
  hit its 0.2 mm target every layer.

## v0.3.1 — 2026-09-16

### Added
- **Actual-thickness-vs-target chart** on the Runs page (replaces the per-layer deviation scatter):
  each layer's actual build-piston thickness as a bar against its commanded target tick with a
  ±tolerance band — a dropped (empty bar) or doubled layer is obvious at a glance.

### Fixed
- **Run-scoped event log** — the Runs event log shows the selected run's own `events.json` instead
  of the live session feed (which looked like it "disappeared" after an operator restart).

## v0.3.0 — 2026-09-15

Reliability, diagnostics, and data-forward run analysis.

### Fixed
- **E-stop no longer undefines motor positions.** An MM2 e-stop is Safe-Torque-Off (cuts motor
  torque, not the encoder); referenced positions now survive it. Regression test pinned.
- **Feed piston drops before the recoater on printing layers.** The recoater repositioned to the
  spread start at layer end, so the anti-backlash preload landed too late; it now repositions at
  layer start, after the preload.
- **Build-piston deviation chart populates** — `layer_accuracy.csv` is served again.

### Added
- **Reference-at-current** — re-reference every axis at its current position without homing, for
  recovery after an e-stop/restart when the machine kept power.
- **One-click operator restart** — top-bar button; re-execs the operator in place.
- **Runs analysis plots** — cumulative build height (commanded vs actual), per-axis activity
  timeline, hover readouts; calm, data-forward styling.
- **Analysis tab** lists only runs with vision captures (`capture_count`).
- **Full Print Parameters surface** — per-axis speed/accel for all phases, heater accel, machine
  geometry positions, timing; most-used up top, the rest in an advanced section.
- **Build-piston characterization sweep** (`backend/scripts/piston_sweep.py`) — diagnostic to find
  deterministic per-step position errors (the "one layer zero, next layer double" effect).

### Performance
- **Faster choreography** — move-started detection lets a wait end as soon as the move completes
  instead of always sitting out the `min_wait_s` floor (default lowered 0.5→0.25 s, tunable via
  `--print-min-wait`). Removes several seconds of dead time per layer.

## v0.2.0 and earlier

Pre-changelog. See the git history for the console redesign, recording/vision, priming, and the
initial choreography work.
