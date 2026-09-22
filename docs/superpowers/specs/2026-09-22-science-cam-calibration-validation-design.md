# Science-cam calibration + trust — design (Spec A)

**Date:** 2026-09-22
**Status:** approved (brainstorm), ready to plan
**Scope:** Make the science-camera calibration automated and *trustworthy*. Camera-side only.
Printed-Siemens-star **process** resolution (min printable feature) is a separate follow-up (Spec B)
that reuses the analyzer built here.

## Goal
The operator can produce a science-cam calibration they can trust to ~**±0.05 mm** for dimensional
work, with three independent, automated checks, each shown as a factory-style tolerance band:

1. **Geometry** — ChArUco intrinsics + bed homography, with coverage-guided capture and an
   acceptance gate.
2. **Independent scale validation** — a *different* board (chessboard) measured in world-mm vs its
   known square size → mean/max error in mm vs the ±0.05 mm band (advisory).
3. **Optical resolution** — a Siemens star imaged and analyzed (contrast-vs-radius blur circle) →
   limiting resolution in lp/mm vs a target (advisory).

Plus an **automated camera-center sweep** that finds the recoater-gantry pose putting the build
piston truly overhead (auto-sets `capture_recoater_mm`).

All three run on the **browser getUserMedia capture path** (post-#87), never a server cv2 grab.

## Non-goals
- Printed process-resolution / min-printable-feature (Spec B).
- Color/greyscale calibration (the QA target's color chart) — not needed now.
- Auto-triggering frame capture: manual "confirm placed → capture" is acceptable; automation is in
  guidance, validation, analysis, and the center sweep.

## Success criteria
- A calibration finalize is **blocked** until coverage (spatial × tilt) is met; reports RMS + reproj.
- Chessboard validation returns mean/max/RMS **mm** error and a PASS/FAIL vs ±0.05 mm (override
  allowed), stored with the calibration version.
- Siemens-star validation returns lp/mm at MTF50/MTF10 + an MTF curve, PASS/FAIL vs a target lp/mm,
  stored with the calibration.
- Camera-center sweep sets `capture_recoater_mm` to the piston-centered pose, with a before/after
  offset report; guarded like a motion routine, cancelable.
- Dimensional analysis **warns** when the active calibration has no passing geometry validation.

## Architecture

Small, isolated, independently testable units. Pure cores have **no IO** and are unit-tested with
synthetic inputs; the API layer adapts the browser image + the controller.

### Pure cores (backend `vision/`, no hardware)
- **`coverage.py`** — `coverage(detections, grid=(3,3), tilt_bins=3) -> CoverageState{cells_filled,
  tilt_bins_filled, enough, gaps}`. Each ChArUco `BoardDetection` contributes a frame cell (from its
  image-space centroid/bbox) and a tilt bin (from the board's perspective skew / homography-implied
  out-of-plane angle). `enough` = every cell hit in ≥1 tilt bin AND ≥ min tilt-bin diversity AND ≥
  min view count. Tested: synthetic detections fill the grid; gaps reported; `enough` flips only when
  covered.
- **`validation.py`** — `scale_residuals(world_pts_mm, board_dims, square_mm) -> ScaleResult{mean,
  max, rms, residuals_mm}`. From chessboard corners already mapped to world-mm (undistort + bed
  homography, done in the API using the *current* calibration), compute adjacent-corner spacings and
  their signed residuals vs `square_mm`. `passed(target_mm)` = max ≤ target. Tested: exact grid → ~0;
  a scaled/sheared grid → fails; noise within tolerance passes.
- **`resolution.py`** — `siemens_resolution(contrast_by_radius, n_spokes, mm_per_px,
  mtf=(0.5,0.1)) -> ResolutionResult{lpmm_at, curve}`. Given contrast (modulation) sampled at each
  radius (px) and the star's spoke count, convert radius→spatial frequency `f(r)=n_spokes/(2π·r·
  mm_per_px)` lp/mm, build the MTF curve, and interpolate the frequency at each MTF threshold.
  `passed(target_lpmm)` = lpmm_at_mtf10 ≥ target. Tested: a synthetic monotonic contrast profile
  yields the expected crossings; a low-contrast profile fails the target. (The IMAGE→contrast_by_
  radius extraction — center find + circular sampling — lives in the API/opencv adapter, thin.)
- **`center_sweep.py`** — `best_center_pose(samples) -> CenterResult{pose_mm, offset_px, improved}`
  where `samples = [(recoater_mm, piston_center_offset_px)]`. Pure selection of the pose minimizing
  the piston-center-to-image-center offset (with a parabola fit for sub-step precision). Tested:
  synthetic V-shaped offset curve → picks the vertex.

### API (browser-image + controller adapters)
- **`POST /api/vision/calibrate/capture-upload`** — unchanged (#87): accumulate one ChArUco view
  from an uploaded browser frame. Now also returns the **coverage** summary (via `coverage.py`).
- **`GET /api/vision/calibrate/session`** — includes `coverage` so the wizard can render the map and
  gate finalize.
- **`POST /api/vision/validate`** — body: uploaded image + `{target: "scale"|"resolution", square_mm?
  , n_spokes?, star_diameter_mm?}`. For `scale`: detect chessboard (subpixel), map to world via the
  current calibration, run `scale_residuals`. For `resolution`: find the star, sample contrast-by-
  radius, run `siemens_resolution`. Returns the tolerance-band result; **no server camera** (browser
  frame). This settles the #87 Validate-panel frame-source question.
- **`POST /api/vision/center-sweep/session`, `GET …`, `POST …/cancel`, `POST …/apply`** — a guarded
  server-side routine (mirrors the backlash-cal session): sweeps the recoater over `capture_recoater_
  mm ± range`, at each step grabs a science frame (browser is not in the loop here — this is an
  overhead-pose routine using the assigned camera via the browser capture request, OR the server
  frame if available; see Open questions), detects the piston circle, records offset; on finish
  reports the best pose; `apply` writes `capture_recoater_mm`.
- **Persist trust:** extend the stored calibration record with `validation: {scale:{mean,max,rms,
  passed,date,square_mm}, resolution:{lpmm_mtf50,lpmm_mtf10,passed,target,date}}`. Version unchanged
  key; validation attaches to the active version.

### Frontend
- **CalibrationWizard** — a **live coverage map** (3×3 × tilt bins) fed by the session `coverage`;
  "confirm board placed → capture" stays manual; **finalize disabled until `coverage.enough`**;
  finalize shows RMS/reproj.
- **ValidationPanel** — capture the chessboard (browser) → scale tolerance band (mm vs ±0.05); capture
  the Siemens star (browser) → resolution tolerance band (lp/mm vs target). Both stored + shown with
  PASS/FAIL and an override.
- **Camera-center sweep** — a button in Settings → capture pose: run the sweep, show progress + the
  before/after offset, Apply the found pose.
- **Tolerance-band chart** — a small reusable client-side chart: measured points/curve vs a shaded
  band + PASS/FAIL. Reused by scale, resolution (and later the queued backlash-cal plots).

## Data flow
1. **Calibrate:** session start → (confirm placed → capture ChArUco view)×N, coverage fills live →
   `enough` → finalize → calibration vN (intrinsics + homography + RMS/reproj).
2. **Validate scale:** place chessboard at bed plane → capture → world-map → residuals mm → band +
   PASS/FAIL → stored on vN.
3. **Validate resolution:** place Siemens star → capture → contrast-by-radius → lp/mm → band +
   PASS/FAIL → stored on vN.
4. **Center sweep:** run routine → best pose → apply `capture_recoater_mm`.
5. **Analysis:** uses vN; warns if vN has no passing scale validation.

## Error handling
- Board/star not detected → `{ok:false, reason}`, never a 500 (mirror existing capture-upload).
- Center sweep guarded (connected/armed/referenced/heater-off/not-printing); cancel returns the
  recoater to its start pose; refuses if a print/routine runs.
- Validation with no active calibration → 400 "calibrate first".
- Every "unknown/failed" is visually distinct from a pass (no false-green; data-contract rule).

## Testing
- Pure cores unit-tested with synthetic inputs (coverage grid, scale residuals, siemens crossings,
  center vertex).
- API tests via the existing synthetic-board renderer (ChArUco) + a synthetic chessboard and a
  synthetic Siemens star image; center-sweep against the simulated backend + a stub circle detector.
- Frontend: pure helpers for the tolerance-band pass/fail + coverage rendering unit-tested; UI via
  tsc + build.

## Open questions (resolve in planning)
- **Center-sweep frame source:** the science cam is browser-opened; a *server-driven* sweep needs
  frames while moving. Option 1: drive the sweep from the browser (JS steps the recoater via the move
  API, grabs a frame each step, posts for circle detection) — keeps the getUserMedia source, no server
  camera. Option 2: server routine using a server frame source when available. **Lean Option 1** (no
  new server-camera dependency; consistent with #87). Confirm in the plan.
- **Siemens star params:** spoke count + physical diameter are board-specific; store as a target
  spec like the ChArUco board spec.
- **Tilt-bin estimate:** derive out-of-plane angle from the per-view homography vs a fronto-parallel
  reference; exact bucketing thresholds tuned during implementation.

## Decomposition
- **Spec A (this):** camera calibration + coverage + chessboard scale validation + Siemens optical
  resolution + camera-center sweep. Delivers `resolution.py`.
- **Spec B (follow-up):** printed Siemens star → process resolution (min printable feature) in the
  gold-standard geometry, reusing `resolution.py`.
