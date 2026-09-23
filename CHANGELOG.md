# Changelog

Notable changes to the Vention Printer Interface. Versions follow semantic versioning; each entry
corresponds to a tagged merge to `main`.

## v0.13.0 — 2026-09-23

### Added
- **Lightweight camera mode** (Settings → Camera settings; on by default on Windows). For cameras that share a slow USB path — the lab PC runs both ELPs through a hub behind a USB-Ethernet adapter, where two streams at 1080p+ truncate frames. Live views run at 1280×720 @ 15 fps (measured clean for both cameras together), and every science still — during prints and Camera Studio snapshots — is taken at full resolution, lossless, with that camera alone: other live views pause for a moment and resume. Off (the Mac): full-quality streaming as before.
- **Camera views reconnect by themselves** when a stream drops (e.g. a cable pulled at a gantry end), with a visible message, instead of staying black until a reload.

### Changed
- **The print waits for each science still.** At a capture pose the print now holds until the operator has stored that still (or 10 s, then continues and logs `capture_missed`), instead of a fixed hold only. Prints with no camera capturing are never held; the existing capture hold still applies as the minimum settle.

## v0.12.1 — 2026-09-23

### Fixed
- **Truncated camera frames are refused, not stored.** A frame whose bottom never arrived over USB (torn rows, then a green band of unfilled data — seen with 20 MP YUY2 through a shared hub) used to pass the blank check and be saved as a science capture. The operator refuses it at every storage point and the browser tries its next grab.
- **Capture failures say why.** A failed science capture names each browser attempt's reason (photo / frame / video, blank or truncated) and the operator fallback's answer, instead of only "503 science capture service is not running".
- **Camera fps limits match the camera's real modes** (e.g. 4K uncompressed tops out at 23 fps), and Camera settings warns when an uncompressed mode needs more USB bandwidth than a shared hub carries.
- **No floating-point noise** in timeline, step and event-log numbers (7.5000000000000036 mm → 7.5 mm).

### Added
- Clicking the console ≠ operator badge explains the mismatch and gives the in-place update command for the operator's OS. The update banner uses the same command (re-running the installer would regenerate the macOS service file and drop its print-timing flags).

## v0.12.0 — 2026-09-23

### Added
- **Camera controls on the Mac.** macOS browsers expose none of a USB camera's controls, so the operator now reads and sets them directly (exposure, gain, brightness, contrast, saturation, hue, sharpness, gamma, white balance, backlight, power-line frequency, focus, zoom), with each control's real range and factory default.
- **Reset camera settings to default.** One button per camera clears the saved capture settings and sliders, returns the browser controls to auto, and (on the Mac) restores the camera's factory settings, reporting anything it couldn't reset.
- **Configure → Prime → Start.** A primed bed now belongs to the plan it was primed for and is used up by a print. The Print tab shows the three steps; START is blocked until the bed is primed and becomes "START ANYWAY…" when it was primed for a different plan or already used.

### Changed
- **Priming page redesign.** Every step is a numbered row of the moves it runs with the targets editable inline; a powder bar (needed vs in the feed) and one status line stay pinned at the top, Back/Next at the bottom.

### Fixed
- Running a priming move right after typing a new target could use the previously saved target; Run now always moves to the value shown.

## v0.11.1 — 2026-09-23

### Added
- **Powder budget before a print.** START checks the powder in the feed against what the print consumes. A short feed is refused with where it would stop ("stops after layer N of M"); a feed whose position can't be verified (not homed since power-on) needs an explicit confirmation. Starting anyway on a short feed stops the print safely when the powder runs out — the run-out guard now counts from the real feed position instead of assuming a full column.
- The Print tab shows a live powder line: enough / short / can't verify (with the reason).

### Fixed
- **Priming fill depth** ("paired to job") now sizes on the print's feed demand + the thick precoats' feed + margin. It used the build's total thickness, which under-fills by about half (the feed rises more than the build drops each layer) — the 2026-09-22 pyramid run ran out at layer ~52 of 184.

## v0.11.0 — 2026-09-23

### Added
- **Data offload:** verified copy or move of runs to an external drive; runs visible and viewable across local + mounted drives; restore a run from a drive back to local.
- **Printing:** opt-in absolute layer seat (no accumulating build-height error); timeline that follows the running step.
- **Pistons:** in-app backlash calibration with live plots, re-measure check, stable recommendation and saved history.
- **Cameras & calibration:** coverage-gated calibration with independent scale validation; automatic camera-center sweep; ignore cameras; Windows camera support.
- **Versioning:** `/api/health` reports the operator's git commit and the status bar always shows it.

### Changed
- Science stills are no longer stored twice when uncalibrated (~36% smaller runs); lighter overview frames; shorter default dwells.
- Alerts float over the page; archived jobs in their own section; 5 mm jog step; numbers without floating-point noise.
- Settings "Unattended science" tab renamed **Camera inventory**; ChArUco presets carry their board parameters into calibration, with the mm/px and bed-extent fields explained.

### Fixed
- Reveal on disk for runs on external drives; capture counts for WebP runs; sidecar lookups for deduplicated captures.
- Ignored cameras (e.g. the built-in FaceTime camera) are hidden everywhere, not just in Settings.
- Generating a large custom ChArUco board no longer overloads and kills the operator.

## v0.10.2 — 2026-09-18

### Fixed
- **Science capture no longer wakes iPhone Continuity Camera.** Browser capture stays bound to the assigned USB device ID, and the unsafe macOS OpenCV/AVFoundation index fallback is blocked because its indexes do not match USB/browser enumeration.
- **Empty captures cannot pass as successful science images.** Browser and operator paths reject black, white, and near-uniform frames before storage and surface a capture failure instead.
- **Camera permission checks never open an unspecified device.** Setup and the overview panel no longer use an unconstrained camera probe that macOS could route to an iPhone.

## v0.10.1 — 2026-09-18

### Fixed
- **Science capture ownership waits for a real frame.** A browser camera stream that opened but never produced decoded pixels used to heartbeat anyway, suppressing the operator fallback and losing that layer's capture. Ownership now begins only after a playable frame exists; a later browser capture failure hands the exact layer/stage back to the operator under a sequence guard.
- **Camera previews handle two identical cameras independently.** The dock live-feed selector has its own saved key and can no longer overwrite the overview role. Studio and Setup panes validate actual video, expose a useful error and retry action, and use lower-bandwidth previews without changing the saved scientific capture mode.
- **Release detection advances to v0.10.1.** The hosted console can now tell a v0.10.0 operator that this backend update is required.

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
