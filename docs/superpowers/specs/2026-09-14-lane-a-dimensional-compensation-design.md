# Lane A — Dimensional Accuracy & Compensation (Analysis tab) — Design

**Status:** draft for review · 2026-09-14
**Branch target:** feat/ui-redesign (or a new feat/analysis-lane-a off it)

## Goal
Print the dimensional test geometry **directly onto powder**, capture it with the science
camera, and run the existing RFAM metrology (`feature_analysis.py`) on that image to produce a
**dimensional-accuracy + geometric-compensation report** — surfaced in a new **Analysis** tab and
tracked across runs. This replaces the old paper-print → flatbed-scan → analyze workflow with an
on-machine, on-powder one that is true to actual printing.

## Scope (v1) — decided with Matt
- **Report only.** Measure and report structured compensation (scale-X/Y, checkerboard yaw) + the
  human-readable recommendation. The operator applies it upstream (CAD/slicer). See "Contract
  reality" for why we cannot auto-apply yet.
- **All four features** of the gold standard: dot array, checkerboard, concentric rings, pitch ruler.
- **Capture via a normal recorded print** of the gold-standard job (reuse the existing capture
  pipeline); the post-jet science-cam still is the analysis input.
- Out of scope for v1: applying/baking compensation, Lanes B (part deviation) & C (ink conc.),
  layerwise/live analysis.

## Contract reality (verified in code — do not re-assume)
1. **The console does NOT slice.** It consumes pre-sliced 2-bit TIFF stacks
   (`<job>_Page<N>_Clr<plane>.tif`, mode L, BitsPerSample 2) + `job_info.json`
   (`backend/vention_printer_interface/jobs/store.py:1-51`). There is no geometry step to apply a
   scale/rotation to.
2. **`print_settings` has no compensation field** (`control/print_settings.py` — no scale/rotation/
   compensation/skew keys). So the *console* has nowhere to "write compensation." → v1 is report-only.
   BUT compensation IS applied elsewhere: the **Meteor RIP** tool scales geometry at slice time via
   `rip_scale_x`/`rip_scale_y` in `code/…/software/meteor/tools/config.json` (currently
   `rip_scale_x: 1.004428, rip_scale_y: 0.999559` — someone already hand-entered a Lane-A-style
   1.0044 X correction). So the **real apply target is that RIP config**, and a **v2** could write it
   directly (the RIP re-slices with the new scale). v1 still reports; v2 = "apply to RIP config".
3. **Test geometry already exists as a job:** `…/rfam-web/Hot Folder/20260414_110925_gold_standard_720dpi`
   — `job_info.json`: 1 TIFF, 720 dpi, 2 bpp, source `gold_standard_720dpi.png`. (The live hot
   folder is the Mac `…/rfam-web/Hot Folder`; the `…/meteor/tools/C:\Users\…\Hot Folder` path is a
   stray Windows-path-literal folder artifact, not a real hot folder.)
4. **Nominal dims** (`code/rfam_tool/generate_dimensional_geometry.py`): outer circle Ø100 mm; dot
   pitch 6.0 mm; checkerboard 8×8 @ 2.0 mm squares; rings 0.5 mm line / 0.5 mm gap; pitch base 6×6 mm.
   These are physical mm (DPI-independent) and are the nominals fed to `feature_analysis`.
5. **`feature_analysis.py` API** (`code/rfam_tool/feature_analysis.py`):
   - `analyze_dot_array(roi, px_per_mm, nominal_diameter_mm, nominal_spacing_mm, …) -> dict`
   - `analyze_checkerboard(roi, px_per_mm, …) -> dict` (square size + yaw via cv2 corners)
   - `analyze_concentric_rings(roi, px_per_mm, …) -> dict`
   - `analyze_pitch_ruler(roi, px_per_mm, …) -> dict`
   - `recommend_compensation_for_dot(summary) -> str` and `recommend_compensation_overall(...)` return
     **human-readable text** (e.g. "Apply a scale factor of 1.0044 in X"); the scale is computed
     internally as `1/(1+err_pct/100)`. → we need a small **structured** extraction (numbers), not
     just the text. Dot rotation is explicitly NOT used for yaw; **checkerboard angle is the yaw
     source**.
   - Inputs are per-feature ROI arrays + `px_per_mm`. The registered science-cam still carries
     `registered_space.mm_per_px` in its sidecar → `px_per_mm = 1/mm_per_px`.
6. **Real fixture for TDD exists:** `experiments/dim-acc-geometries/first-good-test/{results.csv,
   raw.csv,compensation-report.txt,*_overlay.png,*_roi.png}` — a known-good tool output on a real
   scan. Use it to pin our wrapper's numbers.

## Architecture

### Backend
- **Vendor the metrology, don't import the loose repo.** `code/rfam_tool` is unpackaged with several
  duplicate copies. Copy the specific `analyze_*` + `recommend_*` functions (and their private
  helpers) into a new console module `backend/vention_printer_interface/analysis/dimensional.py`,
  trimmed to the pieces Lane A uses. Keeps the console self-contained and testable; records
  provenance in a header comment citing the source file + date.
- **New module `analysis/dimensional.py`:**
  - `analyze_registered_still(image, mm_per_px, nominals) -> DimensionalReport` — locate each
    feature's ROI from the known layout, run the four analyzers, assemble metrics.
  - `to_compensation(report) -> Compensation` — structured `{scale_x, scale_y, yaw_deg, deadband,
    notes[]}` derived from spacing/size errors + checkerboard yaw (mirrors the tool's math), plus the
    human-readable text.
- **ROI localization (design point + risk):** the pattern layout is known in mm; anchor it by
  locating the Ø100 mm outer circle (Hough/contour) in the registered image, then map each feature's
  mm-box → pixels via `px_per_mm`. Fallback: manual ROI entry (parity with the old GUI) if
  auto-locate fails. v1 must degrade gracefully, not emit false numbers (data-contract rule #5).
- **Persistence:** write `analysis/dimensional.json` into the run dir (alongside `vision/`), schema
  = `{run, captured_from: {layer, stage}, mm_per_px, features: {...}, compensation: {...},
  generated_utc, tool_provenance}`.
- **API:** `POST /api/analysis/{run}/dimensional` (run/refresh; body optionally picks layer/stage +
  manual ROIs), `GET /api/analysis/{run}/dimensional` (fetch report, 404 if not run yet).

### Frontend
- **New `Analysis` tab** (view key `analysis`, label "Analysis"): same run list as Runs on the left;
  right pane = the selected run's analysis. Lane A card:
  - "Dimensional accuracy" header + "Analyze this run" button (calls POST; shows spinner).
  - **Compensation card:** scale-X, scale-Y, yaw°, each with the human-readable line; a copy button.
    Clearly labeled "apply upstream in your CAD/slicer" (no auto-apply in v1).
  - **Per-feature stat tiles** (dot spacing/size err %, checkerboard square + yaw, ring line width,
    pitch min-resolvable), staged fixed-size.
  - **Overlay viewer:** the registered still with the analyzer overlay (reuse the lightbox square).
  - **Empty/failed states distinct from healthy** (no false-green): "not analyzed yet", "couldn't
    locate the pattern", "no gold-standard capture in this run" are each visually distinct.
- Deep-link `#analysis` + `?run=` for capture/tooling parity.

## Preconditions & risks (call out honestly)
- **Calibration dependency:** trustworthy `mm_per_px` + bed-plane registration from Setup. If a run's
  capture isn't registered, Lane A can't measure — surface that, don't guess.
- **FOV / resolution:** the science cam must capture the full Ø100 mm pattern at enough px/mm for the
  0.5 mm ring lines. Needs a real feasibility check on hardware; note in UI if `px_per_mm` is too low.
- **On-powder contrast:** a single 2-bit binder layer on powder may have low edge contrast vs a
  paper print — segmentation may need tuning. The real-fixture TDD is paper; add a captured on-powder
  fixture once available and treat paper params as a starting point.
- **ROI auto-location** may fail on partial / low-contrast frames → manual-ROI fallback required.

## TDD plan
1. **Structured compensation extraction** (pure): from a metrics dict with known spacing errors,
   assert `scale_x/scale_y` = `1/(1+err/100)` within the deadband, yaw from checkerboard. RED→GREEN.
2. **Report schema** round-trips (set/get, missing → 404-ish empty, not false-green).
3. **Parity fixture:** run `analyze_*` (vendored) against the real `first-good-test` input and assert
   the key metrics match `results.csv` within tolerance — proves the vendored copy matches the tool.
4. **ROI-from-layout math:** mm-box → px given `px_per_mm` + circle center.
5. Frontend: analysis lib unit tests (parse report → tiles), theme-token check for any new UI.
6. **Real-data integration run** before shipping: analyze an actual on-powder gold-standard capture
   and read the printed numbers (data-contract rule #4).

## Definition of done (v1)
- Print gold-standard → recorded run → "Analyze this run" produces a dimensional report with
  scale-X/Y + yaw + per-feature metrics, persisted and shown in the Analysis tab, with honest
  empty/failure states. Numbers validated against the known-good fixture and one real on-powder run.
