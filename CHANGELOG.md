# Changelog

Notable changes to the Vention Printer Interface. Versions follow semantic versioning; each entry
corresponds to a tagged merge to `main`.

## v0.8.4 — 2026-09-16

### Added
- **Camera hot-plug auto-reconnect (overview).** While a viewer is watching the overview live feed, unplugging the camera no longer kills the stream: after a sustained grab failure the `OverviewStreamer` closes the dead capture and rebuilds it via a factory that **re-resolves the camera's current device index** (macOS can hand out a different index on replug), retrying on a backoff until the camera returns — so unplug/replug recovers the feed by itself. A single transient grab failure is still tolerated (unchanged). (Science-capture reconnect is a follow-up.)

## v0.8.3 — 2026-09-16

### Added
- **Multi-axis homing (re-applied)** — `home()`/`home_all()` union into the pending-home set instead of overwriting it, so homing several axes in quick succession (or homing one while another is still in its homing window) references EVERY axis that homed, not just the last. This was shipped in v0.8.0, reverted in v0.8.1 during a hardware incident, and is now restored: that incident was the transient-read-timeout hard-fault (fixed in v0.8.2), not this change. Regression test re-added (`test_homing_axes_in_succession_all_get_referenced`).

## v0.8.2 — 2026-09-16

### Fixed
- **Operator no longer breaks all motion on a transient telemetry timeout** (critical). A single timed-out `/smartDrives/position` read hard-faulted the controller, which then re-fired `stop_all` every poll for as long as it saw motion — aborting even HMI-commanded moves (home / relative / absolute), until the operator was physically disconnected. Root cause: the read-failure path faulted on the FIRST failed read, bypassing the `stale_fault_s` blind-tolerance that `evaluate()` already applies to slow successful reads. Now a read failure only faults once the blind period exceeds `stale_fault_s`; a brief stall (e.g. the MachineMotion saturated by a sweep or the HMI) surfaces `read_error` and recovers on the next good read. Triggered 2026-09-16 by the piston-sweep load.

## v0.8.1 — 2026-09-16

### Fixed
- **Reverted the v0.8.0 multi-axis homing change** — the v0.8.0 union of `_homing_axes` (`home()`/`home_all()`) regressed homing on real hardware ("home values aren't getting written properly"). Restored the known-good v0.7.0 per-home overwrite to unblock the machine. The original concurrent-multi-axis homing edge (an earlier home dropped when a second is issued mid-window) is re-opened and will be fixed with a hardware-verified per-axis promotion model, not the coarse all-pending-at-once union. No other v0.8.0 feature is affected.

## v0.8.0 — 2026-09-16

### Fixed
- **Multi-axis homing no longer drops earlier homes** — pressing Home on several axes in quick succession (or homing one axis while another is still inside its homing window) referenced only the *last* axis; the earlier axes stayed "unreferenced" and lost their homed position. `control/controller.py` `home()`/`home_all()` now **union** into the pending-home set instead of overwriting it, so every axis that homes records its true homed position and stays referenced. Regression test in `test_controller.py` (home axis 1, then home axis 2 mid-window → both referenced).

### Added
- **Runs outcome status** — each run now carries a derived outcome, shown as a coloured chip on its list card and in the run detail. `recording/recorder.derive_run_status` maps a run's `events.json` labels to `finished` (green), `aborted` (warn), `fault`/e-stop (danger), `running`, `incomplete`, or `recorded` (verified against the real experiment set; an unknown/absent outcome never renders as success). `GET /api/recordings` carries the `status`, so the list needs no per-run event fetch.
- **Runs print-history thumbnails** — a run card shows the printed job's slicer preview when the run is linked to a job. Runs now record the selected job (`experiment.job_folder`/`job_name`) going forward; runs with no job (every existing run, and manual prints) show a neutral layer-stack placeholder — no fabricated image.
- **Reveal a run on disk** — `POST /api/recordings/{run}/reveal` opens the run's `metadata.json` in the OS file browser (the operator runs locally) and returns the absolute path; a "Reveal on disk" button on the run detail shows/opens it. Path resolution is guarded to the experiments root (traversal → 400).

### Changed
- **Layer-accuracy chart tolerance now reads as tolerance** — the per-layer build-piston chart drew a faint grey block above each bar for the ±tolerance band, which read as an unreached remainder even when the layer was on target. It is replaced by a solid target tick across each bar plus a capped ±tolerance error-bar whisker centred on the target — a range marker, not a "missed" box.
- **Setup page reorganised into a clear hierarchy** — the Setup tab is now three labelled tiers: **Guided setup** (the primary 7-step spine), **Review captures** (current-layer stills + capture browser), and **Calibration tools** (the capture-pose and manual raw-point calibrations, grouped and collapsed as a clearly-secondary tier). All existing functionality is preserved.
- **Run cards say "N layers"** instead of the ambiguous "N L" (which read as litres).

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
