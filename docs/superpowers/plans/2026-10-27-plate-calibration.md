# Certified-Plate Calibration Plan

**Goal:** Calibrate the science camera on the certified chessboard (DEvision Q18-100-4.5: 18 x 18 squares, 4.5 mm, 17 x 17 inner corners) instead of the engraved ChArUco. Matt, 2026-10-27: the plate is flat and properly manufactured; the ChArUco is home-made.

**Why it should help (2026-10-27 lab data):** ChArUco calibration + encoder scale fix validated at RMS 0.039 mm / worst 0.075 mm (bias 1.0009). Every miss sits at the left/right edges of a calibrated band only ~46 % of the photo wide: the 4x4 ChArUco never reaches there. The plate fills the photo.

## Data contract (probed 2026-10-27)

| Fact | Evidence |
|---|---|
| Whole plate fits the photo at the capture pose: 17 x 17 = 289 corners | `validations/cal-20261027T175542Z/20261027T175712265073Z/raw.jpg`, `detect_chessboard_partial` → 289 |
| Plate spans ~y 256..3488 px of 3840 (sweep axis = image y) | same photo, annotated |
| Sweep = 14 photos, 5 mm steps (518.7 → 453.7) | `~/.vpi-cache/autocal_last/NN_<mm>.png` |
| Detector is random; grid check + retry needed | 0.22.1, `tests/test_chessboard_lattice.py` |
| Rotation is already fitted out of validation scoring | re-score 2026-10-27: tilt -2.20° vs -0.49° → identical 0.039 / 0.075 mm |
| Real plate sweep | **not captured yet** (Matt to sweep + caliper thickness) |

## Design

1. **Labels (new `vision/plate_labels.py`).** A plain chessboard has no IDs.
   - **Orientation** of every view by image direction: label column index increases toward image +x, row index toward +y (valid while the plate is within 45° of square to the photo).
   - **Full views** (all 17 x 17 seen) are labelled absolutely. At least 2 full views per placement are required, which is true for ±5 mm around the capture pose.
   - **Partial views** get one integer (col, row) offset. Their corners are mapped through the reference full view's homography and compared with the encoder-predicted shift Δ·v, where v is fitted from the full views and refitted as views are accepted, nearest |Δ| first.
   - A view is accepted only when the rounding margin is clear (residual < pitch/4); otherwise it is dropped, with the reason.
2. **Solve.** For a plate, the board's certified mm is the scale reference: no rescale to encoder mm. `scale_ratio` is reported as the independent check, and judge refuses when it is more than 0.5 % from 1.
3. **Session.** The board kind is "checkerboard" (cols, rows, square_size_mm). A sample stores the raw detection; labelling runs at solve over the whole sweep. The plate-thickness field already exists.
4. **Frontend.** A "Certified chessboard (4.5 mm)" board choice. Validation afterwards: move or rotate the plate, then Validate.

## Tests (red → green each)
- `plate_labels`: orientation canonicalisation (real full detection, all 8 index transforms come back the same); partial-offset recovery on REAL photo crops (crop shift k px stands in for camera motion of k·px_mm: real pixels, synthetic motion, labelled as such); ambiguous margin refused; fewer than 2 full views refused.
- Solve: checkerboard views are not rescaled to encoder mm, and the scale ratio is still reported.
- API: a checkerboard session runs sample → solve.
- **Before merge:** real plate sweep from the lab, solved end to end, then validated with the plate moved.
