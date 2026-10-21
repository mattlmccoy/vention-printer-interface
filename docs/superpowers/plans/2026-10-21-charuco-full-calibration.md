# Whole-Board ChArUco Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The calibration uses every identified ChArUco point and runs at full resolution. It is checked by a ChArUco self-check before Save, and by a partly visible certified chessboard. The page shows it live.

**Architecture:**
- Point detection lives in one new pure module (`vision/charuco_points.py`). The automatic calibration, the self-check and the live preview all use it.
- The self-check is a pure scorer plus one session route that gates Save.
- Certified-chessboard validation switches to `findChessboardCornersSBWithMeta(CALIB_CB_LARGER)` and filters to the calibrated area.
- The live views are two new session routes (preview detection, overlay image) and panel components.
- It ships as three PRs: A (Tasks 1–3), B (Tasks 4–6) and C (Tasks 7–9).

**Tech Stack:** Python 3.11+, FastAPI, OpenCV 5 (`cv2.aruco`, `findChessboardCornersSBWithMeta`), numpy. React/TS (vite, node --test).

**Spec:** `docs/superpowers/specs/2026-10-21-charuco-full-calibration-design.md`

## Global Constraints

- **Every point carries an identity.** ChArUco chessboard corners keep their id (0..N−1). Marker corners get id `1000 + 4*marker_id + k` (k = corner 0..3, in `getObjPoints` order). Board coordinates come only from the cv2 board (`getChessboardCorners()`, `getObjPoints()`/`getIds()`). Both share one frame (verified: marker 0 = x 18–30 mm, y 2–14 mm).
- **Marker corners are refined** with `cv2.cornerSubPix` (win 5×5, criteria EPS+COUNT 30/0.01) before use.
- **Trust:** only the certified chessboard clears `calibration_validation_warning`. The ChArUco self-check is stored in provenance and never clears it.
- **Self-check gate:**
  - It scores the session's PENDING solve.
  - Save → 409 unless the latest self-check for the current solve passed.
  - A new solve or a new sweep sample invalidates the self-check.
- **Self-check pass:** pairwise-distance RMS ≤ 0.1 mm, worst ≤ 0.2 mm, ≥ 12 points inside the calibrated area. Tune after the first run.
- **Science stills:** prints, calibration, validation and self-check stills all use the full-resolution capture path (`fullResScienceStill`) at the Camera-settings resolution, on every machine.
- **Live preview** is look-only (no motion route touched). Frames are ≤ 1280 px wide.
- **Style:** ruff ≤ 100 cols, mypy clean, fixtures from cv2-rendered boards/projections only.
- **Versions:** PR A 0.15.0, PR B 0.16.0, PR C 0.17.0. Each bumps pyproject, `__init__`, uv.lock, CHANGELOG.md and changelog.ts.

## Review Focus

1. **A view with markers but no chessboard corners** (board mostly out of frame) still contributes its marker points and never crashes the solve. Test `test_marker_only_view_is_used` (Task 1).
2. **Self-check photos taken without moving the board** (identical to a sweep view) still score, but the report says the board did not move. Test `test_self_check_flags_an_unmoved_board` (Task 4).
3. **Certified chessboard entirely outside the calibrated area:** 400 with "no chessboard corners inside the calibrated area", never a pass on 0 points. Test `test_validation_with_no_points_in_area_is_refused` (Task 6).
4. **Legacy calibration without `valid_region_mm`:** validation still scores and reports "calibrated area unknown (older calibration)". Test `test_legacy_calibration_scores_without_area_filter` (Task 6).
5. **Overlay requested before a solve:** 409, not a 500 or a blank image. Test `test_overlay_before_solve_is_409` (Task 9).

---

## PR A — whole board + full resolution

### Task 1: Identified board points (pure)

**Files:** Create `backend/vention_printer_interface/vision/charuco_points.py`. Test `backend/tests/test_charuco_points.py`.

**Interfaces:**
- Produces `BoardPoints(image_points: np.ndarray Nx2, object_points: np.ndarray Nx3, ids: np.ndarray Nx1 int, kinds: np.ndarray N of "corner"|"marker", markers_px: list[np.ndarray 4x2])`, a frozen dataclass.
- Produces `detect_board_points(image: np.ndarray, spec: BoardSpec) -> BoardPoints | None`. Returns None when nothing is found.
- Produces `MARKER_ID_BASE = 1000`.

- [ ] **Step 1: Failing tests.** They use the image `aruco.CharucoBoard((4,4),16,12,DICT_4X4_50).generateImage((640,640), marginSize=40)` (10 px/mm, 40 px offset).
  - `test_full_board_gives_9_corners_and_32_marker_points`: 41 points, unique ids, 9 kinds "corner".
  - `test_points_land_where_the_board_says`: every point satisfies image ≈ 40 + 10·object mm within 0.3 px after refinement.
  - `test_marker_corner_ids_encode_marker_and_corner`: the point with id 1000+4·0+0 has object (18, 2).
  - `test_half_board_still_identified`: on `img[:, 300:]`, ≥ 16 marker points and the ids are a subset of the full set.
  - `test_marker_only_view_is_used` (Review Focus 1): crop so that only one marker row shows → 0 corners, ≥ 4 marker points, not None.
  - `test_blank_image_is_none`.
- [ ] **Step 2:** `cd backend && uv run pytest -q tests/test_charuco_points.py` → FAIL (module missing).
- [ ] **Step 3: Implement.**
  - Run `CharucoDetector(board).detectBoard`.
  - Chessboard corners: `board.getChessboardCorners()[id]`.
  - Marker corners: from a `{id: getObjPoints()[i]}` map, refined with `cornerSubPix` on a grey image.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(calibration): identify every ChArUco point, incl. marker corners`.

### Task 2: Automatic calibration uses all points

**Files:**
- Modify `backend/vention_printer_interface/api/autocal_routes.py` (`autocal_sample` uses `detect_board_points`; `corners` = all points, plus `chessboard_corners` and `marker_points` counts).
- Modify `backend/tests/autocal_synth.py` (adds `with_markers: bool = True`, which projects marker corners with 0.15 px noise and ids per Global Constraints).

**Tests:** `backend/tests/test_autocal_solve.py`, `backend/tests/test_api_autocal.py`.

**Interfaces:**
- Consumes `detect_board_points` (Task 1).
- `solve_autocal` is unchanged: the views simply carry more points, and the origin stays at ChArUco corner id 0.

- [ ] **Step 1: Failing tests.**
  - `test_marker_points_widen_the_calibrated_area`: with markers, the `valid_region_mm` extent across the recoater is ≥ 55 mm (it was ~32 mm).
  - `test_marker_points_keep_mapping_accuracy`: all-view mapping RMS ≤ 0.02 mm with markers.
  - API `test_sample_counts_corners_and_marker_points`: a full-board crop returns `corners == 41`, `chessboard_corners == 9`, `marker_points == 32`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `MIN_CORNERS` stays at 4 points per view.
- [ ] **Step 4:** Run these plus the whole backend suite → PASS.
- [ ] **Step 5:** Commit `feat(autocal): use marker corners — calibrate the whole board`.

### Task 3: Full-resolution science stills everywhere

**Files:**
- Modify `frontend/src/lib/science_still.ts`: `captureScienceStillOnce` always uses `fullResScienceStill`.
- Modify `frontend/src/components/ScienceCaptureClient.tsx`: the print client always probes and releases, and takes each still via `fullResScienceStill`.
- Add a pure helper `scienceStillPath(): "full-res"` in `frontend/src/lib/camera_mode.ts`, with a test.

**Interfaces:** Consumes the existing `fullResScienceStill(deviceId, resolution, video)`.

- [ ] **Step 1:** Failing test `scienceStillPath is full-res regardless of lightweight mode` in `camera_mode.test.ts`.
- [ ] **Step 2:** `cd frontend && node --experimental-strip-types --test src/lib/camera_mode.test.ts` → FAIL.
- [ ] **Step 3:** Implement and wire both call sites to it.
- [ ] **Step 4:** All node tests pass and the vite build passes. The capture itself is DOM-bound and verified on hardware: the Calibrate photo size must equal the Camera-settings resolution.
- [ ] **Step 5:** Bump to 0.15.0 with changelogs. Run the gates. Commit `feat(cameras): every science still at full resolution`. Open PR A.

## PR B — ChArUco self-check gate + partial certified chessboard

### Task 4: Self-check scorer (pure)

**Files:** Create `backend/vention_printer_interface/vision/charuco_selfcheck.py`. Test `backend/tests/test_charuco_selfcheck.py`.

**Interfaces:**
- Produces `SelfCheck(rms_mm: float, worst_mm: float, scale_bias: float, n_used: int, n_outside: int, moved: bool, passed: bool, reasons: list[str])`.
- Produces `score_self_check(views: list[BoardPoints], to_bed: Callable[[np.ndarray], np.ndarray], region_mm: list[tuple[float, float]] | None, sweep_poses_px: list[np.ndarray] = ()) -> SelfCheck`.
  - `to_bed` maps image px to bed mm (undistort + H).
  - Scoring: for every pair of in-region points in a view, |mapped distance − true board distance|.
  - `scale_bias` = Σ mapped / Σ true distances.
  - `moved` is False when every view's points lie within 2 px of some sweep photo's points.
  - Thresholds and constants: `SELF_RMS_MM = 0.1`, `SELF_WORST_MM = 0.2`, `SELF_MIN_POINTS = 12`.

- [ ] **Step 1: Failing tests.** They use the synthetic projection, with the board rotated 25° and shifted 10 mm.
  - `test_good_calibration_passes`.
  - `test_scale_error_fails_and_reports_bias`: a `to_bed` scaled ×1.01 → `scale_bias` ≈ 1.01 and fails on RMS.
  - `test_points_outside_area_are_not_counted`: n_outside > 0 and they are not used.
  - `test_too_few_points_fails_with_reason`.
  - `test_self_check_flags_an_unmoved_board` (Review Focus 2).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(calibration): ChArUco self-check scorer`.

### Task 5: Self-check route gates Save + panel step

**Files:**
- Modify `api/autocal_routes.py`: add `POST /api/vision/autocal/selfcheck` (raw image), returning `SelfCheck` as JSON. It is stored in the session and cleared by a new sample or a new solve. `save` returns 409 "run the self-check first" unless it passed, and adds `self_check` to provenance.
- Modify `frontend/src/lib/api.ts` and `frontend/src/components/AutoCalibrationPanel.tsx`. After a passing solve the panel says "Move or rotate the board, then take a self-check photo", followed by a [self-check] button that uses `captureScienceStillOnce`. It shows the result. Save is enabled only when it passed.

**Tests:** `backend/tests/test_api_autocal.py`.

- [ ] **Step 1: Failing tests.**
  - `test_save_requires_a_passing_self_check` (409 before; 200 after a passing self-check on a moved crop).
  - `test_failed_self_check_keeps_save_closed`.
  - `test_new_solve_clears_the_self_check`.
  - `test_self_check_is_stored_in_provenance`.
  - Update `test_full_run_passes_and_saves…` to run a self-check before Save.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Backend suite, node tests and build pass.
- [ ] **Step 5:** Commit `feat(autocal): ChArUco self-check gates Save`.

### Task 6: Certified chessboard: partly visible, sized, scored in the calibrated area

**Files:**
- Modify `backend/vention_printer_interface/vision/registration.py`: add `detect_chessboard_partial(gray, min_cols=5, min_rows=5) -> tuple[np.ndarray Nx2, np.ndarray Nx2 grid (col,row)] | None` using `findChessboardCornersSBWithMeta(..., CALIB_CB_LARGER | CALIB_CB_EXHAUSTIVE | CALIB_CB_ACCURACY)`.
- Modify `api/app.py`:
  - `_score_checkerboard_mm` uses it.
  - Object points come from the grid indices × pitch.
  - Points are filtered to `calib.provenance["valid_region_mm"]` when present.
  - The result adds `n_points`, `n_outside`, `area_known`.
  - It is a 400 when 0 points fall inside the area.
- Modify `frontend/src/components/ValidationPanel.tsx`: inputs for pitch (the certified, caliper-measured value). Detection no longer needs the 17×17 count. Show n_used / n_outside.

**Tests:** `backend/tests/test_calibration_size_guard.py` patterns, plus a new `backend/tests/test_validate_partial.py`.

- [ ] **Step 1: Failing tests.**
  - `test_partial_chessboard_is_found_where_the_classic_detector_fails`: crop of an 18×18-square board; classic (17,17) fails; partial finds ≥ 100 corners.
  - `test_validation_scores_a_partly_visible_board`.
  - `test_validation_with_no_points_in_area_is_refused` (Review Focus 3).
  - `test_legacy_calibration_scores_without_area_filter` (Review Focus 4).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Suite, build and node tests pass.
- [ ] **Step 5:** Bump to 0.16.0, gates, commit `feat(validation): partly visible certified chessboard, scored in the calibrated area`. Open PR B.

## PR C — live views

### Task 7: Live preview detection route + overlay

**Files:**
- Modify `api/autocal_routes.py`: add `POST /api/vision/autocal/preview` (raw image ≤ 1280 px wide, any size), returning `{found, image_size, points: [{x, y, id, kind}], markers: [[[x, y] × 4], …]}`. It is stateless and does not need a session (it uses the board in the request query: squares_x, squares_y, square_mm, marker_mm, dict).
- Add `frontend/src/components/CalibrationLivePreview.tsx`:
  - Opens the science camera at ≤ 1280×720 and posts a frame every 500 ms.
  - Draws the points (green = chessboard corner with id label, amber = marker corner) and the marker outlines.
  - Shows "board found: N points" or "board not found".
  - Pauses while a sweep runs or a still is being taken (camera bus).
- Add a pure helper `scaleOverlay(points, from, to)` in `frontend/src/lib/autocal.ts`, with a test.

**Tests:** `backend/tests/test_api_autocal.py` (`test_preview_returns_identified_points_without_a_session`), plus the node test for `scaleOverlay`.

- [ ] Steps: failing tests → FAIL → implement → PASS. Run the build. Browser check: the preview renders and shows "board not found" with no camera.
- [ ] Commit `feat(autocal): live preview with identified ChArUco points`.

### Task 8: Live sweep view

**Files:** Modify `AutoCalibrationPanel.tsx`:
- The latest photo is shown large, with its points drawn the same way as the preview.
- A frame-space map of every point so far is shown, with their convex hull.
- The coverage cells come from the session.
- The bed-mm calibrated area is drawn after the solve, from `valid_region_mm`.

**Ruling recorded:** a bed-mm area only exists after the solve, so during the sweep the growing area is shown in photo space.

- [ ] Add a pure helper `convexHull(points)` in `lib/autocal.ts`, with a test.
- [ ] Build, then a browser check.
- [ ] Commit.

### Task 9: Distortion overlay route + panel

**Files:**
- Modify `api/autocal_routes.py`. The session keeps the decoded image of the sample nearest the capture pose (memory only). Add `GET /api/vision/autocal/overlay.png?view=raw|corrected`:
  - `raw` draws a 10 mm bed grid projected into the photo, plus the calibrated-area outline.
  - `corrected` = `undistort_image` + `warp_to_bed` with the pending result, a 10 mm straight grid and the area outline.
  - It is a 409 before a solve.
- Modify `AutoCalibrationPanel.tsx`: after the solve, show raw and corrected side by side.

**Tests:**
- `test_overlay_before_solve_is_409` (Review Focus 5).
- `test_overlay_returns_png_of_expected_size` (raw = photo size; corrected = bed raster size).

- [ ] Steps: failing → implement → pass. Run the gates.
- [ ] Bump to 0.17.0, commit, open PR C.

## PR D — calibration analysis in the tool (0.17.0; added 2026-10-21, Matt: "all these analyses need to be shown in the tool itself")

Matt chose all four in a poll: solve after a stop, run report, compare with saved, live views. PR D ships the first three as 0.17.0. PR C (live views, Tasks 7–9 above) becomes 0.18.0.

### Task 10: Solve after a stop
- `AutoCalibrationPanel.tsx`: when `runSweep` throws or returns "stopped", keep the shots. Show the reason, plus how many photos were kept and how many are usable. Offer **solve the N photos taken** when ≥ `MIN_VIEWS` (5) are usable.
- The backend already solves any session's usable samples (verified 2026-10-21 on the 23-photo run: it passed).
- Pure helper `canSolvePartial(shots, minViews)` in `lib/autocal.ts`, with a node test.

### Task 11: Run report
- The solve response adds `limits: {min_views, reprojection_mm, shift_rms_mm}` and `views: [{recoater_mm, points, chessboard, markers}]`.
- `GET /api/vision/autocal/last` returns the saved `.autocal_last_sweep.json` summary (result + per-view counts + image points for the coverage map), or 404 when none exists. A reload shows the last report.
- Panel `CalibrationRunReport`:
  - pass/fail per check against its limit;
  - per-photo table;
  - photo-space map of all points with coverage cells;
  - bed diagram of `valid_region_mm`;
  - where the lens error sits (`residualText`).
- Tests:
  - `test_solve_reports_limits_and_per_view_counts`;
  - `test_last_report_round_trips_and_is_404_before_any_solve`;
  - node tests for `checkRows(report)`.

### Task 12: Compare with the calibration in use
- The solve response adds `current`: the active calibration's version, image_size, reprojection mm (or px for an older one), shift RMS, scale ratio, area extent and method. It is null when there is none.
- Pure `compareCalibrations(next, current)` → rows + verdict ("better" / "worse" / "different photo size — the saved one does not apply to these photos" / "no saved calibration"), with node tests.
- Tests: `test_solve_includes_the_calibration_in_use`.
