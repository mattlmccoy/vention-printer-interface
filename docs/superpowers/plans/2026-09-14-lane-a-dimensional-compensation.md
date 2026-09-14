# Lane A — Dimensional Accuracy & Compensation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Backend tasks
> run in a subagent (TDD, pytest, owns backend files only); frontend tasks are done in-session.
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** Print the dimensional test geometry on powder, capture it with the science cam, run the
vendored RFAM metrology on the registered still, and show a dimensional-accuracy + compensation
report in a new Analysis tab. Report-only (v1).

**Architecture:** New backend `analysis/` package (vendored `feature_analysis` + orchestration +
report persistence) exposed via `/api/analysis/{run}/dimensional`; new frontend `Analysis` view
(run list + report). No slicing, no auto-apply in v1.

**Tech stack:** Python/FastAPI backend (uv, pytest, numpy/opencv), React/TS frontend (node --test).

**Spec:** `docs/superpowers/specs/2026-09-14-lane-a-dimensional-compensation-design.md`

**Verified contracts (do not re-assume):**
- `analyze_dot_array(roi, px_per_mm, nominal_diameter_mm, nominal_spacing_mm, …) -> (summary, details)`;
  summary keys incl. `spacing_x_error_pct`, `spacing_y_error_pct`, `diameter_error_pct`,
  `spacing_x_mean_mm`, `avg_diameter_mm`, `num_blobs`, `algorithm_error`.
- `analyze_checkerboard(roi, px_per_mm, nominal_square_mm) -> (summary, details)`; keys incl.
  `angle_deg`, `checkerboard_angle_error_deg`, `mean_square_mm`, `square_error_pct`, `num_squares`,
  `found`, `algorithm_error`.
- `analyze_concentric_rings(roi, px_per_mm, nominal_line_width_mm, nominal_spacing_mm) -> (summary, details)`.
- `analyze_pitch_ruler(roi, px_per_mm, nominal_widths_x=[...]) -> (summary, details)`.
- `recommend_compensation_overall(...) -> str` (human text); scale computed as `1/(1+err_pct/100)`.
- Source: `code/rfam_tool/feature_analysis.py`. Nominals from `generate_dimensional_geometry.py`:
  dot Ø2.0 / pitch 6.0 mm; checkerboard 2.0 mm squares; rings 0.5 mm line / gap; outer circle Ø100 mm.
- **Parity fixture (real, captured):** `experiments/dim-acc-geometries/first-good-test/` has per-feature
  ROI crops (`dot_roi.png`, `checkerboard_roi.png`, …) + `results.csv` (dot row:
  `spacing_x_error_pct=-0.437860`, `spacing_y_error_pct=0.045567`, `diameter_error_pct=4.338251`,
  `num_blobs=25`), scanned at `px_per_mm=118.11`.
- Capture input = a recorded run's registered science-cam still; `px_per_mm = 1/sidecar.registered_space.mm_per_px`.
- **Compensation apply target is out of scope (v1 report-only).** The real target for v2 is the Meteor
  RIP `rip_scale_x`/`rip_scale_y` in `software/meteor/tools/config.json` — do NOT write it in v1.

---

## Phase 1 — Backend: vendored analysis core (subagent, TDD)

### Task 1: Vendor the metrology, proven by a parity test against the real fixture

**Files:**
- Create: `backend/vention_printer_interface/analysis/__init__.py`
- Create: `backend/vention_printer_interface/analysis/feature_analysis.py` (vendored)
- Create: `backend/tests/analysis/test_parity.py`
- Copy fixtures: `backend/tests/analysis/fixtures/first-good-test/{dot_roi.png,checkerboard_roi.png,results.csv}`

- [ ] **Step 1: Copy the parity fixtures** into the test tree (the real ROI crops + results.csv from
  `experiments/dim-acc-geometries/first-good-test/`). These are captured-from-reality, never invented.

- [ ] **Step 2: Write the failing parity test**

```python
# backend/tests/analysis/test_parity.py
import csv, math
from pathlib import Path
import cv2
from vention_printer_interface.analysis.feature_analysis import analyze_dot_array

FX = Path(__file__).parent / "fixtures" / "first-good-test"
PX_PER_MM = 118.11  # the fixture scan calibration (dimensional_main default)

def _expected(col: str) -> float:
    with open(FX / "results.csv") as f:
        row = next(csv.DictReader(f))
    return float(row[col])

def test_dot_array_matches_known_good_tool_output():
    roi = cv2.imread(str(FX / "dot_roi.png"))
    summary, _details = analyze_dot_array(
        roi, px_per_mm=PX_PER_MM, nominal_diameter_mm=2.0, nominal_spacing_mm=6.0)
    assert summary["num_blobs"] == _expected("num_blobs")
    assert math.isclose(summary["spacing_x_error_pct"], _expected("spacing_x_error_pct"), abs_tol=0.05)
    assert math.isclose(summary["spacing_y_error_pct"], _expected("spacing_y_error_pct"), abs_tol=0.05)
    assert math.isclose(summary["diameter_error_pct"], _expected("diameter_error_pct"), abs_tol=0.05)
```

- [ ] **Step 3: Run it — expect RED** (`ModuleNotFoundError: analysis.feature_analysis`).
  Run: `cd backend && uv run pytest tests/analysis/test_parity.py -q`  Expected: import error / fail.

- [ ] **Step 4: Vendor the module.** Copy `analyze_dot_array/analyze_checkerboard/analyze_concentric_rings/
  analyze_pitch_ruler/recommend_compensation_for_dot/recommend_compensation_overall` and their private
  helpers from `code/rfam_tool/feature_analysis.py` into
  `backend/vention_printer_interface/analysis/feature_analysis.py`. Header comment records provenance
  (source path + copied 2026-09-14). Keep signatures identical. Do not "improve" the algorithms.

- [ ] **Step 5: Run — expect GREEN.** If a metric drifts beyond tolerance, the copy diverged — fix the
  copy, do not loosen the assertion beyond measurement noise. Add a checkerboard parity assertion
  (`checkerboard_roi.png` → `square_error_pct`, `angle_deg`) once the dot one passes.

- [ ] **Step 6: Commit** `feat(analysis): vendor RFAM feature-analysis with parity test`.

### Task 2: Structured compensation extraction

**Files:** Create `backend/vention_printer_interface/analysis/compensation.py`; Test
`backend/tests/analysis/test_compensation.py`

- [ ] **Step 1: Failing test** — from a metrics dict, derive structured compensation:

```python
from vention_printer_interface.analysis.compensation import to_compensation

def test_scale_and_yaw_from_metrics():
    comp = to_compensation(
        dot={"spacing_x_error_pct": -0.437860, "spacing_y_error_pct": 0.045567},
        checkerboard={"angle_deg": 1.30, "checkerboard_angle_error_deg": 1.30})
    # scale = 1/(1+err/100): printed slightly small in X -> enlarge (>1)
    assert abs(comp.scale_x - (1/(1 - 0.437860/100))) < 1e-6
    assert abs(comp.scale_y - (1/(1 + 0.045567/100))) < 1e-6
    assert abs(comp.yaw_deg - 1.30) < 1e-6
    assert comp.human  # non-empty recommendation text

def test_deadband_and_missing():
    comp = to_compensation(dot={"spacing_x_error_pct": 0.01}, checkerboard={})
    assert comp.scale_x == 1.0            # inside 0.05% deadband -> no correction
    assert comp.yaw_deg is None           # no checkerboard -> no yaw
```

- [ ] **Step 2: RED** (`uv run pytest tests/analysis/test_compensation.py -q`).
- [ ] **Step 3: Implement** `to_compensation` (dataclass `Compensation{scale_x, scale_y, yaw_deg,
  deadband_pct=0.05, human, notes}`), mirroring `recommend_compensation_for_dot`'s math; yaw from the
  checkerboard angle only (dot rotation is NOT used, per the tool).
- [ ] **Step 4: GREEN.** **Step 5: Commit** `feat(analysis): structured scale/yaw compensation`.

### Task 3: Per-run analysis + persistence (ROI localization with manual fallback)

**Files:** Create `backend/vention_printer_interface/analysis/dimensional.py`; Test
`backend/tests/analysis/test_dimensional.py`

- [ ] **Step 1: Failing tests** for (a) the report schema round-trip (write→read
  `analysis/dimensional.json`), (b) ROI-from-layout math: given `px_per_mm`, outer-circle center, and a
  feature's known mm-box, return the correct pixel crop rect, (c) honest empty: a run with no
  gold-standard capture returns a report with `status="no_capture"` (NOT false-green zeros).
- [ ] **Step 2: RED.**
- [ ] **Step 3: Implement** `analyze_run(run_dir, *, layer=None, stage="post_jet", rois=None,
  nominals=DEFAULTS) -> DimensionalReport`:
  - pick the gold-standard capture (given layer/stage, else the first available), load the registered
    PNG, read `mm_per_px` from its sidecar → `px_per_mm`.
  - ROIs: if `rois` provided (manual `{feature: [x,y,w,h]}`) use them; else auto-locate: find the outer
    Ø100 mm circle (HoughCircles/contour) to anchor, map each feature's known mm-box → px. If
    auto-locate fails, return `status="roi_failed"` with a clear message (no fabricated metrics).
  - run the four `analyze_*`, assemble `{run, captured_from:{layer,stage}, px_per_mm, features:{dot,
    checkerboard,rings,pitch}, compensation:{...}, status:"ok", generated_utc, tool_provenance}`.
  - persist to `<run>/analysis/dimensional.json`.
- [ ] **Step 4: GREEN. Step 5: Commit** `feat(analysis): per-run dimensional analysis + persistence`.

---

## Phase 2 — Backend: API (subagent, TDD)

### Task 4: analysis endpoints

**Files:** Modify `backend/vention_printer_interface/api/app.py`; Test
`backend/tests/api/test_analysis_api.py`

- [ ] **Step 1: Failing FastAPI tests** (TestClient): `GET /api/analysis/{run}/dimensional` on an
  un-analyzed run → 404 or `{status:"not_run"}`; `POST /api/analysis/{run}/dimensional` on a run with a
  gold-standard capture → 200 with a report; bad run → 400; the POST accepts optional
  `{layer, stage, rois, nominals}`.
- [ ] **Step 2: RED. Step 3: Implement** both endpoints delegating to `analyze_run` / reading the
  persisted json; reuse the existing run-path validation (`(root/run).resolve().parent == root`).
- [ ] **Step 4: GREEN. Step 5: run full backend suite** (`uv run pytest -q`) — all green.
  **Step 6: Commit** `feat(api): dimensional analysis endpoints`.

---

## Phase 3 — Frontend: Analysis tab (in-session, TDD where logic is pure)

### Task 5: Analysis view + tab + run list

**Files:** Modify `frontend/src/App.tsx` (add view `analysis`, tab label "Analysis", `#analysis`
deep-link); Create `frontend/src/components/views/AnalysisView.tsx`; Modify `frontend/src/lib/api.ts`
(add `analysisGet`, `analysisRun`, `DimensionalReport` type).

- [ ] **Step 1:** add the `analysis` view to the `View` type + hash allow-list + tab group (next to
  Runs/Setup), rendering `<AnalysisView>`.
- [ ] **Step 2:** AnalysisView shell: reuse the Runs run-list (extract or duplicate the list), select a
  run, fetch its report (`analysisGet`). Build clean (`npm run build`). Screenshot `#analysis`.

### Task 6: Lane A report UI

**Files:** Modify `AnalysisView.tsx`; Create `frontend/src/lib/analysis.ts` + `analysis.test.ts`.

- [ ] **Step 1: Failing test** for `analysis.ts` pure helpers (format a report → stat-tile rows;
  compensation → display strings; status → banner kind). `node --test`.
- [ ] **Step 2: RED → Step 3: implement helpers → GREEN.**
- [ ] **Step 4:** Report UI: "Analyze this run" button (calls `analysisRun`, spinner); **compensation
  card** (scale X, scale Y, yaw°, human-readable line, copy button, "apply upstream in CAD/slicer /
  RIP config" note — no auto-apply); **per-feature stat tiles** (staged fixed-size); **overlay
  viewer** reusing the lightbox square; honest **empty/`no_capture`/`roi_failed`** states, each
  visually distinct (no false-green). Use theme tokens only.
- [ ] **Step 5:** `npx tsc --noEmit`, `node --test`, `npm run build`; screenshot the report (use a
  fixture run). **Step 6: Commit** `feat(analysis): Lane A report UI in the Analysis tab`.

---

## Phase 4 — Integration & honest verification

### Task 7: real-data run + known-deviation check

- [ ] Analyze the real known-good fixture end-to-end through the API and confirm the numbers match the
  tool (already covered by parity, now through the full stack).
- [ ] Use `gold_standard_720dpi_testing_XY_scaling` (the salvaged known-XY-scaled target) as a
  known-deviation input and confirm Lane A reports a scale correction in the expected direction.
- [ ] When hardware is available: print the gold standard on powder, capture, analyze, read the printed
  numbers (spec DoD). Until then, document that the on-powder path is unverified.
- [ ] Final code review; update memory + spec status to "implemented (v1, report-only)".

## Self-review notes
- Spec coverage: A/all-four/reuse-capture/report-only all mapped. ✓
- Types consistent: `analyze_*` returns `(summary, details)`; `Compensation` fields fixed across tasks. ✓
- No false-green: `no_capture` / `roi_failed` statuses required and tested. ✓
- Out of scope kept out: no RIP-config write, no slicing, no lanes B/C. ✓
