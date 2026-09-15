# Lane A — Manual ROI (mark-the-circle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator mark the Ø100 mm outer circle on a captured still; derive the 4 feature ROIs + `px_per_mm` from it (so uncalibrated runs work), and analyze — with an honest sidecar cross-check.

**Architecture:** Small pure helpers in `analysis/dimensional.py` (`px_per_mm_from_circle`, `rois_from_circle`); a `circle` override threaded through `analyze_run`; a `CircleAnchor` request model; a mirrored TS geometry helper; an SVG circle overlay in `AnalysisView`. Precedence: explicit `rois` > `circle` > auto-location.

**Tech Stack:** Python/FastAPI/pydantic/cv2/numpy backend (uv, pytest); React/TS frontend (node --test, theme tokens).

**Spec:** `docs/superpowers/specs/2026-09-14-lane-a-manual-roi-design.md`

---

## File Structure
- Modify: `backend/vention_printer_interface/analysis/dimensional.py` — add `px_per_mm_from_circle`, `rois_from_circle`, `circle`/`calibration` handling in `analyze_run`; report gains `roi_source`, `circle`, `calibration_source`, `calibration_warning`.
- Modify: `backend/vention_printer_interface/api/app.py` — `CircleAnchor` model + `DimensionalAnalyzeRequest.circle`; pass `circle` to `analyze_run`.
- Test: `backend/tests/analysis/test_dimensional.py` (or the existing analysis test module) — pure helpers, circle path, precedence, calibration cross-check, parity.
- Create: `frontend/src/lib/roi.ts` + `frontend/src/lib/roi.test.ts` — `roiBoxesFromCircle` mirroring the backend.
- Modify: `frontend/src/components/views/AnalysisView.tsx` — ROI-edit mode + SVG circle overlay + "Analyze with this circle".
- Modify: `frontend/src/lib/api.ts` — `analysisRun` accepts a `circle` body.
- Modify: `frontend/src/styles.css` — overlay + warning-chip styles (theme tokens only).

---

### Task 1: Pure geometry helpers (backend)

**Files:**
- Modify: `backend/vention_printer_interface/analysis/dimensional.py`
- Test: `backend/tests/analysis/test_dimensional.py`

- [ ] **Step 1: Write the failing test**
```python
def test_px_per_mm_from_circle():
    from vention_printer_interface.analysis.dimensional import px_per_mm_from_circle
    # Ø100 mm circle spanning 500 px radius -> 1000 px across 100 mm -> 10 px/mm
    assert px_per_mm_from_circle(radius_px=500.0, diameter_mm=100.0) == 10.0

def test_rois_from_circle_matches_mm_box_math():
    from vention_printer_interface.analysis.dimensional import rois_from_circle, mm_box_to_px_rect, DEFAULTS
    center, ppm = (400.0, 300.0), 8.0
    rois = rois_from_circle(center, ppm, DEFAULTS)
    # every feature ROI equals mm_box_to_px_rect for that feature's mm box
    for feat, box_mm in DEFAULTS["features"].items():   # adjust to the real nominals layout key
        assert rois[feat] == list(mm_box_to_px_rect(center, ppm, tuple(box_mm)))
    assert set(rois) == {"dot_array", "checkerboard", "concentric_rings", "pitch_ruler"}
```
(Adjust the nominals-layout access to match how `_auto_rois` iterates the feature mm-boxes — read `_auto_rois` first and mirror its exact source of `box_mm`.)

- [ ] **Step 2: Run test to verify it fails**
Run: `cd backend && uv run pytest tests/analysis/test_dimensional.py -k "px_per_mm_from_circle or rois_from_circle" -q`
Expected: FAIL (ImportError: names not defined).

- [ ] **Step 3: Write minimal implementation** in `dimensional.py` (near `mm_box_to_px_rect` / `_auto_rois`):
```python
def px_per_mm_from_circle(radius_px: float, diameter_mm: float) -> float:
    """px/mm implied by the marked Ø``diameter_mm`` outer circle (radius in px)."""
    return (2.0 * radius_px) / diameter_mm


def rois_from_circle(
    center_px: tuple[float, float], px_per_mm: float, nominals: dict[str, Any]
) -> dict[str, list[int]]:
    """The 4 feature ROIs from a known circle center — same math as _auto_rois, no HoughCircles."""
    rois: dict[str, list[int]] = {}
    for feature, box_mm in _feature_boxes(nominals):   # reuse whatever _auto_rois iterates
        rois[feature] = list(mm_box_to_px_rect(center_px, px_per_mm, box_mm))
    return rois
```
If `_auto_rois` inlines the feature/box iteration, extract it into a shared `_feature_boxes(nominals)` generator and have BOTH call it (DRY) — do that extraction as part of this step, keeping `_auto_rois` behavior identical.

- [ ] **Step 4: Run test to verify it passes**
Run: `cd backend && uv run pytest tests/analysis/test_dimensional.py -k "px_per_mm_from_circle or rois_from_circle" -q`
Expected: PASS.

- [ ] **Step 5: mypy + ruff, then commit**
Run: `cd backend && uv run mypy vention_printer_interface && uv run ruff check vention_printer_interface/analysis/dimensional.py`
```bash
git add backend/vention_printer_interface/analysis/dimensional.py backend/tests/analysis/test_dimensional.py
git commit -m "feat(lane-a): pure circle->px_per_mm and circle->ROIs helpers"
```

---

### Task 2: `circle` override in `analyze_run` + report fields

**Files:**
- Modify: `backend/vention_printer_interface/analysis/dimensional.py` (`analyze_run`, `DimensionalReport`)
- Test: `backend/tests/analysis/test_dimensional.py`

- [ ] **Step 1: Write the failing test** (uses the real `first-good-test` fixture run dir, or a crafted run):
```python
def test_analyze_run_with_circle_is_ok_and_labels_source(first_good_test_run):  # existing fixture
    from vention_printer_interface.analysis.dimensional import analyze_run
    circle = {"cx_px": CX, "cy_px": CY, "radius_px": R}   # values that frame the fixture's circle
    rep = analyze_run(first_good_test_run, circle=circle)
    assert rep.status == "ok"
    assert rep.roi_source == "circle"
    assert rep.px_per_mm == (2 * R) / 100.0
    assert rep.calibration_source in ("circle", "circle+sidecar")

def test_analyze_run_circle_works_without_calibration(run_without_sidecar_mm_per_px):
    rep = analyze_run(run_without_sidecar_mm_per_px, circle={"cx_px": CX, "cy_px": CY, "radius_px": R})
    assert rep.status == "ok" and rep.calibration_source == "circle"

def test_calibration_warning_on_disagreement(run_with_sidecar):
    # circle radius chosen so circle px/mm differs >3% from sidecar 1/mm_per_px
    rep = analyze_run(run_with_sidecar, circle={"cx_px": CX, "cy_px": CY, "radius_px": R_off})
    assert rep.calibration_warning and "%" in rep.calibration_warning

def test_explicit_rois_beat_circle(first_good_test_run):
    rep = analyze_run(first_good_test_run, rois=SOME_ROIS, circle={"cx_px":1,"cy_px":1,"radius_px":1})
    assert rep.roi_source == "manual_rois"
```

- [ ] **Step 2: Run → verify fails** (`analyze_run` has no `circle` kwarg; report has no `roi_source`). 
Run: `cd backend && uv run pytest tests/analysis/test_dimensional.py -k circle -q` → FAIL.

- [ ] **Step 3: Implement.** Add fields to `DimensionalReport`:
```python
    roi_source: str = "auto"           # "auto" | "manual_rois" | "circle"
    circle: dict[str, float] | None = None
    calibration_source: str | None = None   # "sidecar" | "circle" | "circle+sidecar"
    calibration_warning: str | None = None
```
Add `circle: dict[str, float] | None = None` param to `analyze_run` (keyword-only). Rework the calibration/ROI section so precedence and the no-calibration bypass are correct:
```python
    sidecar_mm_per_px = _read_mm_per_px(_sidecar_path_for(run_dir, registered_rel))
    image = cv2.imread(str(image_path))
    if image is None:
        return _fail(run, "no_capture", f"capture image unreadable: {registered_rel}")

    CAL_TOL = 0.03  # 3% agreement band between circle- and sidecar-derived scale
    roi_source = "auto"
    calibration_source: str | None = None
    calibration_warning: str | None = None

    if rois is not None:
        roi_source = "manual_rois"
        if sidecar_mm_per_px is None:
            return _fail(run, "no_calibration", "manual rois need registered mm_per_px", ...)
        px_per_mm = 1.0 / sidecar_mm_per_px
        calibration_source = "sidecar"
    elif circle is not None:
        roi_source = "circle"
        px_per_mm = px_per_mm_from_circle(circle["radius_px"], nominals["outer_circle"]["diameter_mm"])
        rois = rois_from_circle((circle["cx_px"], circle["cy_px"]), px_per_mm, nominals)
        if sidecar_mm_per_px is not None:
            calibration_source = "circle+sidecar"
            rel = abs(px_per_mm - 1.0 / sidecar_mm_per_px) / px_per_mm
            if rel > CAL_TOL:
                calibration_warning = (
                    f"circle scale differs from camera calibration by {rel * 100:.1f}% — using the circle"
                )
        else:
            calibration_source = "circle"
    else:
        if sidecar_mm_per_px is None:
            return _fail(run, "no_calibration", "...not registered...", captured_from=..., )
        px_per_mm = 1.0 / sidecar_mm_per_px
        calibration_source = "sidecar"
        rois = _auto_rois(image, px_per_mm, nominals)
        if rois is None:
            return _fail(run, "roi_failed", "could not auto-locate the Ø100 outer circle; mark the circle", ...)
```
Thread `roi_source`, `circle`, `calibration_source`, `calibration_warning`, `mm_per_px=sidecar_mm_per_px` into the successful `DimensionalReport(...)` constructor at the end of `analyze_run`. Keep every existing behavior for the auto/manual-rois paths identical.

- [ ] **Step 4: Run → verify passes.** `cd backend && uv run pytest tests/analysis/test_dimensional.py -k circle -q` → PASS. Then the whole analysis module: `uv run pytest tests/analysis -q`.

- [ ] **Step 5: mypy + ruff + commit.**
```bash
cd backend && uv run mypy vention_printer_interface && uv run ruff check vention_printer_interface/
git add -A backend && git commit -m "feat(lane-a): circle override + calibration cross-check in analyze_run"
```

---

### Task 3: API request model wiring

**Files:**
- Modify: `backend/vention_printer_interface/api/app.py`
- Test: `backend/tests/test_api_jobs.py` or the analysis API test module

- [ ] **Step 1: Failing test** (TestClient): POST `/api/analysis/{run}/dimensional` with `{"circle": {"cx_px":..,"cy_px":..,"radius_px":..}}` on a run with a capture → 200, body `roi_source == "circle"`, `px_per_mm == 2R/100`. (Use the smallest real fixture run available; if none, assert the request model accepts `circle` and passes it through via a monkeypatched `analyze_run`.)

- [ ] **Step 2: Run → fails** (`circle` rejected by the model / ignored).

- [ ] **Step 3: Implement** in `app.py`:
```python
class CircleAnchor(BaseModel):
    cx_px: float
    cy_px: float
    radius_px: float

class DimensionalAnalyzeRequest(BaseModel):
    # ...existing fields...
    circle: CircleAnchor | None = None
```
In `analysis_dimensional_run`, pass it through:
```python
    report = analyze_run(
        run_dir, layer=req.layer, stage=req.stage, rois=req.rois,
        circle=req.circle.model_dump() if req.circle else None, nominals=nominals,
    )
```

- [ ] **Step 4: Run → passes.** `cd backend && uv run pytest tests/ -k "dimensional or analysis" -q`.

- [ ] **Step 5: mypy + ruff + commit.**

---

### Task 4: Frontend geometry helper (mirrors backend)

**Files:**
- Create: `frontend/src/lib/roi.ts`, `frontend/src/lib/roi.test.ts`

- [ ] **Step 1: Failing test** (`roi.test.ts`): for `circle={cx:400,cy:300,radius:400}` and the gold-standard layout, `roiBoxesFromCircle` returns boxes equal to the backend's `mm_box_to_px_rect` numbers (hard-code the expected ints computed from the same formula: `x=round(cx + x_mm*ppm)`, `y=round(cy - y_mm*ppm)`, `w=round(w_mm*ppm)`, `h=round(h_mm*ppm)`, `ppm = 2*radius/100`).

- [ ] **Step 2: Run → fails.** `cd frontend && node --experimental-strip-types --test src/lib/roi.test.ts`.

- [ ] **Step 3: Implement** `roi.ts`:
```ts
export interface Circle { cx: number; cy: number; radius: number; }
export interface Box { x: number; y: number; w: number; h: number; }
// feature mm-boxes [x_mm(center-rel), y_mm(up +), w_mm, h_mm], mirrored from backend DEFAULTS
export const GOLD_LAYOUT_MM: Record<string, [number, number, number, number]> = { /* fill from DEFAULTS */ };
export function pxPerMmFromCircle(radius: number, diameterMm = 100): number { return (2 * radius) / diameterMm; }
export function roiBoxesFromCircle(c: Circle, layout = GOLD_LAYOUT_MM, diameterMm = 100): Record<string, Box> {
  const ppm = pxPerMmFromCircle(c.radius, diameterMm);
  const out: Record<string, Box> = {};
  for (const [feat, [xm, ym, wm, hm]] of Object.entries(layout)) {
    out[feat] = { x: Math.round(c.cx + xm * ppm), y: Math.round(c.cy - ym * ppm), w: Math.round(wm * ppm), h: Math.round(hm * ppm) };
  }
  return out;
}
```
Copy `GOLD_LAYOUT_MM` values from the backend `DEFAULTS` feature boxes verbatim (single source of truth is the backend; note the provenance in a comment).

- [ ] **Step 4: Run → passes.**

- [ ] **Step 5: Commit.**

---

### Task 5: AnalysisView ROI-edit mode + SVG overlay

**Files:**
- Modify: `frontend/src/components/views/AnalysisView.tsx`, `frontend/src/lib/api.ts`, `frontend/src/styles.css`

- [ ] **Step 1 (UI — verification is a browser check, not a unit test; state that):** Add to `AnalysisView`:
  - state `editing` (bool), `circle` ({cx,cy,radius} in the still's natural px), entered when report `status==="roi_failed"` or via an "Adjust ROIs" button.
  - Render the registered still in the `.xsec` square; overlay an `<svg>` sized to the image's natural dimensions (viewBox = natural px) with: a `<circle>` (draggable body), a rim handle (`<circle>` at cx+radius), and the 4 derived boxes from `roiBoxesFromCircle(circle)` as labeled `<rect>`s.
  - Pointer handlers: drag body → move cx,cy; drag rim → set radius = dist(center, pointer). Clamp to image bounds.
  - Initial guess: `cx=natW/2, cy=natH/2, radius=0.4*min(natW,natH)`.
  - "Analyze with this circle" → `api.analysisRun(run, { circle: { cx_px: circle.cx, cy_px: circle.cy, radius_px: circle.radius } })`, then show the returned report; exit editing.

- [ ] **Step 2: `api.ts`** — extend `analysisRun` to accept an optional body `{ circle?: {cx_px,cy_px,radius_px} }` and POST it.

- [ ] **Step 3: CSS** (`.roi-overlay`, `.roi-box`, `.roi-circle`, `.roi-handle`, `.cal-warn`) using theme tokens only (`--accent`, `--muted`, `--warn`, `--line-strong`, `--scrim`). No color literals (theme.test.ts enforces).

- [ ] **Step 4: Verify in browser** (the gate for this UI task): start vpi-serve + vite, open `#analysis`, select a run, enter ROI-edit, drag the circle so the 4 boxes frame the features, click "Analyze with this circle", confirm a report renders. Confirm the warning chip appears when a run has a mismatched sidecar. `npx tsc --noEmit` + `node --test 'src/**/*.test.ts'` (theme guard) green.

- [ ] **Step 5: Commit.**

---

### Task 6: Honest states + warning chip

**Files:** `frontend/src/components/views/AnalysisView.tsx`, `frontend/src/lib/analysis.ts` (+ its test)

- [ ] **Step 1: Failing test** in `analysis.test.ts`: a small pure mapper `roiEditPrompt(status)` returns the actionable copy for `roi_failed` ("Auto-location failed — mark the outer circle") and `null` for `ok`; `calibrationChip(report)` returns the warning text when `calibration_warning` present, else `null`.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** the pure mappers; wire them into `AnalysisView` (the `roi_failed` state auto-opens edit mode and shows the prompt; the chip renders when present).
- [ ] **Step 4: Run → passes** + `tsc` clean.
- [ ] **Step 5: Commit.**

---

### Task 7: Real-data verification gate (data-contract rule #4)

- [ ] **Step 1:** Start vpi-serve against the real hot folder; open `#analysis`; pick an actual gold-standard capture run.
- [ ] **Step 2:** Mark the circle on the real Ø100 outline; Analyze; **read the printed scale-X/Y + per-feature numbers**; confirm they are plausible and that `calibration_source`/`calibration_warning` reflect reality. Screenshot for the record.
- [ ] **Step 3:** If numbers are implausible, do NOT ship — investigate segmentation/px_per_mm before merge.

---

## Self-review notes
- Types/names consistent: `roi_source` ∈ {auto, manual_rois, circle}; `calibration_source` ∈ {sidecar, circle, circle+sidecar}; `circle` keys `cx_px/cy_px/radius_px` everywhere (backend model, report, frontend api).
- No placeholders except the two clearly-marked "fill `GOLD_LAYOUT_MM`/nominals-iteration from backend DEFAULTS" steps — both instruct copying the single source of truth (backend), which the implementer reads in Task 1.
- Spec requirement coverage: interaction (T5), circle→px_per_mm+ROIs (T1), override+precedence+cross-check (T2), request contract (T3), geometry parity (T4/T1), honest states (T6), real-data gate (T7). Persistence of new report fields is covered by T2 (they're on `DimensionalReport`, which `analyze_run` already persists via the existing write path — verify that write path serializes the new fields in T2 Step 4).
