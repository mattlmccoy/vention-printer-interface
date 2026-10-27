# Calibration History Implementation Plan

**Goal:** See the most recent and every past science-camera calibration in the console long after it was made: its report, its photos, its self-check and its validations, with "use this calibration" to restore one. Matt (2026-10-26): "not a 'find the cal file' button but actually route to where they are stored and allow viewing them (as well as validation)".

**Architecture:**
- A filesystem archive `experiments/vision_calibrations/<version>/`, written when a calibration is saved. It holds:
  - `calibration.json`, `report.json`;
  - the JPEGs `capture`, `raw`, `corrected`, `residuals`.
- Validations stay where 0.19.3 put them (`experiments/validations/<version>/<stamp>/`) and now also keep the unannotated photo as `raw.jpg`.
- One routes module serves the list, the detail, the images and activate. A Settings → Calibrations page renders them.

## Data contract (probed 2026-10-26 on the real experiments root)

| Source | Shape / evidence |
|---|---|
| `.vision_calibration.json` | `registration.py:save_calibration`. Real file: version `cal-20261026T192538Z`, provenance has `valid_region_mm`, `self_check`, `scale_ratio`, `n_views`, `reprojection_rms_mm`. |
| `.autocal_last_sweep.json` | `autocal_routes.py` solve. `saved_at` ISO, `result` (the solve output), `views[]`. Real: one file, `saved_at` 2026-10-26T19:11Z = 15:11 EDT, before the save at 15:25. |
| `.vision_validation.json` | `{calibration_version, scale:{max_mm, rms_mm, passed, target_mm, scale_bias}}`. Real: numbers only for `cal-20261026T192538Z`, no photo. |
| `validations/<version>/<stamp>/` | `app.py:_store_validation` (0.19.3+): `annotated.jpg` and `result.json`. Real root: folder absent; that validation predates 0.19.3. |
| sweep photos | `~/.vpi-cache/autocal_last/NN_<mm>.png`, 14 real files, 5120 × 3840. |

## Tasks (red → green each)

1. **`vision/calibration_history.py`**
   - Functions: `archive_calibration`, `list_calibrations`, `calibration_detail`, `load_archived`.
   - Tests: round trip; newest first; active flag; the active calibration is listed even when not archived; validations counted, with the latest one summarised; legacy numbers-only validation labelled; path traversal refused.
2. **Autocal save archives:** report plus the 4 images from the session.
   - API test: after save, the folder holds `calibration.json`, `report.json` and 4 JPEGs.
3. **Validation keeps `raw.jpg`**, and its route serves it.
4. **Routes** `api/calibration_history_routes.py`:
   - `GET /api/vision/calibrations` and `/{version}`;
   - `GET /{version}/images/{name}.jpg`;
   - `POST /{version}/activate`, which refuses a mismatched `expect_image_size` with 409 and sets the live calibration.
5. **Backfill** of the active calibration when it isn't archived:
   - always copy `calibration.json`;
   - copy the report and photos only when the sweep file provably produced it (sweep `saved_at` before the version time, and the same `shift_rms_mm`).
6. **Frontend:**
   - pure `calibration_history.ts` (rows, verdicts, restore confirm text), tested with node;
   - `CalibrationHistoryPanel`, with a Settings item "Calibrations".
7. **Wrap-up:** version 0.22.0 plus changelogs, gates, a real-data run against a copy of the real experiments root, a browser check, then the PR stacked on #140.

## Rules
- Never show an unknown value as healthy: no validation is "not validated", never a pass.
- A numbers-only legacy validation says so ("photo not kept before 0.19.3").
- Restore never happens silently: a confirm dialog names the photo size, and the server refuses a size mismatch when the client states one.
