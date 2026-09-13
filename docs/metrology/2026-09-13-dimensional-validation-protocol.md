# Dimensional-Accuracy Validation Protocol — Layerwise Machine-Vision on the Binder-Jet Printer

**Status:** PLAN. No measured numbers appear below. Every value is a target, a threshold, or a
formula to be filled once data exist. Author: RFAM Experimentalist. Date: 2026-09-13.

**Claim under test.** The calibrated vision pipeline (`register_frame` = undistort → warp-to-bed)
maps in-plane bed features to true millimetres with a field-wide error small enough to serve
layerwise dimensional QA at a chosen tolerance. Falsifiable form: *across the working bed, the
point-position error between homography-mapped checkerboard corners and their certified true
geometry has bias, repeatability, and worst-case magnitude all inside the gate for the chosen
tolerance T (Section 5).* If any gate fails, the system is rejected at that tolerance.

**Measurement primitive (exact contract, from
`backend/vention_printer_interface/vision/registration.py`).**
`validate_dimensions(known_points_mm, measured_points_mm) -> {rms_mm, max_mm, points:[{known_mm,
measured_mm, error_mm}]}` where `error_mm` is the per-corner **Euclidean** distance
`||measured - known||`. It compares two point sets *already in a common frame* — it does no
alignment. That alignment step is ours to define (Section 5.1) and is the single biggest source of
"lying to yourself" in this protocol.

---

## 0. Measurement chain (what actually gets compared)

Per validation frame, the operator/UI executes:

1. `detect_board(image, checkerboard_spec)` → `image_points` (N×2 px, sub-pixel via `cornerSubPix`).
2. `undistort_points(image_points, camera_matrix, dist_coeffs)` → undistorted px.
3. `apply_homography(H, undistorted_px)` → `measured_points_mm` (N×2 in bed mm).
4. Build `known_points_mm` = ideal grid `(col,row) × true_pitch` (true pitch from Section 1),
   then **best-fit align** known→measured (Section 5.1).
5. `validate_dimensions(known_points_mm, measured_points_mm)` → `rms_mm`, `max_mm`, per-point.

Note the pipeline detail: `H` is defined on **undistorted** image coordinates (see
`register_frame` / `build_bed_remap`), so validation must undistort points *before* applying `H`,
exactly as steps 2→3 do. Do not feed raw pixels to `apply_homography`.

**Do not validate off the warped raster.** `warp_to_bed` resamples to a 0.05 mm/px output grid;
measuring corners on that raster adds a resampling/quantization error (~½ output pixel = 0.025 mm)
on top of the real geometry error. Always measure from **point correspondences** (steps 1–3), not
from pixels of the warped image. The 0.05 mm/px grid is an output convention, not an accuracy.

---

## 1. Reference-artifact requirements

### 1.1 Test Uncertainty Ratio (TUR) rule

The reference's own uncertainty must be small compared to the tolerance being certified. Use the
standard metrology rule: **TUR ≥ 4:1 is the floor, ≥ 10:1 is the target.** With half-tolerance
`T` (so the spec band is `±T`), the reference expanded uncertainty `U_ref` must satisfy:

| Target tolerance | Half-tol T | U_ref @ 4:1 (floor) | U_ref @ 10:1 (target) |
|---|---|---|---|
| ±0.05 mm | 0.05 mm | ≤ 0.0125 mm | ≤ 0.005 mm |
| ±0.10 mm | 0.10 mm | ≤ 0.025 mm  | ≤ 0.010 mm |
| ±0.25 mm | 0.25 mm | ≤ 0.0625 mm | ≤ 0.025 mm |

`U_ref` here is the uncertainty of the reference **pitch/scale and corner geometry** in mm, not the
caliper's single-reading resolution. If `U_ref` cannot meet the 4:1 floor for a tolerance, that
tolerance is **not certifiable** with this artifact — report it, do not fudge it.

### 1.2 Qualifying the bought checkerboard (treat reference accuracy as a variable — REQUIRE it be established)

The checkerboard's true pitch is an input, not an assumption. Two acceptable paths:

- **(A) Certified target.** If it ships with a calibration certificate stating pitch and
  uncertainty (e.g. a chrome-on-glass or laser-etched MV target with `U_ref` on the cert), record
  the cert value and `U_ref` directly. Photograph/scan the cert into the run record.
- **(B) Caliper-established true pitch (averaging trick).** If uncertified, **do not caliper a
  single square** — a ±0.02 mm caliper on one 5 mm pitch is a 0.4% (0.02 mm) error, failing even
  4:1 at ±0.05. Instead measure the **gross span across many pitches**: measure corner-row-0 to
  corner-row-K over K pitches (largest K the jaws span, ≥ 20), repeat M ≥ 5 times, and compute
  `true_pitch = mean_span / K`. The pitch uncertainty divides by K:
  `U_pitch ≈ U_caliper / K` (plus a `√M` gain on the random part). Example: `U_caliper = 0.02 mm`,
  `K = 20` → `U_pitch ≈ 0.001 mm`, which meets 10:1 even at ±0.05. Do this on **both axes** and on
  **two orthogonal locations** to catch pitch anisotropy and non-squareness; if the two axes
  disagree by more than `U_ref`, treat the board as anisotropic and carry separate x/y pitches.
- **Averaging across squares also applies in-frame:** because `validate_dimensions` uses all N
  corners, the *scale* estimate benefits from every pitch in the field, so board scale error
  averages down; localized errors (a bad square, a scratch) show up in `max_mm`, not `rms_mm`.

### 1.3 Alternatives / complements (rank order)

1. **Certified chrome-on-glass MV target** — best `U_ref`, flat, thermally stable, but glass is
   specular; needs diffuse/polarized lighting to detect on a tilted macro cam.
2. **Gauge pins / gauge blocks** (class ZZ pins, grade-B blocks) — sub-µm-to-few-µm certified
   *length*, ideal to spot-check a single mapped distance and to validate the caliper itself, but
   they give one dimension per artifact, not a field.
3. **Caliper-verified laser-engraved feature plate** — cheap, custom feature layout on the actual
   bed footprint; qualify its pitch by path (B) above.
4. **The bought checkerboard** — primary field artifact for spatial coverage (many corners at once).

**Excluded — wrong scale:** the microscope **stage micrometers / reticles** (10 µm graduations).
At 30–40 µm/px a 10 µm tick is **sub-pixel (0.25–0.33 px)**; the camera cannot resolve individual
ticks, so they cannot serve as a length reference for this macro cam. They belong to the microscope,
not to this rig. Do not use them here.

---

## 2. Independence

Independence is what turns this from a self-consistency check into a validation.

- **Different artifact for calibrate vs validate.** Calibrate intrinsics + `H` on the **ChArUco**
  board. Validate on the **checkerboard** (different pattern, different detector path:
  `findChessboardCorners`+`cornerSubPix` vs `CharucoDetector`). This breaks the trap where the same
  detection bias inflates both calibration and its own "validation."
- **Different bed positions.** Validation checkerboard placements must **not** reuse the calibration
  poses. Calibration should tile the frame with ChArUco views; validation then places the
  checkerboard at the independent grid of Section 3. Overlap of a validation pose with a calibration
  pose voids that run.
- **Powder-surface plane only.** `H` is a plane-to-plane map fit at the **powder-surface height**.
  Because the camera is tilted 30–45°, any feature **off** that plane carries parallax: an
  out-of-plane offset `Δz` projects to an in-plane error `≈ Δz·tan(θ)` (θ = tilt from normal), i.e.
  0.5–1.0 mm of apparent shift per mm of height at these tilts. Therefore:
  - Validate **in-plane dimensions only** (corner-to-corner spacings within the powder-surface
    plane). Do **not** claim height or 3-D accuracy.
  - The checkerboard's pattern face must sit at the **same height as the calibration plane**. Shim
    the board so its printed surface is coplanar with the powder surface used for `H`
    (board substrate thickness is a systematic `Δz` — measure it and shim it out, or record it and
    apply the `Δz·tan(θ)` correction/uncertainty). Record measured `Δz` per run.

---

## 3. Spatial coverage (DoE)

**Design:** a position × orientation layout that forces the homography to reveal edge/perspective
error, plus a repeat-at-center for the noise floor. The tilt makes error strongly **spatially
non-uniform** (far edge worse than near edge), so coverage is not optional — a center-only check
would pass a system that fails at the far edge.

**Factors:**
- Position (categorical, 7 levels): Center, 4 Corners (NW, NE, SW, SE), Near-edge (closest to cam),
  Far-edge (farthest from cam). For the ±0.05 mm tier add 2 mid-radius positions → 9.
- Orientation (categorical, 2 levels): 0° and 45° board rotation (45° maximally decorrelates the
  board grid from the bed/pixel grid and exposes anisotropic scale/skew).
- (Nested) Static-capture replicate, Power-cycle replicate — see Section 4.

**Run table (positions × orientations), randomized order.** "Reps" columns are filled per tolerance
tier from Section 5/6.

| Run | Position | Orientation | Static caps (n_s) | Notes |
|---|---|---|---|---|
| P1 | Center     | 0°  | n_s | also noise-floor anchor (large n_s) |
| P2 | Center     | 45° | n_s | anisotropy check at best-focus region |
| P3 | NW corner  | 0°  | n_s | |
| P4 | NE corner  | 0°  | n_s | |
| P5 | SW corner  | 0°  | n_s | |
| P6 | SE corner  | 0°  | n_s | |
| P7 | Near-edge  | 45° | n_s | shortest object distance, best px/mm |
| P8 | Far-edge   | 45° | n_s | worst px/mm + max parallax → expected worst case |
| P9*| Mid-radius (2)| 0° | n_s | ±0.05 tier only, 2 positions |

*Randomize the physical order of P1–P9 (draw once, record the seed/order) so operator drift,
lighting drift, and thermal drift do not alias onto position. Re-place the board by hand each run
(placement is a real use-condition variable). Keep the board's printed face coplanar with the
powder plane at every position (Section 2).

**Why these positions:** corners + far-edge probe the largest homography extrapolation and the
worst perspective foreshortening; near-edge is the best case; center anchors precision. Reporting
`max_mm` **per position** (not just pooled) is what catches the far-edge failure mode.

---

## 4. Replication & precision — separating BIAS from PRECISION (gauge-R&R-lite)

Three nested sources of variation, each measured deliberately:

1. **Repeatability (PRECISION floor / EV).** Same board, same position, **no motion** — capture
   `n_s` frames back-to-back. Variation here = camera noise + sub-pixel detection jitter + rolling-
   shutter/illumination flicker. Estimate `σ_repeat` = std of per-corner position (or of `rms_mm`)
   across the `n_s` static frames. This is the **noise floor**: no gate can be tighter than it.
2. **Reproducibility (pose/setup, AV+drift).** **Re-home / power-cycle** the machine and re-park to
   the same nominal pose; recapture. Repeat for `n_c` cycles. Variation added here = park-position
   repeatability + any calibration-pose drift + re-illumination. Estimate `σ_repro`.
3. **Bias (accuracy).** Mean signed error vs certified truth, per position and pooled. Report as
   both a **scale bias** (fitted scale − 1, in ppm and mm across the field) and a **residual
   position bias** field after the rigid fit. Bias is the systematic part `validate_dimensions`
   folds into `rms_mm`; precision is the run-to-run scatter of that number.

**Gauge-R&R-lite structure** (not a full crossed GRR — one "operator" = one automated pipeline, so
this estimates EV and setup-reproducibility, not appraiser variation):

| Component | How measured | Symbol | Design |
|---|---|---|---|
| Repeatability (EV) | `n_s` static caps, no motion | σ_repeat | at every position; large `n_s` at anchors |
| Reproducibility (setup) | `n_c` power-cycle/re-home caps | σ_repro | at Center + Far-edge (worst case) |
| Bias (accuracy) | mean error vs cert truth | b | every position, 0° and 45° |
| Total precision | `σ_R = √(σ_repeat² + σ_repro²)` | σ_R | pooled |

**Report the ANOVA-style variance split** (position as a fixed effect; static-replicate and
power-cycle as nested random effects). Deliverable: a table of `b`, `σ_repeat`, `σ_repro` per
position, plus pooled `σ_R`, plus `max_mm` per position.

---

## 5. Metrics & acceptance gates

### 5.1 Alignment before scoring — CHOOSE AND STATE IT (or the number is meaningless)

`validate_dimensions` does no alignment. The checkerboard is placed at an unknown pose, so
`known_points_mm` (ideal grid) and `measured_points_mm` (homography output) live in different
frames until aligned. **Two analyses, reported separately:**

- **A. Rigid fit (rotation + translation only, NO scale).** Best-fit R,t of the ideal grid onto the
  measured points, then `validate_dimensions`. Residuals capture **scale error + perspective/
  distortion + local geometry** — this is the honest *dimensional-accuracy* number and drives the
  gates below. Allowing scale in the fit would **hide** a scale error (the exact thing QA must
  catch), so scale is NOT a free parameter here.
- **B. Pure scale/pitch check.** Independently, mean measured nearest-neighbour pitch vs certified
  pitch → scale bias (ppm and mm-across-field). Cross-checks that any residual in A is geometry, not
  a mis-set `mm_per_px`/`H` scale.

Record which fit produced each number. The gate is on Analysis A (`rms_mm`, `max_mm`) plus the
Analysis B scale bias.

### 5.2 Metrics (all from `validate_dimensions` on Analysis-A-aligned points)

- `rms_mm` — field RMS point-position error (the headline accuracy number), per position and pooled.
- `max_mm` — worst single-corner error in the field (drives the worst-case/`±T` claim).
- `b` (bias) — mean signed radial error and fitted scale bias (Analysis B).
- `σ_repeat`, `σ_repro`, `σ_R` — precision (Section 4).

### 5.3 Accept/reject gates, parameterized for three candidate tolerances

Convention: a "±T" tolerance means individual mapped features must land within `T` of truth, so the
**worst-case** metric `max_mm` is gated at `T`, with **guard-banding** for measurement uncertainty.
`rms_mm` (the distribution's core) is gated tighter. Guard band uses `σ_R` (pooled precision) with
`k=2` (≈95%). Reference must first pass TUR (Section 1.1) or the tier is void.

| Requirement | ±0.05 mm | ±0.10 mm | ±0.25 mm |
|---|---|---|---|
| Reference U_ref (must meet ≥4:1) | ≤ 0.0125 mm | ≤ 0.025 mm | ≤ 0.0625 mm |
| Bias gate: \|b\| pooled ≤ | 0.015 mm | 0.030 mm | 0.075 mm |
| Precision gate: σ_R ≤ | 0.015 mm | 0.030 mm | 0.075 mm |
| RMS gate: rms_mm pooled ≤ (T/2) | 0.025 mm | 0.050 mm | 0.125 mm |
| Worst-case gate: max_mm any position + 2σ_R ≤ T | ≤ 0.05 mm | ≤ 0.10 mm | ≤ 0.25 mm |
| Scale-bias gate (Analysis B) ≤ | 0.010 mm/field | 0.020 mm/field | 0.050 mm/field |
| Min static caps n_s (per position) | 10 | 5 | 3 |
| Min power-cycles n_c (anchors) | 10 | 5 | 3 |
| Noise-floor caps at anchor | 50 | 25 | 15 |

**Decision rule (per tolerance tier):** ACCEPT the system at tolerance ±T iff **all** of: reference
passes TUR ≥ 4:1; `|b| ≤ T/3`; `σ_R ≤ T/3`; pooled `rms_mm ≤ T/2`; and `max_mm + 2σ_R ≤ T` at
**every** position (including Far-edge). Otherwise REJECT at ±T (and report the binding
constraint — usually Far-edge `max_mm` or `σ_R` at ±0.05).

**Honest reach.** The ±0.05 mm tier sits near the physical floor of this rig: at 30–40 µm/px, sub-
pixel corner localization of ~0.1–0.3 px is already 3–12 µm, and homography + plane-coplanarity +
park-repeatability stack on top. If measured `σ_R` approaches 0.015 mm, the ±0.05 gate has almost no
guard band left and the tier may be **unprovable** (you cannot certify a tolerance you cannot
resolve). ±0.10 and ±0.25 are expected to be comfortably resolvable. State this outcome explicitly;
do not report a pass you cannot defend.

---

## 6. Sample size / power

**Precision estimate (how many static caps to trust σ).** A std from `n` samples has ~`1/√(2(n-1))`
relative uncertainty. `n_s = 25` → ±14% on σ; `n_s = 50` → ±10%. Hence the noise-floor anchors use
25 (±0.10) to 50 (±0.05) captures; loose tiers tolerate fewer.

**Bias detection power.** One-sample test that mean bias ≠ 0 at α=0.05 (two-sided), power 0.80:
`n ≈ (z_{α/2}+z_β)² (σ/δ)² = 7.85·(σ/δ)²`, δ = the bias magnitude to resolve.

| Bias to resolve δ | σ/δ = 0.5 | σ/δ = 1.0 | σ/δ = 1.5 |
|---|---|---|---|
| n per condition (rounded up) | 2 | 8 | 18 |

Interpretation with δ tied to tolerance: to catch a bias of **half the tolerance** (`δ = T/2`) when
precision is `σ ≈ T/3` (i.e. `σ/δ ≈ 0.67`), `n ≈ 4` replicates per position suffice — consistent
with the `n_s`/`n_c` in the gate table. To catch a **quarter-tolerance** bias (`δ = T/4`,
`σ/δ ≈ 1.33`) you need `n ≈ 14`, which is why the ±0.05 tier (where quarter-tol = 0.0125 mm is
near the noise floor) demands the largest replication and is the hardest to certify. Across the
7–9 positions, total validation frames per tier ≈ positions × n_s + anchors × n_c:
roughly **~40 (±0.25), ~85 (±0.10), ~200 (±0.05)** frames.

**Confound honesty:** with one automated pipeline there is no appraiser factor, so this design
estimates equipment + setup variation, **not** operator variation. Board-placement-by-hand is
deliberately folded into σ_repro (re-placed each run) so the certified number reflects real use; if
placement is instead fixtured in production, σ_repro will be optimistic — note the discrepancy.

---

## 7. Procedure (operator steps at the machine)

**Pre-flight (once per validation campaign):**
1. Confirm active calibration: `load_calibration` returns intrinsics + `H` + `mm_per_px` +
   `bed_extent_mm`; record `version` and `reprojection_error`. Reject if intrinsics absent
   (Phase-2 homography-only file) for anything tighter than ±0.25.
2. Establish reference truth (Section 1.2): record certified pitch + `U_ref`, or perform the
   caliper span-averaging on both axes; log values, K, M, and computed `U_pitch`.
3. Lock the optics: fix zoom and focus rings and **tape/set-screw them**; record focal length,
   aperture, and a focus-verification frame. Any later touch voids the campaign (lens breathing).
4. Warm up: power the camera and lighting ≥ 30 min; log ambient temp. Fix lighting (constant DC/
   flicker-free source, no room lights that vary).
5. Measure and record `Δz` (board printed-face height vs powder-surface calibration plane); shim to
   coplanar (Section 2).

**Per run (each position/orientation, randomized order from Section 3):**
6. Place checkerboard at the target position/orientation; confirm coplanarity (re-check `Δz`).
7. Park/still the machine (captures only at parked moments — rolling-shutter mitigation, Section 8).
8. Guided capture UI: grab `n_s` static frames with **no motion between them**.
9. For each frame run the Section-0 chain (`detect_board` → `undistort_points` → `apply_homography`),
   build `known_points_mm`, do the **rigid** alignment (Analysis A), call `validate_dimensions`.
   Also compute Analysis-B scale bias.
10. UI records per frame: timestamp, position, orientation, `Δz`, ambient temp, `rms_mm`, `max_mm`,
    full per-point list, N corners detected, fit residual of the rigid alignment, and the raw image
    hash/path (reproducibility).
11. After the position set, do `n_c` **power-cycle/re-home** reps at Center and Far-edge; repeat 6–10.

**Post (analysis):**
12. Aggregate: per-position `b`, `σ_repeat`, `σ_repro`, `max_mm`; pooled `σ_R`, `rms_mm`.
13. Apply the Section-5.3 decision rule at each of the three tolerance tiers; report ACCEPT/REJECT
    per tier and the binding constraint.
14. Persist the summary into the calibration's `validation` dict (the `Calibration.validation`
    field is designed to carry exactly this) alongside `version` so the accepted tolerance travels
    with the calibration file.

**Record for every frame (data contract):** timestamp; calibration `version` + `reprojection_error`;
position; orientation; `Δz`; ambient temperature; lighting setting; focus/zoom lock state;
`rms_mm`; `max_mm`; per-point `error_mm`; N detected corners; rigid-fit residual; reference
`true_pitch` + `U_ref`; raw image path + hash; randomization seed/order.

---

## 8. Threats to validity (and mitigations)

- **Illumination stability.** Corner sub-pixel location shifts with lighting gradient/flicker on a
  rolling shutter. *Mitigate:* fixed flicker-free DC source, constant geometry, warm-up, and
  monitor `σ_repeat` over time; a rising σ across the campaign flags drift. *Cannot fully remove* —
  folded into σ_repeat.
- **Focus / zoom lock (lens breathing).** Any change to focus or zoom changes intrinsics **and**
  effective mm/px, silently invalidating `H`. *Mitigate:* mechanically lock and tape rings, record a
  focus frame, void the campaign if touched. This is the single most likely way to get a
  wrong-but-plausible number.
- **Rolling shutter.** Captures are parked-only, so within-frame motion smear should be absent; but
  vibration during "parked" (pumps, gantry settling) still skews rows. *Mitigate:* enforce a settle
  delay before capture; verify by comparing static-cap σ with and without an added dwell.
- **Plane / tilt / parallax.** The dominant systematic. Off-plane features map with
  `≈ Δz·tan(θ)` error. *Mitigate:* coplanar shimming, `Δz` logging, in-plane-only claims; and
  because far-edge combines worst px/mm with worst perspective, gate `max_mm` **per position**.
- **Thermal drift of ABS/printed boards.** ABS CTE ≈ 70–90 ppm/°C: a 10 °C swing shifts a 100 mm
  span by ~0.07–0.09 mm — enough to blow the ±0.05 and dent the ±0.10 gate. *Mitigate:* log ambient
  temp, characterize the reference pitch at the **same** temperature as validation, or use a
  low-CTE reference (glass/Invar/ceramic) for the tight tiers. A printed/ABS checkerboard is
  acceptable for ±0.25, marginal for ±0.10, and **should be replaced by glass** for ±0.05.
- **Homography extrapolation beyond calibrated region.** If validation positions sit outside the
  convex hull of calibration views, `H` extrapolates and error balloons. *Mitigate:* ensure
  calibration ChArUco views span the full bed incl. corners; flag any validation corner outside the
  calibrated hull.
- **Reference qualification error.** If `true_pitch`/`U_ref` is wrong, the whole campaign inherits a
  scale bias that looks like system error (or masks it). *Mitigate:* two-axis, two-location caliper
  averaging, cross-checked against a gauge block/pin; refuse tiers where `U_ref` fails 4:1.
- **Detector-path mismatch.** Checkerboard `cornerSubPix` and ChArUco corners have different
  sub-pixel biases; using the same artifact for both would hide this. Independence (Section 2)
  converts it from a hidden bias into a measured one.

---

## 9. What this protocol can and cannot prove

**Can prove:** in-plane point-position accuracy (bias + precision + worst-case) of the calibrated
map across the bed, at whichever of the three tolerance tiers the reference and the measured `σ_R`
support; and *where* on the bed accuracy degrades.

**Cannot prove:** height/3-D accuracy (single tilted plane map, no depth); accuracy at ±0.05 mm if
`σ_R` or reference `U_ref` do not clear the floor (report as *not certifiable* rather than pass);
production placement precision if the real workflow fixtures the part differently than the hand-
placed board; and anything outside the calibrated homography hull.
