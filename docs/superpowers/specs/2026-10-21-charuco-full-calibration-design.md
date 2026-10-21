# Use the whole ChArUco board, validate with it, show calibration live, full resolution

Date: 2026-10-21. Status: for Matt's approval. The builder check is done and its two questions
were answered by Matt. It follows the first passing automatic run,
`cal-20261021T174751Z` (summary: https://claude.ai/artifact/RhcuTob5y1ejsCuQq7PqDN).

## 1. Why

The first real automatic calibration passed: lens fit 0.29 px RMS, encoder-shift 0.039 mm RMS,
scale 1.0021, 9 usable photos. Four problems remain.

1. **It only uses a third of the board.**
   - The solve uses the 9 interior chessboard corners. On the 4×4 board (16 mm squares) these
     span 16–48 mm of the 64 mm pattern.
   - The outer squares carry ArUco markers whose 4 corners each have known board positions. They
     are ignored today.
   - The run's calibrated area was about 42 × 32 mm. Corners only ever landed in the middle third
     of the photo, left to right.
   - Measured on a cv2-rendered board (2026-10-21): 8 markers → **32 marker corners spanning
     2–62 mm**, versus 9 chessboard corners spanning 16–48 mm. With half the board out of view,
     16 marker corners and 3 chessboard corners are still found.
   - The usable source is the board's own `getObjPoints()` / `getIds()`. OpenCV 5's
     `CharucoBoard.matchImagePoints` refuses marker corners (assertion), so marker corners are
     matched by id.
2. **Validation can't pass.**
   - Three attempts were all 400s.
   - At 1920×1080 the frame is about 132 × 74 mm (0.0686 mm/px).
   - The certified chessboard's 17×17 inner corners span 72 × 72 mm.
   - `findChessboardCorners` needs every corner in view, which leaves about 1 mm of slack.
   - The board size is hard-coded in `ValidationPanel.tsx`.
3. **Nothing is visible while calibrating.**
   - Before Start the operator can't see whether the board is found.
   - During the sweep the page shows only the latest photo.
   - After solving there is no picture of what the correction does.
4. **Photos are 1920×1080, not the camera's full resolution.**
   - On the Mac, outside lightweight mode, science stills (prints and calibration) come from the
     ≤1080p stream (`SCIENCE_CAPTURE_STREAM_CONSTRAINTS`).

## 2. Decisions (Matt, 2026-10-21 poll)

- **Validation:** ChArUco self-check plus the certified chessboard, with the chessboard allowed to
  be partly visible.
- **Live views:** all three:
  1. a live preview with corners before Start
  2. a live sweep view
  3. a corrected-vs-raw distortion overlay after solving
- **Resolution:** all science photos (prints, calibration, validation) use the Camera-settings
  resolution through the full-resolution capture. A 1080p calibration must be redone.
- **Coverage:** use the whole existing board (marker corners) rather than demand a new board.
- **Trust:** only the certified chessboard marks a calibration validated, i.e. clears
  `calibration_validation_warning`. The ChArUco self-check is reused-board evidence. It is shown as
  its own result and stored with the calibration's provenance, but it never clears that warning.
- **Self-check timing:** after the sweep and before Save, as a gate.
  - The operator moves or rotates the board and takes one or more photos.
  - They are scored against the PENDING (unsaved) result held in the automatic-calibration session.
  - Save is offered only when the self-check passes. A failure leaves the previous calibration
    active.

## 3. Goals

1. **Calibration uses marker corners as well as chessboard corners.**
   - Both are fed to the distortion fit, the bed homography and the shift check.
   - Each point is matched by its id to the board's known geometry.
   - The calibrated area becomes the swept footprint of the whole board.
   - Coverage and the valid region count every point.
2. **ChArUco self-check (a gate before Save).**
   - After the sweep's solve passes, the operator moves or rotates the board anywhere in view, then
     takes one or more photos.
   - The photos are scored against the session's pending result (the solve output, not yet saved).
     Save stays disabled until a self-check passes.
   - The console maps every identified point through that pending calibration.
   - It compares distances between point pairs with their true board distances: RMS, worst case
     and scale bias.
   - Only points inside the calibrated area count. The report says how many were used and how many
     were outside.
   - A partly visible board works.
   - Accuracy is bounded by the engraving; the caliper scale bar on the board is the reference for
     that.
3. **Certified chessboard validation.**
   - Uses `cv2.findChessboardCornersSB` with `CALIB_CB_LARGER`, which accepts a board larger than
     the requested pattern or partly out of view.
   - The board pattern (inner corners, pitch) is an input on the page, defaulting to the bought
     board (17 × 17, 4.5 mm nominal).
   - Scoring is limited to the calibrated area, with counts reported.
   - The rigid no-scale fit and the scale bias stay as they are.
4. **Live preview.**
   - Before Start, the Calibrate page shows the science camera live.
   - Detected chessboard corners (with ids) and marker outlines are drawn on top, a few times per
     second.
   - The page tells the operator whether the board is found at the capture pose.
5. **Live sweep view.**
   - Each sweep photo appears as it is taken, with its detected points.
   - A coverage map of the photo fills in from every point so far.
   - The calibrated area grows on a bed-mm map.
6. **Distortion overlay.**
   - After the solve, the page shows the capture-pose photo raw and corrected side by side.
   - Each has a grid of straight lines and the calibrated-area outline.
   - It shows what the correction does and where it stops being trusted.
7. **Full resolution everywhere.**
   - Print stills, calibration and validation photos all use the full-resolution capture: the
     camera opened alone at the Camera-settings resolution, raw frame, PNG.
   - This applies on every machine, not only in lightweight mode.
   - Science stills stay consistent in size, so the 0.13.4 size guard keeps working.

## 4. Non-goals

- Tilting the board, or motion other than the recoater.
- Changing the bed frame, the safety window, the approach side or the settle rule.
- Engraving a new board.

## 5. Anti-goals

- Any point used without its identity: no unidentified corners, no guessed matches.
- Showing a validation as passed when it scored few or no points. Unknown never reads as healthy.
- A live preview that drives motion. It is look-only.
- Calibration and print photos of different sizes.

## 6. Constraints

- **Frame source:** browser getUserMedia only. Calibration photos come from the same capture
  function as print photos.
- **Live preview cost:**
  - Detection runs in the operator on reduced-size preview frames (e.g. 1280 px wide, a few per
    second).
  - Results are scaled back to the full-resolution photo's coordinates for drawing.
  - The preview must not block the print capture.
  - It pauses while a still is being taken (the camera bus).
- **Distortion overlay image:** the operator keeps the capture-pose photo of the current session in
  memory and renders the overlay on request. Photos are not written to disk.
- **Marker corner accuracy:** marker corners are refined (`cornerSubPix`) before use. Whether they
  are weighted relative to chessboard corners is left to the builder, as long as tests show the
  mapping accuracy is not worse than chessboard-only on synthetic ground truth.

## 7. Left to the builder

- The live preview transport (a polling upload endpoint is fine) and the frame rate.
- The layout of the three live views in the Instrument style.
- Self-check thresholds. These are pass criteria for the Save gate. Start: pairwise-distance
  RMS ≤ 0.1 mm, worst ≤ 0.2 mm, at least 12 points inside the area. Mark them
  tune-after-first-run.
