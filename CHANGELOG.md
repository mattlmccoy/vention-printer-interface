# Changelog

Notable changes to the Vention Printer Interface. Versions follow semantic versioning; each entry
corresponds to a tagged merge to `main`.

## v0.21.0 — 2026-10-26

### Added
- **Each calibration run picks its points by held-out accuracy.** The solve now fits three ways and keeps the one that best predicts photos it was not fitted on:
  - every identified point (chessboard and marker corners);
  - the same, minus points the lens fit misses by more than 3 px;
  - chessboard corners only.
  - **How it is scored:** each photo is left out in turn, the calibration is refitted on the others, and the left-out photo's points are predicted. Every method is scored on the same points (all points of the left-out photo), so a method with fewer, cleaner points gets no easier test.
  - **Rule:** the lowest average error among methods that pass the run's limits wins. A method must beat an earlier one by at least 1 µm to replace it; `all` is first.
  - **On the real 2026-10-26 sweep:** all points 32.8 µm average / 98 µm worst; outliers dropped 32.8 / 100 µm; chessboard only 84.8 / 716 µm. Chessboard-only extrapolates poorly to the frame edges from 76 points. Scored on its own points it read 28.4 µm, which is why the scoring set is fixed. All points are kept.
  - **Where to see it:** the run report shows all three with the kept one marked. The saved calibration records `point_method` and the table in its provenance.
- **Frame board preset (10 × 7, 12 mm squares).** Sized to fill the zoomed science-camera view in one placement on the substrate.

### Fixed
- The held-out accuracy check no longer crashes on a photo with fewer than 4 points of the kind being fitted. The real sweep's edge photos have 0–3 chessboard corners.

## v0.20.0 — 2026-10-26

### Added
- **Calibrate with several board placements in one run.** The recoater only moves the board along one axis of the photo, so one placement calibrates a band. At the 2026-10-26 zoom the board covered ~47% of the photo width, and the lens correction over the rest was extrapolated by up to ~5 mm.
  - **How:** after a sweep, press **add a board placement**, move the board to a part of the bed not yet covered (left or right, flat on the same surface), and sweep again. Repeat as needed; the solve combines every placement.
  - **What the solve does:**
    - The lens fit uses every photo of every placement.
    - The bed frame stays on the first placement's capture-pose photo.
    - Each later placement gets its own encoder-shift check, since its board pose differs; the encoder scale is pooled.
    - With two or more placements, the lens's optical centre is also fitted, because it is measurable once the data spans the frame.
  - **Effect on a synthetic lens like the real one** (board over 41% of the frame): the error where only the second placement reached drops from 29 µm with one placement to 13 µm with two.
  - **Where to see it:** the run report lists placements and photos per placement, and the per-photo table shows each photo's placement.

## v0.19.3 — 2026-10-26

### Fixed
- **The calibration inherited the engraved board's scale error, so certified validation failed.** Two independent references showed the calibration's millimetres too large: the recoater encoder said 0.20% (scale ratio 1.0020), and the certified chessboard said 0.27% (scale bias 1.0027). The ChArUco board is engraved about 0.2% small. The self-check could not see it, because it measures the board with its own ruler.
  - **Encoder mm:** the solve now rescales the calibration to the recoater encoder's millimetres.
  - **Shift check:** it is measured with that scale fitted out.
  - **Self-check:** it compares against the board's measured true size.
  - **Limit:** a disagreement of more than 0.5% fails ("measure the board's scale bar with calipers") instead of being absorbed.
  - **Effect on the real 2026-10-26 sweep:** the error on unseen photos dropped from 0.066 to 0.033 mm, the worst point from 0.140 to 0.098 mm, and the encoder-shift check from 0.061 to 0.033 mm.
  - **Recalibrate** to get the corrected scale.
- **Validation now shows why it passed or failed, on the actual chessboard photo.** Every corner is coloured against the target (green / amber / red), with an arrow towards where the calibration says it should be. Corners outside the calibrated area are grey, and the area is outlined. The result also gives the error with scale removed and says whether the miss is mostly scale. Every validation photo and result is stored under its calibration version (`experiments/validations/<version>/`).
- **Validate said "No calibration loaded yet" right after saving one.** Status now reports the saved calibration when the camera service is idle; print stills already used it.

## v0.19.1 — 2026-10-21

### Fixed
- **http://localhost:8020 showed a months-old console.** The operator serves its own copy of the console from `frontend/dist`. That folder is not part of git, so `git pull` + `uv sync` never rebuilt it: the lab Mac served console 0.10.4 (built 2026-09-21) next to a 0.19.0 operator.
  - Each console build now writes `dist/version.json`. The operator serves its copy only when that version matches its own.
  - Otherwise `http://localhost:8020` explains why (both versions) and opens the current console on GitHub Pages.
  - A build without a version stamp counts as out of date.
  - The API is unaffected.

## v0.19.0 — 2026-10-21

### Added
- **Lens-fit residual arrows.**
  - Each board point's residual (direction and size, enlarged) is drawn in the run report's photo map and on the capture-pose photo.
  - Arrows lined up in one direction show a systematic misfit; scattered ones show noise.
  - On a rendered board they already show marker corners biased outward (sub-pixel refinement is built for chessboard X-corners, not a marker's L-corner).
- **Fine board preset for 20 MP stills:** "fine — 12×12, 5 mm" (3.75 mm markers, DICT_4X4_100).
  - 121 chessboard corners instead of the 4×4 board's 9, in a 60 mm pattern that fits the 98.5 mm round cut.
  - Chessboard corners are the accurate kind (OpenCV ChArUco tutorial).
- **The last sweep's photos are kept** on this computer, outside Dropbox (`~/.vpi-cache/autocal_last`, override with `VPI_AUTOCAL_PHOTO_DIR`).
  - Overwritten by the next run, about 500 MB at 20 MP.
  - Before this, no calibration photo was stored anywhere.
- **Compare detection methods on the stored photos** (Calibrate page, after a solve). Three ways of finding the points are each measured on photos the fit never saw:
  - as now;
  - marker corners not refined;
  - corners placed through the solved lens.
  - The last two follow the OpenCV ChArUco tutorial. Nothing changes by default until real photos show a win.

### Not changed
- **Single-pass registration of print stills was tried and dropped.** On a ground-truth test it was no sharper (6.341 vs 6.338 grey-level error). At 20 MP it saves 0.17 s per still but costs 1.9 s on the first still and ~56 MB of memory.

## v0.18.0 — 2026-10-21

### Added
- **Overlays on the active calibration image.**
  - **Live view** (Calibrate page, before the sweep and while placing the board for the self-check). The science camera with every identified point drawn on it is refreshed every 0.5 s:
    - green dots = chessboard corners, with their ids;
    - amber dots and outlines = ArUco marker corners;
    - green dashed outline = the area already covered by the sweep photos.
  - The preview is look-only (`POST /api/vision/autocal/preview`, no motion) and pauses while a full-resolution photo is taken.
  - **During the sweep:** each photo shows the same overlay plus the area covered so far.
  - **After the solve:** the capture-pose photo is shown twice:
    - *as photographed*, with the board's square edges drawn where the new calibration predicts them (they should lie exactly on the real edges);
    - *corrected onto the bed* (lens distortion removed), where those edges are straight.
  - Both show the calibrated-area outline (`GET /api/vision/autocal/overlay.png?view=raw|corrected`). The corrected view takes about 0.25 s at 5120×3840.

## v0.17.0 — 2026-10-21

### Added
- **Calibration run report on the Calibrate page.** Every solve shows:
  - each check with its value, its limit and pass/fail (lens fit in mm on the bed, encoder-shift, usable photos, scale, calibrated area);
  - where the lens error sits (chessboard vs marker corners, photo centre vs edge);
  - a map of every board point seen in the photo, with the 9 coverage regions;
  - the calibrated area drawn on the bed;
  - a table of each photo (recoater position, points, chessboard corners, markers).
  The report is saved by the operator, so it survives a reload or restart ("Last run report").
- **Compare with the calibration in use.** The report puts the new run side by side with the saved calibration (photo size, lens fit, encoder shift, scale, area, photos) with a plain verdict: better, worse, mixed, no calibration saved yet, or "the saved calibration does not apply to photos of this size".
- **Solve after a stop.** When a run stops early (a missed position, Stop pressed), its photos are kept. Once at least 5 have the board found, the page offers "solve the N photos taken" instead of starting again. The 23-photo run of 2026-10-21 would have passed this way.

## v0.16.2 — 2026-10-21

### Fixed
- **Automatic calibration stopped at random positions, often the very first ("never starts on the first run").** The console polls the operator every 50 ms, but the operator re-reads the recoater position from the MachineMotion only about every 290 ms. Once the MachineMotion answers "move complete", which it does for a moment from the *previous* move, the operator stops asking. The console counted one cached reading seen on three polls as "three stable readings". About 0.5 s into a move it decided the recoater had stopped, the position check refused the photo, and the run ended. In the real run the move to 403.3 mm was issued at 15:39:52.130 and "complete" was read at .312 and .559 only; the console gave up at about .6, while the recoater did reach 403.3 mm. Now only fresh telemetry samples count (a new operator timestamp). A still position more than 0.15 mm from the target is accepted only after holding for 2 s, so a move that starts late is not mistaken for a finished one, and an axis that really stops short is still reported. The camera-centring sweep uses the same wait.

## v0.16.1 — 2026-10-21

### Fixed
- **Automatic calibration failed at full resolution on a pixel limit that shrinks as photos grow.** The lens-fit limit was 0.5 px. That is 0.034 mm on the bed at 1920×1080 but only 0.013 mm at 5120×3840. The first full-resolution sweep (5120×3840, 24 photos, all 9 regions) failed it at 1.40 px, about 0.036 mm, while every millimetre check passed: encoder-shift 0.056 mm RMS, scale 1.0009, and a calibrated area of about 100 × 62 mm. The lens fit is now judged in millimetres on the bed (RMS px × mm/px at the image centre), with a limit of 0.05 mm matching the ±0.05 mm target. The result shows the mm figure and the pixels it came from, plus where the error sits: chessboard vs marker corners, and photo centre vs middle vs edge. Each solve saves its sweep points to `experiments/.autocal_last_sweep.json`, so a failed run can be diagnosed and re-solved without moving the machine again.
- **You can choose the calibration board on the Calibrate page itself.** The board used to come only from the Calibration board page, so a browser that had never opened that page (like the lab PC's) had no board. Opening that page also silently reset the board to its default, so the only working route was: Calibration board → re-select your board → Calibrate. Now the Calibrate page has a board picker. It lists the shipped presets plus any custom board you generated, starts on the last board used (the small 4×4 when there is none), and remembers your choice in this browser. The Calibration board page saves a board only when you change something there. A wrong square size still cannot pass unnoticed: the encoder scale check fails the run.

## v0.16.0 — 2026-10-21

### Added
- **ChArUco self-check before Save.** After a passing sweep, move or rotate the board anywhere in view and take a self-check photo. Every identified board point is mapped through the new (not yet saved) calibration, and the distances between points are compared with their true distances on the board. The result shows RMS, worst case, scale bias, and how many points were inside and outside the calibrated area. Save opens only when the self-check passes: RMS ≤ 0.1 mm, worst ≤ 0.2 mm, ≥ 12 points inside the area. A new photo or a new solve closes Save again. The result is stored with the calibration. If the board did not move since the sweep, the page says so. This is reused-board evidence and does not clear the "not validated" warning; only the certified chessboard does.

### Fixed
- **Validation failed whenever the certified chessboard ran off the photo.** That board (17×17 corners, 81 mm) is larger than the science camera's ~74 mm view, so the fixed-count detector never found it and every Validate photo was refused. Validation now uses the visible part of the board (any 5×5 corners or more). Known positions come from the corner grid × the caliper-measured pitch, and only corners inside the calibration's area are scored. The result says how many corners were scored and how many were outside. A chessboard entirely outside the area is refused with that reason, never passed on zero corners. An older calibration without a recorded area scores every corner and says the area is unknown.
- **Validate showed only "400 scale validation" when it failed.** The operator's reason (wrong photo size, chessboard not found, outside the calibrated area) is now shown.

## v0.15.0 — 2026-10-21

### Changed
- **Automatic calibration uses the whole ChArUco board.** Each sweep photo now contributes every identified point: the 9 chessboard corners **and** the four corners of every ArUco marker (32 more on the 4×4 board), each with its known board position. The first run calibrated only the middle third of the photo, because the chessboard corners span 32 of the pattern's 64 mm. With the marker corners the calibrated area grows to ≥ 55 mm across the recoater. On synthetic ground truth the mapping error is 0.009 mm RMS (chessboard corners alone: 0.011 mm), and it stays ≤ 0.03 mm when the marker corners are three times noisier. Each sweep photo reports its chessboard and marker counts.
- **Every science still is taken at the Camera-settings resolution**: print stills, calibration photos and validation photos alike. Each still opens the science camera alone and grabs its raw frame (lossless PNG), so the other live views pause for a moment. Before this release, the Mac (with lightweight mode off) took stills from a stream capped at 1080p. **Recalibrate after upgrading** if your science resolution is not 1920×1080. A calibration only applies to photos of its own size, and the Calibrate page warns when they differ.

## v0.14.1 — 2026-10-21

### Fixed
- **Automatic calibration photographed while the recoater was still moving.** The machine keeps reporting "move complete" from the previous move for a few polls after a new move starts, and the console's settle check accepted that: the first real run read positions 0.3–3 mm short of each target (463.6 mm for the 463.3 mm capture pose), so the solve found no capture-pose photo. The console now uses the operator's proven settle rule (the move must register, then three readings within one 0.1 mm count) and refuses a photo when the recoater stopped more than 0.15 mm from the target. The camera-centring sweep had the same bug and is fixed too.

## v0.14.0 — 2026-10-20

### Added
- **One-button science-camera calibration** (Settings → Calibrate). Place the ChArUco board (on the substrate or in the cylinder), press Start, confirm the planned recoater positions, and watch. The science camera rides the recoater, so the console sweeps it across the board inside a safety window you set (default 0–523 mm, remembered), approaching every position from the same side, and takes each still the same way print stills are taken. The operator fits lens distortion and the print-plane mapping at the capture pose (bed +X = increasing recoater mm, origin at the board's first corner) and checks scale against the recoater encoder. Pass needs ≥ 5 usable photos, lens fit ≤ 0.5 px RMS and encoder-shift ≤ 0.1 mm RMS; only a passing run can be saved. The calibration records the board placement and thickness (the board's top face is assumed to be the print plane for now) and only covers the area where corners were seen.

### Fixed
- **The manual calibration could never finish with a board that fills the frame.** Coverage now counts where board corners land, not the board's centre; the manual gate (under Advanced) is ≥ 6 views, ≥ 6 of 9 cells and 2 tilt ranges.

## v0.13.4 — 2026-10-20

### Fixed
- **A calibration is only applied to science stills of the size it was fitted on.** In lightweight camera mode (the Windows PC), Calibrate/Validate photos came from the ≤1080p stream while print stills are raw full-resolution frames, and the operator applied the calibration to every still regardless of size — wrong millimetres with no error, and Validate (same photo path as Calibrate) would still have passed. Now: Calibrate and Validate take their photo with the same full-resolution capture as print stills; a calibration session refuses photos of a second size; validation refuses a photo of another size; a print still of another size is stored but not measured, and its sidecar says why (`calibration.applied`, `skipped_reason`, the real `image_size`). The Calibrate and Validate pages show the photo size and warn when the science camera's resolution no longer matches the calibration.

## v0.13.3 — 2026-10-20

### Changed
- **The small calibration board can be cut round so it fits the build cylinder (~99.2 mm bore), or square.** It used to be cut only as a 96 mm square (135.8 mm across the corners), which can't go into the cylinder. The `small_cylinder` preset now defaults to a 98.5 mm circle (~0.4 mm clear a side after kerf) with the 64 mm pattern centred; the 50 mm scale bar and the label (which names the bar length) sit in the curved gaps, everything at least 1 mm inside the cut. The square cut stays available for sitting the board on the aluminium substrate, closer to the print plane (console: "cut shape: square / round"; API `cut_diameter_mm=0`). Any board can take a round cut; a circle too small for the pattern is refused with the diameter it would need.

## v0.13.2 — 2026-10-20

### Fixed
- **Calibration boards engrave as solid shapes, not a grid of outlines.** Each black area is now one filled shape (outer edge + holes for white bits) instead of one rectangle per marker bit (489 on the 5×7 board, now 39). A DXF board engraved on Trotec Ruby came out as empty outlined boxes because DXF rectangles carry no fill; the DXF now adds a solid hatch per area, and the SVG (filled shapes) is labelled as the recommended laser format. Squares that only touch at a corner stay separate shapes.

### Added
- **Caliper scale bar on calibration boards** (on by default): a 100 mm bar (50 mm on the small board) with 10 mm ticks in the top margin, so the engraved board's true size can be checked.

## v0.13.1 — 2026-09-23

### Fixed
- **The Mac's Recovery volume is no longer offered as an offload drive.** macOS mounts the APFS Recovery volume read-write under `/Volumes`, so it passed the drive filter and showed up next to real SSDs in Offload. Volumes macOS hides from Finder (`dontbrowse`) are now excluded.

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
