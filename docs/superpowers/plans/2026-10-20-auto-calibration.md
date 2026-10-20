# Automatic Science-Camera Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One "Start calibration" run sweeps the recoater-mounted science camera over the placed ChArUco
board, then solves and checks the camera→print-plane calibration at the capture pose.

**Architecture:** Pure, unit-tested cores in `backend/vention_printer_interface/vision/`: the sweep
plan, corner coverage, the solve and the verdict. An operator session lives in a new
`api/autocal_routes.py`. The browser drives motion and capture, like the existing centre sweep
(`SettingsView.tsx`: `api.move(4,"abs",p)` → `waitSettled` → `captureScienceStillOnce`). Its loop is a
pure async function with injected dependencies, so it is testable.

**Tech Stack:** Python 3.11+, FastAPI, OpenCV (`cv2.calibrateCamera`, `cv2.aruco`), numpy; React/TS
(vite, node --test).

**Spec:** `docs/superpowers/specs/2026-10-20-auto-calibration-design.md`

## Global Constraints

- **Safety window:** defaults are min 0 mm and max 523 mm. Remembered between runs. No move outside it.
  The capture pose must lie inside it.
- **Motion rules:** no motion before the operator confirms the planned positions on the page. The
  controller's armed check (`_require_armed`) still applies. Homing is checked first, via
  `telemetry.referenced["4"]`.
- **Approach side:** every sweep position is approached from the same side, going **down** in mm
  (descending order, plus one pre-approach move above the first position).
- **Stills:** taken with `captureScienceStillOnce` (the print capture path). One photo size per session.
- **Board placement:** the board's top face is treated as the print plane. Each saved calibration
  records the placement (`substrate` | `cylinder`) and `board_thickness_mm` (default 3.175, editable),
  plus `plane_note = "board top surface, assumed print plane"`.
- **Pass rule:** reprojection RMS ≤ 0.5 px, encoder-shift RMS ≤ 0.1 mm (worst case reported), ≥ 5 usable
  views. A usable view has ≥ 4 ChArUco corners.
- **Bed frame:**
  - origin = the board's first inner corner (ChArUco id 0)
  - +X = the direction of increasing recoater mm
  - Y = perpendicular, same handedness as the image (rotation only, never a mirror)
- **Bed raster:** `bed_extent_mm` is the bounding box of the corner-covered region mapped to bed mm.
  `mm_per_px` matches native resolution at the image centre. The raster stays within
  `MAX_BED_IMAGE_PX` (`registration.py:79`).
- **Tests:** fixtures come from cv2 projection or cv2-rendered boards, never invented numbers.
- **Style:** ruff line length ≤ 100. mypy clean.
- **Version:** 0.14.0 (feature). Update `backend/pyproject.toml`, `__init__.py`, `uv lock`,
  `CHANGELOG.md` and `frontend/src/lib/changelog.ts`.

## Review Focus

1. **Board not visible at the capture pose:** nothing is solved or saved. The run reports "board not
   found at the capture pose". Task 3 test `test_solve_refuses_without_a_capture_pose_view`.
2. **Recoater not homed, or no position readback:** Start stays disabled with the reason. A sample with
   a non-finite `recoater_mm` is a 400. Task 6 `test_preflight_blocks_unreferenced_recoater` and
   Task 5 `test_sample_rejects_non_finite_position`.
3. **Window that excludes the capture pose, or is inverted:** refused before any motion. Task 1 tests.
4. **Photo size changes mid-sweep** (resolution changed): that sample is refused and the run fails
   honestly. Task 5 `test_sample_of_another_size_is_refused`.
5. **Stop pressed mid-sweep:** no further move is issued, nothing is solved or saved, and the motion
   stop is sent. Task 6 `test_run_sweep_stops_before_the_next_move`.

---

### Task 1: Sweep plan (pure)

**Files:**
- Create: `backend/vention_printer_interface/vision/autocal_plan.py`
- Test: `backend/tests/test_autocal_plan.py`

**Interfaces:**
- Produces:
  - `SweepPlan(poses: list[float], pre_approach_mm: float, capture_mm: float)`, a frozen dataclass.
    `poses` are in descending order and include `capture_mm`.
  - `plan_sweep(capture_mm: float, window_min_mm: float, window_max_mm: float, step_mm: float = 5.0,
    max_offset_mm: float = 70.0, approach_mm: float = 5.0) -> SweepPlan`. Raises `ValueError` with a
    user-facing message.

- [ ] **Step 1: Write failing tests**
  ```python
  def test_poses_are_descending_and_include_the_capture_pose():
      p = plan_sweep(463.3, 0.0, 523.0, step_mm=5.0, max_offset_mm=20.0)
      assert p.poses == [483.3, 478.3, 473.3, 468.3, 463.3, 458.3, 453.3, 448.3, 443.3]
      assert p.pre_approach_mm == 488.3
  def test_window_clips_and_pre_approach_stays_inside():
      p = plan_sweep(520.0, 0.0, 523.0, step_mm=5.0, max_offset_mm=20.0)
      assert max(p.poses) <= 523.0 and p.pre_approach_mm <= 523.0
  def test_capture_pose_outside_window_is_refused():  # Review Focus 3
      with pytest.raises(ValueError, match="capture pose"): plan_sweep(600.0, 0.0, 523.0)
  def test_inverted_or_empty_window_is_refused():
      with pytest.raises(ValueError, match="window"): plan_sweep(100.0, 200.0, 50.0)
  def test_non_positive_step_is_refused():
      with pytest.raises(ValueError, match="step"): plan_sweep(100.0, 0.0, 523.0, step_mm=0)
  ```
  Positions are rounded to 0.001 mm.
- [ ] **Step 2: Run** `cd backend && uv run pytest -q tests/test_autocal_plan.py`. Expected: FAIL
  (module missing, then assertion).
- [ ] **Step 3: Implement** `plan_sweep`. Generate `capture ± k*step` for `k*step ≤ max_offset_mm`,
  keep those inside the window, and sort descending. `pre_approach_mm` is
  `min(max(poses) + approach_mm, window_max_mm)`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(autocal): sweep plan`.

### Task 2: Corner coverage + reachable manual gate

**Files:**
- Modify: `backend/vention_printer_interface/vision/coverage.py`, the `_accumulate_calibration_view`
  descriptor in `backend/vention_printer_interface/api/app.py` (adds `corners_px`)
- Test: `backend/tests/test_coverage.py` (existing; update its gate expectations)

**Interfaces:**
- Produces: `corner_cells(points_px: list[np.ndarray], image_size: tuple[int, int],
  grid: tuple[int, int] = (3, 3)) -> list[list[bool]]`. A cell is True when any corner of any view
  falls inside it.
- Produces: `coverage(...)` descriptors gain an optional `"corners_px"` key. The new rule (manual
  wizard):

  ```
  enough = total_views >= 6 and cells_filled >= 6 and tilt_bins_filled >= 2
  ```

  `cells_filled` counts corner cells. It falls back to the centroid cell for descriptors without
  `corners_px`.

- [ ] **Step 1: Failing tests:**
  - `test_one_frame_filling_board_covers_many_cells`: one view whose corners span the frame →
    ≥ 6 cells
  - `test_manual_gate_needs_six_views_six_cells_two_tilts`
  - `test_old_descriptors_without_corners_still_count_their_centroid_cell`
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Pass `corners_px=detection.image_points.tolist()` in app.py.
- [ ] **Step 4:** Run the coverage tests plus `tests/test_api_vision.py -k coverage` → PASS. Update
  expectations that pinned the old 9-cell/3-tilt rule, and say so in the commit message.
- [ ] **Step 5:** Commit `fix(calibration): coverage counts where corners fall; manual gate reachable`.

### Task 3: Plane solve (pure, synthetic ground truth)

**Files:**
- Create: `backend/vention_printer_interface/vision/autocal_solve.py`,
  `backend/tests/autocal_synth.py` (test helper)
- Test: `backend/tests/test_autocal_solve.py`

**Interfaces:**
- Produces:
  - `AutocalView(recoater_mm: float, image_points: np.ndarray, object_points: np.ndarray,
    ids: np.ndarray)`, a frozen dataclass. Points are Nx2 px and Nx3 board mm; ids are Nx1.
  - `AutocalResult`, a frozen dataclass:

    | field | type |
    |---|---|
    | `camera_matrix` | `np.ndarray` |
    | `dist_coeffs` | `np.ndarray` |
    | `H` | `np.ndarray` (undistorted px → bed mm) |
    | `mm_per_px` | `float` |
    | `bed_extent_mm` | `tuple[float, float, float, float]` |
    | `reprojection_rms_px` | `float` |
    | `shift_rms_mm` | `float` |
    | `shift_worst_mm` | `float` |
    | `scale_ratio` | `float` (measured apparent shift / encoder shift) |
    | `n_views` | `int` |
    | `image_size` | `tuple[int, int]` |
    | `valid_region_mm` | `list[tuple[float, float]]` |
    | `capture_view_corners` | `int` |

  - `solve_autocal(views: list[AutocalView], *, capture_recoater_mm: float, image_size: tuple[int, int],
    max_bed_px: int = MAX_BED_IMAGE_PX) -> AutocalResult`. Raises `ValueError` (user-facing) when fewer
    than 2 usable views exist or no view lies within 0.15 mm of the capture pose.
- `tests/autocal_synth.py`: `synth_views(*, f=1400.0, pp=(972.0, 532.0), dist=(-0.15, 0.05, 0.0005,
  -0.0003, 0.0), size=(1920, 1080), height_mm=170.0, board_rotation_deg=0.0, shifts_mm=..., axis_px=(1,0),
  board=resolve_preset("small_cylinder"), encoder_scale=1.0) -> tuple[list[AutocalView],
  GroundTruth]`. It projects the real `cv2.aruco.CharucoBoard` chessboard corners with
  `cv2.projectPoints` for a camera translated by each shift along the image-`axis_px` direction. It
  keeps only in-frame corners and adds 0.05 px Gaussian noise (seeded).
  `GroundTruth.bed_xy(view_index, image_pts)` returns the true board-mm positions.

- [ ] **Step 1: Failing tests:**
  - `test_recovers_the_plane_mapping_within_20_microns`: map every corner of every view through
    `undistort_points` + `H` at the capture view. RMS error vs ground truth ≤ 0.02 mm. True
    distortion is k1 = −0.15 and k2 = 0.05; the principal point is offset 12 px / −8 px from the image
    centre; shifts are −40…+40 mm in 5 mm steps.
  - `test_bed_plus_x_is_increasing_recoater_mm`: a corner seen at offset +Δ maps to bed X lower by Δ
    (±0.05 mm) than at offset 0. Also holds with `board_rotation_deg=30`.
  - `test_no_mirror_in_the_bed_frame`: det of the 2×2 board→bed rotation = +1.
  - `test_encoder_scale_error_is_caught`: with `encoder_scale=1.02`, `scale_ratio` ≈ 1/1.02 (±0.002)
    and `shift_rms_mm > 0.1`.
  - `test_solve_refuses_without_a_capture_pose_view` (Review Focus 1).
  - `test_extent_and_mm_per_px_are_sane`: the extent contains all mapped corners, and
    `bed_raster_error(mm_per_px, extent)` is None.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.**
  - **Distortion:** `cv2.calibrateCamera` over the usable views. Start from K with fx = fy = image
    width and the principal point at the image centre. Flags: `CALIB_USE_INTRINSIC_GUESS |
    CALIB_FIX_FOCAL_LENGTH | CALIB_FIX_ASPECT_RATIO | CALIB_FIX_PRINCIPAL_POINT | CALIB_FIX_K3`. A
    wrong fixed focal length is exactly absorbed by k1/k2 in pixel space. If the 20 µm test fails
    because of the principal-point offset, drop `CALIB_FIX_PRINCIPAL_POINT` and record why in a code
    comment.
  - **Board homography:** from the capture view, undistorted image points → board mm
    (`compute_homography`).
  - **Recoater direction and scale:** for each other view, map its undistorted points through that
    homography: d = mapped − true board mm. Least-squares fit d ≈ Δ·v with Δ = recoater_mm − capture.
    Then `scale_ratio = |v|` and the bed +X direction is −v/|v|.
  - **Shift residuals:** d − Δ·(−x̂) → RMS and worst case.
  - **Bed frame:** rotation R taking x̂ to (1, 0). Bed = R·(board − board(id 0)). The final `H`
    composes this with the board homography.
  - **Valid region:** convex hull of all views' image points, mapped through the capture calibration.
    The extent is its bounding box, padded outward to whole mm.
  - **Raster scale:** `mm_per_px` = mm per pixel at the image centre, rounded up to 0.01 mm, then
    raised until `bed_raster_error` is None.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(autocal): plane solve with encoder-shift check`.

### Task 4: Verdict + calibration provenance

**Files:**
- Modify: `backend/vention_printer_interface/vision/autocal_solve.py` (verdict),
  `backend/vention_printer_interface/vision/registration.py` (adds `Calibration.provenance` and
  round-trips it in `save_calibration` / `load_calibration`)
- Test: `backend/tests/test_autocal_solve.py`, `backend/tests/test_vision_registration.py`

**Interfaces:**
- Produces: `judge(result: AutocalResult) -> tuple[bool, list[str]]`. Constants: `MIN_VIEWS = 5`,
  `MAX_REPROJ_PX = 0.5`, `MAX_SHIFT_RMS_MM = 0.1`, `MIN_CORNERS = 4`. Each failure reason is a plain
  sentence naming the number and its limit.
- Produces: `to_calibration(result: AutocalResult, *, version: str, provenance: dict[str, Any]) ->
  Calibration`.
- Produces: `Calibration.provenance: dict[str, Any]`, default `{}`. A missing key loads as `{}`
  (old files).

- [ ] **Step 1:** Failing tests:
  - `test_judge_passes_a_good_synthetic_run`
  - `test_judge_names_each_failed_limit` (too few views, high reprojection, high shift RMS)
  - `test_provenance_round_trips_and_old_files_load_with_empty_provenance`
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. The whole `tests/test_vision_registration.py` stays green.
- [ ] **Step 5:** Commit `feat(autocal): verdict + calibration provenance`.

### Task 5: Operator session routes

**Files:**
- Create: `backend/vention_printer_interface/api/autocal_routes.py`
- Modify: `backend/vention_printer_interface/api/app.py` (calls `register_autocal_routes` next to
  `register_uvc_routes`)
- Test: `backend/tests/test_api_autocal.py`

**Interfaces:**
- Produces: `register_autocal_routes(app: FastAPI, *, root: Path, vision_service: Callable[[], Any],
  capture_pose: Callable[[], float], calibration_path: Path, on_saved: Callable[[Calibration], None],
  events: Callable[[str, dict[str, Any]], None]) -> None`. Routes:
  - `GET /api/vision/autocal/window` → `{min_mm, max_mm}`, from `root/.autocal.json`, default
    `{0.0, 523.0}`.
  - `POST /api/vision/autocal/session` with body `{spec: BoardSpecBody, window_min_mm, window_max_mm,
    step_mm?, max_offset_mm?, placement: "substrate"|"cylinder", board_thickness_mm=3.175}` → the
    `SweepPlan` as JSON plus `capture_mm`. Persists the window. A `ValueError` from the plan → 400.
    An invalid ChArUco spec → 400.
  - `POST /api/vision/autocal/sample?recoater_mm=` with a raw image body → `{usable, corners,
    image_size, corners_px, coverage_cells}`.
    - Non-finite position → 400.
    - No session → 409.
    - A different photo size from the session's first photo → `{usable: false, reason}`; the sample is
      not added.
  - `GET /api/vision/autocal/session` → plan, samples summary and `coverage_cells`.
  - `POST /api/vision/autocal/solve` → `{passed, reasons, reprojection_rms_px, shift_rms_mm,
    shift_worst_mm, scale_ratio, n_views, image_size, bed_extent_mm, mm_per_px, valid_region_mm}`.
    Keeps the pending result in the session. A `ValueError` → 400 with the message.
  - `POST /api/vision/autocal/save` → `{calibration_version}`. 409 unless the last solve passed. Saves
    through `to_calibration` with provenance `{method: "auto-sweep", placement, board_thickness_mm,
    plane_note, capture_recoater_mm, window, scale_ratio, shift_rms_mm, valid_region_mm, n_views}`,
    then calls `on_saved`, which hot-swaps the vision calibration.
  - `POST /api/vision/autocal/cancel`.

- [ ] **Step 1:** Failing tests. Images are crops of one large cv2-generated ChArUco image
  (`board.generateImage`). The crop offset in px is Δ_mm × px_per_mm along x, which models a pure
  translating, zero-distortion camera.
  - `test_full_run_passes_and_saves_a_calibration_with_provenance`: the file's provenance placement
    is "substrate", thickness 3.175, and `/api/vision/status` shows the new version
  - `test_save_before_a_passing_solve_is_409`
  - `test_sample_rejects_non_finite_position` (Review Focus 2)
  - `test_sample_of_another_size_is_refused` (Review Focus 4)
  - `test_window_defaults_to_0_523_and_is_remembered`
  - `test_session_refuses_a_capture_pose_outside_the_window`
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Detection uses `detect_board`.
- [ ] **Step 4:** Run → PASS, plus the full backend suite.
- [ ] **Step 5:** Commit `feat(autocal): operator session routes`.

### Task 6: Frontend run logic (pure, tested)

**Files:**
- Create: `frontend/src/lib/autocal.ts`, `frontend/src/lib/autocal.test.ts`
- Modify: `frontend/src/lib/api.ts` (autocal types + calls), `frontend/src/components/views/SettingsView.tsx`
  (its local `waitSettled` uses the shared one)

**Interfaces:**
- Produces: `preflight(i: {status: StatusPayload | null; capturePoseMm: number; scienceAssigned: boolean;
  boardOk: boolean}) -> string[]`. These are plain problem sentences; empty means ready. It checks:
  - controller connected
  - armed
  - `referenced["4"]` true
  - capture pose > 0
  - science camera assigned
  - board settings valid
- Produces: `waitSettled(getStatus: () => Promise<StatusPayload>, axis: number, opts?: {timeoutMs?:
  number; settleMs?: number; sleep?: (ms: number) => Promise<void>}) -> Promise<void>`. This is
  today's logic moved out of SettingsView.
- Produces: `runSweep(plan: {poses: number[]; preApproachMm: number; captureMm: number}, d: {move:
  (mm: number) => Promise<void>; settle: () => Promise<void>; capture: () => Promise<Blob>; readMm: ()
  => Promise<number>; sample: (b: Blob, mm: number) => Promise<{usable: boolean}>; stopped: () =>
  boolean; stopMotion: () => Promise<void>; onStep?: (i: number, r: unknown) => void}) ->
  Promise<"done" | "stopped">`.
  - It moves to `preApproachMm`, then to each pose.
  - It checks `stopped()` before every move. When stopped it calls `stopMotion` and returns
    "stopped".
  - Below the capture pose, it ends early after the first unusable view.
  - Errors propagate.

- [ ] **Step 1:** Failing tests:
  - `test preflight blocks unreferenced recoater` (Review Focus 2)
  - `test preflight lists every missing item`
  - `test runSweep visits pre-approach then poses in order`
  - `test runSweep stops before the next move` (Review Focus 5)
  - `test runSweep ends early below capture once the board is lost`
  - `test waitSettled waits for motion_complete then settles`
- [ ] **Step 2:** `cd frontend && node --experimental-strip-types --test src/lib/autocal.test.ts` →
  FAIL.
- [ ] **Step 3:** Implement. Point SettingsView's centre sweep at the shared `waitSettled`.
- [ ] **Step 4:** Run the node tests (all) and the vite build → PASS.
- [ ] **Step 5:** Commit `feat(autocal): run logic + preflight (frontend)`.

### Task 7: Auto-calibration panel + Advanced manual wizard

**Files:**
- Create: `frontend/src/components/AutoCalibrationPanel.tsx`
- Modify: `frontend/src/components/views/SettingsView.tsx` (the "calib" section shows the
  AutoCalibrationPanel, with `<details>` "Advanced (manual capture)" wrapping `CalibrationWizard`)

**Interfaces:**
- Consumes: Task 6 (`preflight`, `runSweep`, `waitSettled`, api calls), `loadBoardDef` and
  `sessionSpecFromDef` (`lib/board_def.ts`), `captureScienceStillOnce`, `CalibrationSizeNote`.

The panel's flow:
1. **Before Start:**
   - the board and the placement select (default `cylinder` when the generated board has a round cut,
     else `substrate`)
   - thickness (3.175)
   - the window min/max (from `GET /window`)
   - the preflight list, with Start disabled while it is non-empty
2. **Start:** creates the session and shows a page-built confirm: the position list, the window and an
   estimated time of about 3 s per position. No motion until "Move and calibrate" is pressed.
3. **Running:**
   - the latest photo with detected corners drawn over it
   - corners/usable per position
   - a 3×3 coverage grid from `coverage_cells`
   - Stop, which sets a ref flag
4. **Result:**
   - pass/fail, the numbers, and the reasons
   - the placement and thickness, with the line "calibrated at the board's top surface, assumed to be
     the print plane"
   - Save (only when passed)
   - "Return to capture pose" (a confirmed move)
   - a link to Validate

Not unit-testable (DOM). Verification: vite build, then a browser check against the Mac operator with
the controller disconnected. Expected: the preflight list shows "controller not connected" and Start is
disabled. Also check the manual wizard opens under Advanced.

- [ ] **Step 1:** Implement the panel and SettingsView wiring.
- [ ] **Step 2:** `npm run build` → exit 0. All node tests pass.
- [ ] **Step 3:** Browser check as above (dev server `vpi-ui-polish`, Settings → Calibrate).
- [ ] **Step 4:** Commit `feat(autocal): one-button calibration panel; manual wizard under Advanced`.

### Task 8: Release

- [ ] Bump to 0.14.0. Add the CHANGELOG.md and changelog.ts entries. Run `uv lock`.
- [ ] Gates, each with its own exit code: ruff, mypy, pytest (run alone), vite build, node tests.
- [ ] PR with what changed, the tests, the gates and what wasn't verified on hardware (the real sweep on
  the machine).
