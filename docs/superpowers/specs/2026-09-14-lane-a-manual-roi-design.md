# Lane A — Manual ROI via "mark the circle" — Design

**Status:** draft for review · 2026-09-14
**Builds on:** `2026-09-14-lane-a-dimensional-compensation-design.md` (v1 report-only, already built)
**Branch target:** a new `feat/lane-a-manual-roi` off `main`

## Goal
When Lane A's automatic ROI location fails (or the operator wants to override it), let the operator
**mark the Ø100 mm outer circle** on the captured still; the four feature ROIs (dot array,
checkerboard, concentric rings, pitch ruler) are then **derived from the known mm layout**, and the
run is analyzed. Because the outer circle is a known **Ø100 mm**, the marked radius also yields
`px_per_mm` — so a run can be analyzed **even without bed-plane calibration** (the circle is the
ruler), cross-checked against the registered sidecar `mm_per_px` when present.

## Why this is the right shape (verified in code — do not re-assume)
- The backend already accepts caller-supplied ROIs: `DimensionalAnalyzeRequest.rois`
  (`api/app.py:417`) → `analyze_run(run_dir, layer, stage, rois, nominals)`
  (`analysis/dimensional.py:299`).
- ROIs are derived from a circle center by `mm_box_to_px_rect(center, px_per_mm, box_mm)`
  (`dimensional.py:102`), exactly as `_auto_rois` does after `_locate_outer_circle` (HoughCircles,
  `dimensional.py:211`). So "mark the circle" = supply the center + a px_per_mm and reuse that math,
  skipping Hough.
- Nominal geometry is fixed: `DEFAULTS["outer_circle"]["diameter_mm"] == 100.0` (`dimensional.py:48`);
  the four feature mm-boxes are the same the auto path uses.
- `DimensionalReport` already carries `px_per_mm` and `mm_per_px` (`dimensional.py:87-88`); sidecar
  calibration is read by `_read_mm_per_px` (`dimensional.py:191`).
- The still is shown in the Analysis tab today; the square image viewer / lightbox already exists in
  the frontend (`RunsView`/`AnalysisView`, `.xsec` styling).

## Scope
**In:** the "mark the circle" override — backend request field + derivation, and the frontend circle
overlay with live-derived boxes. **Out (unchanged, separate increments):** on-powder validation, v2
RIP `rip_scale_x/y` write-back, per-box manual nudge, drawing 4 arbitrary boxes.

## Backend

### Request contract
Add an optional field to `DimensionalAnalyzeRequest` (`api/app.py`):
```python
class CircleAnchor(BaseModel):
    cx_px: float
    cy_px: float
    radius_px: float  # radius of the Ø100 mm outer circle, in pixels

class DimensionalAnalyzeRequest(BaseModel):
    # ...existing: layer, stage, rois, nominals...
    circle: CircleAnchor | None = None
```
Precedence in `analyze_run`: explicit `rois` (unchanged) > `circle` (new) > auto-location. `circle`
and `rois` are mutually exclusive in practice; if both are sent, `rois` wins (documented).

### Derivation (pure, tested)
New pure helpers in `dimensional.py`:
```python
def px_per_mm_from_circle(radius_px: float, diameter_mm: float) -> float:
    return (2.0 * radius_px) / diameter_mm

def rois_from_circle(center_px, px_per_mm, nominals) -> dict[str, list[int]]:
    # same loop as _auto_rois, but center + px_per_mm are given (no HoughCircles)
    return {feat: list(mm_box_to_px_rect(center_px, px_per_mm, box_mm)) for feat, box_mm in ...}
```
`analyze_run` gains a `circle` param. When `circle` is given and `rois` is not:
- `ppm = px_per_mm_from_circle(circle.radius_px, nominals["outer_circle"]["diameter_mm"])`
- `rois = rois_from_circle((circle.cx_px, circle.cy_px), ppm, nominals)`
- run the four analyzers with that `ppm`; status is `ok` (not `roi_failed`).

### Calibration cross-check (no false-green — data-contract rule #5)
Report gains `calibration_source: "circle" | "sidecar" | "circle+sidecar"` and, when both a marked
circle and a sidecar `mm_per_px` exist, a `calibration_warning` string if
`abs(ppm_circle - 1/mm_per_px)/ppm_circle` exceeds a tolerance (e.g. 3%). The number actually used
is the circle-derived `ppm` (the operator explicitly marked it); the sidecar is the cross-check.
When only the circle is marked and there's no sidecar, that's fine and explicit
(`calibration_source: "circle"`) — this is the case that unblocks uncalibrated runs.

### Persistence
`analysis/dimensional.json` gains `roi_source: "auto" | "manual_rois" | "circle"`, the `circle`
(when used), `calibration_source`, and `calibration_warning`. Re-opening a run restores the overlay
and makes re-analysis reproducible.

## Frontend

### Interaction (AnalysisView)
- An **ROI-edit mode**, entered automatically on a `roi_failed` report and via an **"Adjust ROIs"**
  button on any run. Shows the registered still in the square viewer with an **SVG circle overlay**:
  - drag the circle **body** to move the center; drag a **rim handle** to resize the radius;
  - the **four derived ROI boxes** (labeled dot / checker / rings / pitch) render live from the
    circle, updating as it moves — so the operator sees the fit before committing.
- **"Analyze with this circle"** posts `{circle: {cx_px, cy_px, radius_px}}` to
  `POST /api/analysis/{run}/dimensional`, then shows the returned report.
- Initial circle guess: center = image center, radius = ~40% of the smaller dimension (a visible
  starting point the operator drags into place). Coordinates are in the still's natural pixel space
  (map from the displayed/letterboxed image via its intrinsic size).

### Derived-box geometry (pure, tested)
A small TS helper `roiBoxesFromCircle(circle, layoutMm, diameterMm)` mirrors the backend's
`mm_box_to_px_rect` (center-relative, +y-mm-is-up → smaller pixel row) so the live overlay matches
exactly what the backend will compute. Unit-tested against backend numbers for a fixed circle.

### Honest states (preserved)
- `roi_failed` → "Auto-location failed — mark the outer circle" (actionable, opens ROI-edit mode),
  visually distinct from healthy.
- `calibration_warning` present → a warning chip: "circle scale differs from camera calibration by
  N% — using the circle." No silent disagreement.
- `no_capture` / `no_calibration` unchanged (a marked circle can now satisfy the scale even when
  `no_calibration` would otherwise apply — surface that transition clearly).

## TDD plan
**Backend (pure first):**
1. `px_per_mm_from_circle(radius_px=..., 100.0)` == `2·radius/100`. RED→GREEN.
2. `rois_from_circle(center, ppm, DEFAULTS)` equals `_auto_rois`'s output when `_auto_rois` is fed
   the same center (patch/seed the circle) — proves the manual path matches the auto math.
3. `analyze_run(..., circle=CircleAnchor(...))` on the real `first-good-test` fixture returns `ok`
   with `roi_source=="circle"` and the key metrics within tolerance of `results.csv` (parity).
4. Request round-trips `circle`; `rois` beats `circle`; calibration cross-check emits
   `calibration_warning` when circle vs sidecar disagree > tol, and none when they agree.
5. `no_calibration` + marked circle → `ok` with `calibration_source=="circle"` (the unblock case).

**Frontend:**
6. `roiBoxesFromCircle` unit test asserts the 4 boxes match the backend's `mm_box_to_px_rect` numbers
   for a fixed circle + `DEFAULTS` layout.
7. Report-parse → ROI-edit trigger on `roi_failed`; warning-chip on `calibration_warning`.
8. Theme-token check for the new overlay/chip CSS (no color literals).

**Real-data gate (data-contract rule #4):** before shipping, mark the circle on one actual
gold-standard capture in the hot folder and read the printed scale-X/Y + per-feature numbers.

## Definition of done
Operator opens a run whose auto-location failed (or clicks "Adjust ROIs"), drags the circle onto the
Ø100 outline with the four boxes snapping into place live, clicks "Analyze with this circle", and gets
the same dimensional report the auto path would — including on a run with no bed-plane calibration,
with an honest calibration-source label and a warning when the circle and sidecar disagree. Backend
and frontend geometry proven identical by tests; parity held against the known-good fixture; verified
once on a real capture.
