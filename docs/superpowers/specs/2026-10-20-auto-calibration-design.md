# Automatic science-camera calibration: place the board, press start, watch

Date: 2026-10-20. Status: written for Matt's approval (builder check done; answers folded in).

## 1. Why

The current Calibrate page (Settings → Calibrate) can't be completed with the real board and camera.
On 2026-10-20 Matt captured 13 views of the small 4×4 board (16 mm squares, 12 mm markers, 9 interior
corners). The page stayed at "no — fill the coverage map".

The coverage gate is the cause (`vision/coverage.py`). Finalize unlocks only when all of these hold:
- the centre of the detected board has landed in all 9 cells of a 3×3 grid over the frame
- the views span three tilt ranges (<10°, 10–25°, >25°)
- there are at least 6 views

The small board fills about 80% of the frame height and about 48% of its width at the capture pose (Matt's
screenshot). To put its centre in a top or bottom cell, roughly a third of the board would have to leave
the picture. In the 99.2 mm build cylinder the board cannot slide at all. Nothing on the page explains
any of this. Each capture is also a manual click.

Matt wants: **place the board once, press Start, and monitor.** The science camera rides the recoater
(axis 4), so the machine can move the camera instead of a person moving the board.

## 2. Goals

1. One button runs the whole calibration. Matt's only actions are placing the board, pressing Start,
   confirming the planned motion, and watching. Stop and E-stop always work.
2. The result maps science-photo pixels to millimetres on the print plane at the capture pose,
   including lens distortion. Lens distortion is fitted from the ChArUco corners. Partial boards near
   the frame edges still count, because each ChArUco corner is identified individually.
3. Every number the page shows is real. The run reports plain pass/fail with the evidence. A weak or
   failed fit never shows as healthy.
4. It works with both board placements Matt uses:
   - the **square board on the static aluminium substrate** (closer to the print plane)
   - the **round 98.5 mm board in the build cylinder**

## 3. Non-goals

- Tilting the board. The machine can't tilt it, and the measurement only has to hold on the print
  plane. The trade-off: the lens model is fitted for that plane, not as a general 3-D camera model.
- Moving the build piston (Z). With the board on the static substrate, the piston can't be lowered
  under it (Matt, 2026-10-20).
- Correcting for the board's thickness (decided by Matt, 2026-10-20). For now the board's top face
  counts as the print plane. The engraved board is 1/8" (3.175 mm) thick and sits on the static
  substrate, so the true offset is not yet known and will be added later. To leave room for that:
  - every saved calibration records the board placement (substrate or cylinder) and the board
    thickness, 3.175 mm by default and editable
  - the result says plainly "calibrated at the board's top surface, assumed to be the print plane"

  Height errors scale the measurement by the height difference divided by the camera height. The
  sideways sweep cannot detect them, so the later correction will need the camera height, e.g. from
  one known build-piston drop in the cylinder placement.
- A calibration valid at recoater positions other than the capture pose. Print stills are only taken
  there.
- Changing how print stills are taken, or the 0.13.4 size guard. Calibration stills keep using the same
  capture function as print stills (`fullResScienceStill` in lightweight mode, the existing grab
  otherwise). One photo size per session.

## 4. Anti-goals (a failure even if it "works")

- **Any motion outside the travel window, or before the operator confirms the planned positions.**
- **Any motion while not armed or not homed.** The existing controller refuses unarmed moves
  (`_require_armed`, `control/controller.py`). The run must also check homing first.
- **A calibration saved without its fit being checked**, or shown as good when it isn't.
- **Calibration stills taken a different way from print stills** (the frame-source and size rules
  from #87 and #124).

## 5. Safety window (decided by Matt)

- The recoater may only move between a **minimum and a maximum position** that the operator enters
  before starting.
- **Defaults: 0 mm to 523 mm.** 523 mm is the farthest safe extent with the square board on the
  substrate, where the recoater blade would otherwise reach the board. Below that, the recoater can go
  as close to 0 mm as needed.
- The window is remembered between runs (my call: a print-settings field like `capture_recoater_mm`).
- Planned positions outside the window are dropped before anything moves. If the capture pose itself
  is outside the window, the run is refused.
- The same window applies to the round board in the cylinder (my call: one window, editable per run).

## 6. How a run goes

1. **Preflight.** The page lists what's missing in plain words and Start stays disabled until every
   item passes:
   - controller connected, armed and homed
   - capture pose saved (`capture_recoater_mm` > 0)
   - science camera assigned, at the print resolution
   - board settings entered (from Calibration board)
   - the board found in a photo taken at the capture pose (the recoater moves there first, which
     needs its own confirm)
2. **Plan and confirm.** The page shows the planned recoater positions inside the window, centred on
   the capture pose, and the estimated time. Motion starts only after the operator confirms on the page.
3. **Sweep.** At each position, in order:
   1. move the recoater (absolute)
   2. wait for motion complete plus a settle delay (same as the centre sweep)
   3. take the still with the print capture function
   4. upload it with the recoater position read back from telemetry, not the commanded value
   5. the operator detects the ChArUco corners and records the view

   In each direction the sweep stops when the board is no longer usable (fewer than a minimum number
   of corners, e.g. 4; my call) or the window edge is reached. The page shows, live:
   - the latest photo with its detected corners
   - a coverage map built from where the **corners** fall, not board centres
   - corners per view
   - the position
   - a Stop button

   Stop and any error end the sweep and leave the recoater where it is (my call). The page then offers
   a confirmed move back to the capture pose.
4. **Solve** (in the operator, from the recorded views; details in §7).
5. **Result.** The page shows:
   - pass/fail
   - reprojection error (px)
   - the encoder-shift check (mm; §7)
   - number of views and corners
   - photo size

   If the run passes, the operator saves it as the calibration, which keeps today's versioning and
   hot-swap. If it fails, the page says why and nothing is saved. The recoater returns to the capture
   pose (confirmed move). The page then offers the existing Validate step.

## 7. What the solve must deliver

- **The mapping.** Lens distortion plus a bed homography, valid on the print plane at the capture
  pose. The view at the capture pose (offset 0) defines the bed reference: the board's first inner
  corner is the origin, as today. This replaces the "use last view as bed reference" checkbox.
- **Distortion with a fixed-height, translating camera.** Every view is the same plane at roughly the
  same distance, so the focal length is not separately observable. Only the plane mapping is needed,
  so the builder may fix the focal length (and principal point, if needed) to a nominal value and fit
  the distortion coefficients. The pixel-to-plane mapping that results is what matters.
  The builder chooses the exact OpenCV route (e.g. `calibrateCamera` with `CALIB_FIX_FOCAL_LENGTH`
  etc., or a direct joint fit) and proves it with tests.
- **Encoder-shift check.** This is an independent scale check that comes free with the sweep. A
  corner seen at recoater offset Δ, mapped through the capture-pose calibration, should land Δ mm
  along the recoater direction from where it lands at offset 0. The run reports the worst and RMS
  discrepancy in mm. It is reported alongside, not instead of, the certified-chessboard Validate step.
- **Pass/fail thresholds** (my call; tune after the first real run):
  - reprojection RMS ≤ 0.5 px
  - encoder-shift RMS ≤ 0.1 mm, worst reported (the readout step is 0.1 mm, so this checks scale and
    gantry straightness, not sub-step precision; certified accuracy comes from Validate)
  - at least 5 usable views

  Failing any of them fails the run, and the page names which.
- **Valid region** (my call). The fit is only trusted where corners were actually seen. The recoater
  sweeps along one axis, so with the small board the corners cover a band across the frame, not the
  frame corners. The run records the region the corners covered:
  - the result shows it as a map over the photo
  - `bed_extent_mm` is limited to it
  - analysis outside it is labelled "outside the calibrated area", never silently measured

  Coverage is reported, but it is not a gate: a 3×3-cells rule fails for the same reason the current
  one does. A larger board that overfills the frame covers more and gives a better fit. ChArUco takes
  partial views, so that is the recommended board for the substrate placement.
- **Bed axes** (my call). The origin stays at the board's first inner corner. Bed X is aligned to the
  recoater direction estimated from the sweep, with +X in the +recoater (increasing mm) direction. Bed
  Y is perpendicular, with the same handedness as the camera image (no mirroring). This fixes the bed
  frame to the machine whatever the board's rotation (the round board can sit at any angle in the
  bore). Lane B's existing CAD alignment is unchanged by this design.
- **Recoater position, backlash and the shift check** (my call). Every sweep position is approached
  from the same side, and the capture pose is approached the way prints approach it (from lower mm;
  the builder confirms against `compile_print`). One-sided approach takes backlash out of the check.
  The position used per view is the telemetry readback (axis 4 reads in 0.1 mm steps, like the other
  axes). The shift check is judged on its RMS, with the worst case reported. The threshold sits above
  the 0.1 mm readout step (see thresholds).
- **Bed image size.** `mm_per_px` and `bed_extent_mm` are chosen automatically:
  - the extent covers what the camera sees at the capture pose, mapped into bed mm
  - `mm_per_px` is about the native resolution at the image centre
  - both stay under the existing `MAX_BED_IMAGE_PX` limit

  This replaces the two input fields (my call; still overridable under Advanced).

## 8. Where things live

- **The browser drives motion and capture**, like the existing centre sweep (`SettingsView.tsx` →
  `api.move(4, "abs", p)`, `waitSettled`, then the capture). This keeps the frame-source rule and
  reuses proven code.
- **The operator holds the session and does all detection and solving**, like the centre sweep and
  calibrate sessions: start session (window and plan), add sample (image + measured position), status,
  finalize, cancel. The existing `/api/vision/calibrate/*` routes stay working.
- **Pure, unit-tested cores:**
  - sweep planning (positions from capture pose, window, step)
  - corner-coverage summary
  - the solve
  - the encoder-shift check
  - the pass/fail rules

  Tests use synthetic boards rendered with a known distortion and known camera shifts, so the solve is
  checked against a ground truth. Fixtures come from cv2-rendered boards, never invented numbers.
- **The current manual wizard** moves under "Advanced (manual capture)" (my call). Its gate changes
  from board-centre cells to corner coverage, so it is reachable. Both flows share the same solve and
  checks.

## 9. Left to the builder

- Step size and settle delay. A reasonable start: 5 mm steps (the field of view is about 130 mm wide at
  the capture pose, by the board's apparent size), 400 ms settle as in the centre sweep.
- The exact distortion-fit route (§7), as long as tests prove it recovers a known distortion and shift.
- Page layout, within the existing Instrument style.
- Whether the sweep alternates sides or does one direction then the other.

## 10. Open item

- Which image axis the recoater moves along is not known in advance. The solve must estimate the
  recoater direction from the data (the board's apparent motion between views), not assume it.
