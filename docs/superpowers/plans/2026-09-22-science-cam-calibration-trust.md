# Science-cam calibration + trust — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline) or
> subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Automated, trustworthy science-cam calibration: coverage-guided ChArUco geometry,
independent chessboard scale validation (±0.05 mm), Siemens-star optical resolution, and an
automated camera-center sweep — all on the browser getUserMedia path.

**Architecture:** Pure, hardware-free cores in `backend/vention_printer_interface/vision/`
(`coverage`, `validation`, `resolution`, `center_sweep`), adapted by thin API endpoints (browser
image in; controller for the sweep) and React UI (coverage map + finalize gate, tolerance-band
panels, sweep UI). Cores are unit-tested with synthetic inputs; API via the synthetic-board renderer.

**Tech Stack:** Python 3.13 (uv, ruff, mypy, pytest), FastAPI, OpenCV; React + TypeScript (tsc,
node --test, vite).

**Spec:** `docs/superpowers/specs/2026-09-22-science-cam-calibration-validation-design.md`

**Gates (run before every commit):** backend `uv run ruff check . && uv run mypy vention_printer_interface
&& uv run --extra dev python -m pytest -p no:warnings -q`; frontend `npx tsc --noEmit -p . &&
node --experimental-strip-types --test 'src/**/*.test.ts' && VITE_BASE="/vention-printer-interface/" npm run build`.

---

## File Structure
- Create `backend/vention_printer_interface/vision/coverage.py` — coverage grid from detections (pure)
- Create `backend/vention_printer_interface/vision/validation.py` — world-space scale residuals (pure)
- Create `backend/vention_printer_interface/vision/resolution.py` — Siemens-star MTF → lp/mm (pure)
- Create `backend/vention_printer_interface/vision/center_sweep.py` — best overhead pose (pure)
- Modify `backend/vention_printer_interface/api/app.py` — coverage in session; `/vision/validate`;
  center-sweep session endpoints; persist validation on the calibration
- Create tests `backend/tests/test_coverage.py`, `test_validation.py`, `test_resolution.py`,
  `test_center_sweep.py`; extend `backend/tests/test_api_vision.py`
- Modify `frontend/src/components/CalibrationWizard.tsx` (coverage map + gate),
  `frontend/src/components/ValidationPanel.tsx` (tolerance bands), `frontend/src/lib/api.ts`
- Create `frontend/src/lib/tolerance.ts` (+ test) — pass/fail + band helpers (reused by backlash later)
- Create `frontend/src/components/ToleranceBand.tsx` — reusable band chart

---

## PHASE 1 — pure cores (build first, TDD)

### Task 1: coverage.py — grid + tilt coverage
**Files:** Create `backend/vention_printer_interface/vision/coverage.py`; Test `backend/tests/test_coverage.py`

- [ ] **Step 1: failing test**
```python
from vention_printer_interface.vision.coverage import coverage, CoverageState

def _det(cx, cy, tilt):  # minimal stand-in: image centroid (px) + out-of-plane tilt (deg)
    return {"centroid_px": (cx, cy), "tilt_deg": tilt, "image_size": (900, 600)}

def test_enough_requires_all_cells_and_tilt_diversity():
    # one centred, fronto-parallel view: not enough (one cell, one tilt bin)
    st = coverage([_det(450, 300, 0)], grid=(3, 3), tilt_bins=3, min_views=6)
    assert isinstance(st, CoverageState)
    assert st.enough is False and len(st.gaps) > 0
    # nine cells across three tilt bins, >= min_views -> enough, no gaps
    dets = []
    for gx in range(3):
        for gy in range(3):
            dets.append(_det(150 + gx * 300, 100 + gy * 200, [0, 15, 30][(gx + gy) % 3]))
    st2 = coverage(dets, grid=(3, 3), tilt_bins=3, min_views=6)
    assert st2.enough is True and st2.gaps == []
    assert st2.cells_filled == 9 and st2.tilt_bins_filled == 3
```
- [ ] **Step 2:** `uv run --extra dev python -m pytest backend/tests/test_coverage.py -q` → FAIL (module missing)
- [ ] **Step 3: implement** (frozen dataclass `CoverageState{cells_filled:int, tilt_bins_filled:int,
  enough:bool, gaps:list[str], cell_hits:list[list[int]]}`; map centroid→cell via
  `int(cx/width*gx)`, tilt→bin via fixed edges e.g. `[0,10,25,90]`; `enough` = every cell hit AND
  `tilt_bins_filled>=min(tilt_bins,3)` AND `total_views>=min_views`; `gaps` lists empty cells as
  `"r{gy}c{gx}"` plus `"tilt"` when tilt diversity short). Pure, no IO.
- [ ] **Step 4:** pytest → PASS
- [ ] **Step 5:** gates + commit `feat(vision): coverage grid for calibration capture guidance`

### Task 2: validation.py — world-space scale residuals
**Files:** Create `backend/vention_printer_interface/vision/validation.py`; Test `backend/tests/test_validation.py`
- [ ] **Step 1: failing test**
```python
import math
from vention_printer_interface.vision.validation import scale_residuals, ScaleResult

def _grid(square_mm, nx, ny, scale=1.0, shear=0.0):
    pts = []
    for j in range(ny):
        for i in range(nx):
            x = i * square_mm * scale
            y = j * square_mm + shear * x
            pts.append((x, y))
    return pts, (nx, ny)

def test_exact_grid_has_near_zero_error():
    pts, dims = _grid(5.0, 6, 5)
    r = scale_residuals(pts, dims, square_mm=5.0)
    assert isinstance(r, ScaleResult)
    assert r.max < 1e-6 and r.mean < 1e-6
    assert r.passed(0.05) is True

def test_scaled_grid_fails_tolerance():
    pts, dims = _grid(5.0, 6, 5, scale=1.02)  # 2% too wide -> 0.1 mm at 5 mm
    r = scale_residuals(pts, dims, square_mm=5.0)
    assert r.max > 0.05 and r.passed(0.05) is False
```
- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3: implement** (`ScaleResult{mean,max,rms,residuals_mm:list[float]}` + `passed(t)`=max<=t;
  measure adjacent horizontal + vertical corner spacings from the (nx,ny) grid of world-mm points,
  residual = spacing − square_mm; robust to point order by indexing `pts[j*nx+i]`).
- [ ] **Step 4:** PASS  — [ ] **Step 5:** gates + commit `feat(vision): world-space scale residuals`

### Task 3: resolution.py — Siemens-star MTF → lp/mm
**Files:** Create `backend/vention_printer_interface/vision/resolution.py`; Test `backend/tests/test_resolution.py`
- [ ] **Step 1: failing test**
```python
from vention_printer_interface.vision.resolution import siemens_resolution, ResolutionResult

def test_contrast_crossings_give_expected_lpmm():
    # contrast falls monotonically as radius shrinks (freq rises). radii in px, contrast 0..1.
    radii = [200, 160, 120, 90, 60, 40, 25]
    contrast = [0.95, 0.9, 0.8, 0.6, 0.4, 0.2, 0.08]
    r = siemens_resolution(radii, contrast, n_spokes=72, mm_per_px=0.01)
    assert isinstance(r, ResolutionResult)
    # f = n_spokes/(2*pi*radius*mm_per_px); higher freq at smaller radius
    assert r.lpmm_at[0.5] < r.lpmm_at[0.1]         # MTF50 freq below MTF10 freq
    assert r.passed(target_lpmm=r.lpmm_at[0.1] - 1) is True
    assert r.passed(target_lpmm=r.lpmm_at[0.1] + 5) is False

def test_low_contrast_never_reaches_target():
    r = siemens_resolution([100, 50], [0.05, 0.02], n_spokes=72, mm_per_px=0.01)
    assert r.passed(target_lpmm=10) is False
```
- [ ] **Step 2:** FAIL
- [ ] **Step 3: implement** (`ResolutionResult{lpmm_at:dict[float,float], curve:list[tuple[freq,contrast]]}`
  + `passed(target)`=lpmm_at.get(0.1,0)>=target; `freq(r)=n_spokes/(2*pi*r*mm_per_px)`; sort by freq;
  linear-interpolate the freq where contrast crosses each MTF threshold; if never crossed, lpmm_at=0).
- [ ] **Step 4:** PASS — [ ] **Step 5:** gates + commit `feat(vision): Siemens-star MTF resolution`

### Task 4: center_sweep.py — best overhead pose
**Files:** Create `backend/vention_printer_interface/vision/center_sweep.py`; Test `backend/tests/test_center_sweep.py`
- [ ] **Step 1: failing test**
```python
from vention_printer_interface.vision.center_sweep import best_center_pose, CenterResult

def test_picks_the_min_offset_pose_with_subsample():
    # V-shaped offset vs recoater mm, minimum near 12.0
    samples = [(8.0, 30.0), (10.0, 12.0), (12.0, 1.0), (14.0, 13.0), (16.0, 31.0)]
    r = best_center_pose(samples, start_pose_mm=8.0)
    assert isinstance(r, CenterResult)
    assert 11.5 <= r.pose_mm <= 12.5 and r.improved is True

def test_no_improvement_when_flat():
    samples = [(8.0, 5.0), (10.0, 5.0), (12.0, 5.0)]
    r = best_center_pose(samples, start_pose_mm=10.0)
    assert r.improved is False  # start already as good as any
```
- [ ] **Step 2:** FAIL
- [ ] **Step 3: implement** (`CenterResult{pose_mm,offset_px,improved}`; pick min-offset sample; if it
  has both neighbours, refine with a 3-point parabola vertex; `improved`=best offset < offset at the
  sample nearest `start_pose_mm` by more than a small epsilon).
- [ ] **Step 4:** PASS — [ ] **Step 5:** gates + commit `feat(vision): center-sweep pose selection`

---

## PHASE 2 — API (mirror #87 upload + backlash-cal session)

### Task 5: coverage in the calibration session
- [ ] Modify `_accumulate_calibration_view` (app.py) to also compute a lightweight detection descriptor
  (centroid_px from `detection.image_points` mean, tilt_deg from the view homography vs fronto-parallel)
  and store it in `app.state.calib_session_cov`. `GET /api/vision/calibrate/session` returns
  `coverage = coverage(descriptors).__dict__`. Test in `test_api_vision.py`: after N synthetic
  `_warped_charuco_frames` uploads, `session.coverage.enough` becomes true; finalize still works.
- [ ] gates + commit `feat(vision): report calibration coverage in the session`

### Task 6: `POST /api/vision/validate` (scale + resolution, browser image)
- [ ] Body: raw image + query `target=scale|resolution`, `square_mm`/`n_spokes`/`star_diameter_mm`.
  scale: `findChessboardCornersSB` → undistort+homography via the active calibration → world-mm →
  `scale_residuals`. resolution: locate star centre (brightest-symmetric / provided ROI), sample
  contrast by radius (std/mean of a ring), `siemens_resolution` (mm_per_px from calibration or
  `star_diameter_mm`). Returns the result dict + `passed`. No server camera (400 if no active
  calibration). Tests: synthetic chessboard passes ~0; a synthetic Siemens star returns a finite
  lp/mm; blank → `{ok:false}`. Reuses helpers; keep the opencv extraction thin over the pure cores.
- [ ] gates + commit `fix(vision): browser-image validation (scale + resolution)`

### Task 7: persist validation on the calibration + analysis warning
- [ ] On a passing/failing validate, write `validation` onto the stored calibration record
  (`.vision_calibration.json`), keyed by the active version. Dimensional analysis surfaces a
  `calibration_unvalidated` warning when the active calibration has no passing scale validation
  (advisory; distinct from ok — no false green). Test: validate → reload calibration shows the
  stored result; analysis warning present/absent accordingly.
- [ ] gates + commit `feat(vision): persist validation trust on the calibration`

### Task 8: center-sweep session (guarded motion routine)
- [ ] Mirror the backlash-cal session (`backlash_routine.py`): `POST /api/vision/center-sweep/session`
  {range_mm, step_mm}, `GET …`, `POST …/cancel`, `POST …/apply`. Browser-driven frames (Option 1):
  the endpoint returns the sweep plan (recoater positions); the browser steps the recoater via the
  move API, captures a science frame per step, POSTs each to `POST /api/vision/center-sweep/sample`
  (image + recoater_mm) which detects the piston circle (HoughCircles) and records the offset; a
  final `best` uses `best_center_pose`; `apply` writes `capture_recoater_mm` via print-settings.
  Guards: connected/armed/referenced/heater-off/not-printing. Test the guard + the sample→best flow
  with synthetic circle images; the guard refusal like `test_api_backlash`.
- [ ] gates + commit `feat(vision): automated camera-center sweep`

---

## PHASE 3 — frontend

### Task 9: tolerance helpers + band chart
- [ ] Create `frontend/src/lib/tolerance.ts` + `tolerance.test.ts`: `bandStatus(value, band) ->
  "pass"|"fail"`, `bandFraction(...)` for plotting. Unit-tested. Create `ToleranceBand.tsx` (SVG:
  shaded band, points/curve, PASS/FAIL chip). tsc + tests + build.
- [ ] commit `feat(runs): reusable tolerance-band chart`

### Task 10: coverage map + finalize gate (CalibrationWizard)
- [ ] Render the 3×3 (× tilt) coverage grid from `session.coverage`; "confirm placed → capture"
  stays; **finalize disabled** until `coverage.enough`; show gaps ("need a view top-left / more
  tilt"). tsc + build. commit `feat(calibration): coverage map + finalize gate`

### Task 11: ValidationPanel tolerance bands (scale + resolution)
- [ ] Two capture buttons (chessboard → scale band vs ±0.05 mm; Siemens → resolution band vs target
  lp/mm), both browser getUserMedia (reuse `captureScienceStillOnce`), POST to `/vision/validate`,
  render `ToleranceBand` + PASS/FAIL + override. tsc + build. commit `feat(validation): scale + resolution bands`

### Task 12: center-sweep UI (Settings → capture pose)
- [ ] A "Find overhead centre" button: run the sweep (step recoater + capture per step), show progress
  + before/after offset, Apply the pose. tsc + build. commit `feat(settings): automated camera-center sweep`

---

## Self-review (done)
- Spec coverage: geometry+coverage (T1,T5,T10), scale validation (T2,T6,T7,T11), resolution
  (T3,T6,T11), center-sweep (T4,T8,T12), browser path (T6,T8,T11), persistence/warning (T7),
  tolerance bands (T9). All covered.
- No placeholders in the pure-core tasks (full test + impl). Phase 2/3 tasks are concrete (endpoints,
  files, mirrored patterns) — expand each into red/green steps at execution time.
- Types consistent: CoverageState/ScaleResult/ResolutionResult/CenterResult names reused throughout.
