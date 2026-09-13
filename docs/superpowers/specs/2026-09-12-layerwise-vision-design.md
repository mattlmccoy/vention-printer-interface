# Layerwise Vision — Design (Slice 1: Capture + Register + Store)

**Date:** 2026-09-12 (updated 2026-09-13: finalized cameras + corrected registration pipeline)
**Status:** Approved 2026-09-12; cameras finalized 2026-09-13
**Author:** Matt McCoy (with Claude)
**Platforms:** macOS, Windows, Linux. The operator is cross-platform (`install.sh` + `install.ps1`); the vision module preserves that — `pathlib` paths, `opencv-python-headless`, a per-OS OpenCV capture backend (AVFoundation / V4L2 / DirectShow), configurable device selection, and best-effort (never-raising) camera controls. All unit tests are hardware-free and OS-agnostic.

## Goal

Add two cameras to the binder-jet operator:

1. **Overview camera** — a live view of the whole build area for the operator UI. "Just for viewing."
2. **Science camera** — a stationary, high-resolution camera that captures a still of the build bed at each process stage (pre-jet / post-jet / post-heat), geometrically **registered to the bed plane** (lens-distortion corrected + mapped to millimetres) and stored with full metadata.

Slice 1 delivers the **data foundation**: cameras in, event-triggered registered stills, stored as a reproducible per-layer dataset — **without ever affecting motion-control timing**. Analysis (intended-vs-printed comparison, carbon concentration) is deferred to later slices but the data model is designed to serve them.

## Scope

**In scope (Slice 1):**
- A `vision` module in the operator backend, isolated from the control loop.
- `FrameSource` hardware abstraction; UVC implementation (resolution + pixel-format negotiation, actual-mode readback, fresh-grab); a simulated source for tests.
- Capture triggered by existing print events (`EventLog` sink) at bed-clear stages, with fresh (non-stale) frames.
- Bed-plane registration (**intrinsics + lens distortion + homography** from calibration targets) → mm-mapped "bed images," validated across the bed.
- Storage layout + metadata sidecars + per-run manifest.
- Overview-camera live stream in the UI.
- A "Cameras" view: overview stream, latest science stills per stage, calibration workflow, capture browser.

**Deferred (designed-for, not built in Slice 1):**
- Intended-vs-printed dimensional comparison. Two reference sources: (a) the **imported Meteor sliced job stack** (per-layer bitmaps) for real jobs; (b) **rfam_tool generated geometry** (`code/rfam_tool/generate_dimensional_geometry.py`, the dimensional-accuracy diagnostic patterns) for dimensional tests. Analysis backend: `code/rfam_tool/dimension_analysis.py` / `dimensional_main.py`.
- Carbon-concentration estimation (`rfam_ink_tool_carbon_content`). Requires controlled illumination + color/exposure calibration.

**Non-goals:**
- No change to the jetting path (external: Meteor/MetPrint).
- No thermal work (that is the separate FLIR research interface).

## Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Where it lives | **Inside the Vention operator** | The operator natively knows the process events; in-process triggering, one recording timeline. |
| Capture trigger | **Printer events drive capture** | Internal `EventLog` sink; deterministic layer+stage labels; no cross-system link. |
| Overview-cam hardware | **ELP 20MP AR2020, 95° FOV, housed, USB3/UVC** (`ELP-U3CAM20MP01-KV100`, ASIN B0GMFM4CJV) | Wide coverage of the whole machine; run at 1920×1080@30 (MJPEG) for a shared live view; no calibration. |
| Science-cam hardware | **ELP 20MP AR2020, CS-mount 5–50 mm manual varifocal, housed, USB3/UVC** (`ELP-U3CAM20MP01-IB(5-50B)`, ASIN B0GMFN5RTD) | 5120×3840 sensor; manual zoom/focus/iris set & locked at install; capture full-res **YUY2 (7.5 fps, uncompressed-ish)** when the host supports it, else **MJPEG (27.5 fps)** with the actual format recorded. Replaces the earlier 4K B0D2541JJ6. |
| Registration | **Intrinsics + lens-distortion calibration, THEN bed-plane homography** at the powder-surface plane; validated across the bed | A homography corrects planar perspective only — lens distortion needs an intrinsic/distortion model. `mm/px` is a configurable output grid, **not** a measured accuracy. |
| Slice-1 output | **Capture + register + store** | Foundation all later analysis feeds on. |

## Cameras (finalized 2026-09-13)

Both are ELP modules on the Onsemi **AR2020** sensor (max **5120×3840**), USB3/UVC, advertised cross-platform (macOS/Linux/Windows). Actual modes and control availability **must be verified on the printer host** — advertised specs are not guarantees.

**Overview** — `ELP-U3CAM20MP01-KV100` (95° FOV, housed):
- Start at **1920×1080 @ 30 fps, MJPEG**; serve through the existing overview-stream endpoint.
- **No dimensional calibration.** Housed, secured to the printer frame. Open **one** source and fan its frames out to all UI clients.

**Science** — `ELP-U3CAM20MP01-IB(5-50B)` (CS-mount 5–50 mm manual varifocal, housed):
- Capture at **5120×3840** — do **not** silently fall back to 3840×2160 because the module says "4K."
- Prefer **full-res YUY2 (7.5 fps)** to avoid JPEG artifacts; it is still processed, chroma-subsampled video — **not sensor RAW**. If YUY2 at full res is unavailable on the host, use **MJPEG (27.5 fps)** and **record the actual format explicitly** (saving a decoded MJPEG frame as PNG does not undo prior compression).
- **Manual** optical zoom/focus; confirm the mechanical iris (advertised lens-ring brightness) during acceptance. **Set zoom/focus/aperture at install, then lock** — any change invalidates calibration.
- Approx. install: **~2 ft from the bed at a 30–45° angle** — confirm whether that angle is from vertical or from the bed surface before computing coverage. Short, rigid mount with cable strain relief.

## Camera connection & role persistence (auto-connect + quick-start)

Both cameras share the AR2020 sensor, so the OS cannot tell them apart by name — the operator should NOT have to re-pick devices on every connect.

- **Persistent role memory:** a role map (`stable_id → role`, stored under the config/experiments root; `cameras.save_role_map`/`load_role_map` already exist) remembers which physical device is `overview` vs `science`. Keyed on a **stable device identifier** (USB path/serial), not enumeration index.
- **Auto-connect on connect:** whenever the operator connects to the software, it enumerates devices, loads the role map, `resolve_roles`, and **auto-opens the mapped overview + science cameras** — no per-device selection. If every role resolves, connection is silent.
- **Quick-start setup page (first-run wizard):** shown only when roles are unresolved/ambiguous (new machine, a camera swapped, or an unknown `stable_id`). It previews each detected camera so the operator labels which is `overview` and which is `science`, saves the role map, then **disappears**. It is **reopenable any time from Settings** to re-assign roles (cameras swapped, replaced, or re-cabled). Changing a role updates the map and re-opens sources accordingly.
- Backend endpoints: enumerate detected devices (id + preview), get/set the role map. Frontend: the wizard + a Settings entry to reopen it.

## Calibration board generation (SVG/DXF for laser engraving)

The operator will laser-engrave ChArUco boards onto **dual-color ABS sheet**, so the app must generate boards as **true vector** files at exact physical size.

- **Vector, not raster:** `cv2.aruco...generateImage()` outputs a bitmap — unusable for a laser. The generator draws the board as vector geometry itself: the checkerboard squares as filled rectangles at exact **mm** coordinates, and each ArUco marker's NxN **bit cells** as filled rectangles read from the contrib dictionary's bit patterns. Output **SVG** (native, no dep) and **DXF** (via `ezdxf`, a new dep, or hand-rolled).
- **Dual-color engrave semantics:** engraving removes the top color to reveal the second. The output marks the "black" regions (black checker squares + black marker bits) as the **engrave** layer/fill; make the engrave polarity **invertible** (config), since which ABS color is on top varies.
- **Adjustable + presets:** parameters are adjustable (`squares_x`, `squares_y`, `square_length_mm`, marker/square ratio, ArUco dictionary). Presets: a **small board that fits a ~4 in (Ø101.6 mm) cylinder top**, a **medium 5×7**, and a **large 6×9** — all overridable.
- **Self-labeling:** engrave a human-readable label with the exact `BoardSpec` (dict, squares, square mm) on the board, so a photographed board's spec — which the calibration step must match — is recoverable.
- Backend endpoint returns the SVG/DXF for given params/preset; a small UI lets the operator pick a preset/params and download it (local operator app, so downloads work).

## Architecture

### Isolation (the safety property)

The operator already has an event bus, `control/events.py::EventLog`:
- `add_sink(sink: Callable[[str, dict], None])` registers observers.
- `append(label, data)` records the event and calls every sink, each wrapped in `try/except` so **a sink exception never breaks the emitter**.
- Sinks run **synchronously on the caller's thread** (often the control loop).

Therefore the `VisionService` registers as a **sink**, and its sink callback must be **strictly non-blocking**: it validates the label, builds a `CaptureRequest`, and `queue.put_nowait(...)` (drop-oldest if full), then returns immediately. All slow work — grabbing a frame, warping, writing files — runs on a **dedicated worker thread** draining that queue. A slow or failed camera can, at worst, drop a capture; it can never delay `EventLog.append` and thus never delay motion.

```
print_controller._emit(label,data) → on_event → EventLog.append(label,data)
        → [recorder sink] [api/event-log sink] [VisionService sink → put_nowait → return]
                                                         │
                                   (separate thread) worker: grab → warp → write image + sidecar
```

### Capture points

Capture stages are emitted as `mark` steps in `compile_print` (same mechanism as today's `layer_start` → `layer_started`). New capture labels (proposed):
- `capture:pre_jet` — layer coated, bed clear, **before** the jetting pass.
- `capture:post_jet` — **after** the jetting pass, gantries parked clear.
- `capture:post_heat` — **after** the heater dwell, gantries parked clear.

**Bed-clear constraint:** the science cam is stationary and the recoater/printhead gantries traverse its field of view. Capture must fire only when the bed is unobstructed and still — i.e. at parked states (printhead at `printhead_start_mm`=250, recoater home ≈5). Each `mark` is placed in `compile_print` at a step where the axes are already parked. Exact clear positions are confirmed against the camera's actual FOV during calibration (see Open Questions).

### Capture freshness

UVC capture buffers frames; a naive `read()` can return a **stale, pre-event** frame that would be silently mislabeled to the wrong stage. The worker therefore takes a **fresh** frame for each stage capture (flush the buffer / grab-to-latest, e.g. `CAP_PROP_BUFFERSIZE=1` plus a discard-then-grab), records the frame's own timestamp in the sidecar, and — where the event timestamp is available — never assigns a frame older than the triggering event. Freshness is a first-class acceptance check.

### Registration pipeline (corrected)

A single homography is **not** enough: it corrects planar perspective but not lens distortion, and dewarping can never recover optical blur or missing detail. The science-camera registration is a calibrated pipeline, performed once at the final locked focus/zoom/capture-mode:

1. **Intrinsics + distortion** — calibrate the camera matrix `K` and distortion coefficients from **multiple** calibration-target views. **Both board types are supported: ChArUco (preferred) and plain checkerboard (allowed).** ChArUco detection/calibration (`cv2.aruco.detectMarkers` → `interpolateCornersCharuco` → `calibrateCameraCharuco`) is more robust to occlusion/partial views and gives per-corner IDs; checkerboard uses `findChessboardCorners`+`cornerSubPix` → `calibrateCamera`. A board-spec config (squares_x/y, square_length_mm, marker_length_mm + ArUco dictionary for ChArUco; rows/cols + square_size for checkerboard) drives detection. **Dependency note:** `cv2.aruco` lives in `opencv-contrib`, so the ChArUco path requires switching the dependency from `opencv-python-headless` to `opencv-contrib-python-headless` (a drop-in superset).
2. **Bed-plane homography** — estimate the homography from a target lying in the **actual powder-surface plane** (not an arbitrary height).
3. **Undistort → bed map** — undistort the image, then map into bed (mm) coordinates.
4. **Fuse** — where practical, compose undistort + homography into **one** resampling (precomputed remap) to avoid double interpolation.
5. **Validate** — check dimensional accuracy against **independent** known points/dimensions across the bed — near edge, far edge, and corners — and store the result.

`mm_per_px` (example 0.05) is a **configurable output-grid spacing, not an established measurement accuracy**. Final spacing and acceptance tolerances depend on actual bed size, required feature resolution, and the installed-camera validation.

## Components (files)

All under `backend/vention_printer_interface/vision/`:

| File | Responsibility |
|---|---|
| `frame_source.py` | `FrameSource` ABC: `open()`, `close()`, `grab() -> Frame`, `configure(...)`. `UvcFrameSource` negotiates **resolution + pixel format (FOURCC: YUY2 or MJPG)** and reads back the **actual** width/height/fps/FOURCC into `Frame.settings` (requested ≠ actual is recorded, never assumed). Exposes readable UVC controls (exposure/gain/white-balance + their auto states) where the OS/driver allows (`null` otherwise), and a **fresh-grab** path (buffer flushed) for stage captures. `SimulatedFrameSource` for tests; `IndustrialFrameSource` later. |
| `registration.py` | Pure functions for the corrected pipeline: `calibrate_intrinsics(views) -> (K, dist)`, `compute_homography(image_pts, world_pts_mm)`, `undistort_points/image`, `build_bed_remap(K, dist, H, mm_per_px, bed_extent_mm)` (fused undistort+homography map), `warp_to_bed(...)`, `reprojection_error(...)`, `validate_dimensions(points_mm, measured_mm)`, `load_calibration()/save_calibration()`. Extended `Calibration` (see Data model). Persisted to `.vision_calibration.json` per camera. Unit-testable with synthetic points. |
| `capture.py` | `VisionService`: the non-blocking sink + worker thread + bounded queue. Consumes capture labels, grabs, optionally warps, writes via `store`. Structured logging; drop-oldest metric. |
| `events.py` | Capture contract: `CaptureRequest{run_id, layer:int, stage:str, host_timestamp_ns, axis_positions:dict, job_id}`; the set of capture labels it listens for. |
| `store.py` | Storage layout + manifest writer/reader (below). |
| `overview.py` | Overview camera: MJPEG live-stream generator (+ optional continuous record). No registration. |
| `cameras.py` | Camera registry/config + **role assignment**. Both cameras share the AR2020 sensor and enumerate with near-identical names, so roles are **not** inferred from index/name alone: config carries a **stable device identifier** (USB path/serial where available) and a **preview-based identification** workflow (show each source so the operator confirms which is overview vs science). Holds per-role resolution, pixel format, per-OS `default_backend()`, and the science calibration path. |

Backend wiring:
- `api/app.py`: construct `VisionService`, `event_log.add_sink(vision.on_event)` during startup; expose endpoints.
- `control/print.py` (`compile_print`): insert the three capture `mark` steps at parked points.

### API endpoints

- `GET /api/vision/status` — cameras present, calibration state, queue depth, drops.
- `GET /api/vision/cameras` — enumerated devices + role assignment.
- `POST /api/vision/calibrate` — capture calibration target, compute homography, return reprojection error.
- `GET /api/vision/overview/stream` — MJPEG live stream (overview cam).
- `GET /api/vision/captures?run=…` — list stored captures / serve images + metadata.

### Frontend

**Reusable `OverviewCameraPanel` component** (wraps the shared `GET /api/vision/overview/stream` MJPEG). It is embedded, in a compact/collapsible form, on the **Control**, **Priming**, and **Print** views so the operator always has a live view of the build while working — and in full size on the Cameras view. Because all instances point at the one stream endpoint, this is a pure frontend addition with no extra backend cost. The panel degrades gracefully (placeholder + reason) when the overview camera is absent or the backend isn't serving it, and its visibility is a per-view toggle (remembered locally) so it never crowds a page the operator wants clean.

New **"Cameras"** view (React):
- Overview live MJPEG (full size).
- Science-cam latest still per stage (pre-jet / post-jet / post-heat) for the current layer.
- Calibration workflow: place target → capture → compute → show reprojection error + a warped preview.
- Capture browser: navigate run → layer → stage; show raw + registered image and metadata.

Views touched for the embedded overview panel: `ControlView`/control page, `PrimingView`, `PrintView`, plus the new `CamerasView`.

## Data model

Under `experiments_root` (same root the operator already uses):

```
runs/<run_id>/
  manifest.json                      # run-level: job, camera ids, calibration version, start time
  layer_0001/
    pre_jet.png        pre_jet.json
    post_jet.png       post_jet.json
    post_heat.png      post_heat.json
  layer_0002/ ...
```

Each `<stage>.json` sidecar (`"raw"` = the **original unwarped decoded frame**, not Bayer sensor RAW):
```json
{
  "run_id": "…", "layer": 1, "stage": "post_jet",
  "host_timestamp_ns": 0, "frame_timestamp_ns": 0,
  "job": {"id": "…", "name": "…"},
  "axis_positions_mm": {"build": 0.0, "feed": 0.0, "printhead": 250.0, "recoater": 5.0},
  "camera": {"role": "science", "model": "ELP-U3CAM20MP01-IB(5-50B)", "asin": "B0GMFN5RTD",
             "device_id": "usb-…-or-serial", "device_index": 1},
  "capture": {"requested": {"width": 5120, "height": 3840, "fps": 7.5, "pixel_format": "YUY2"},
              "actual":    {"width": 5120, "height": 3840, "fps": 7.5, "pixel_format": "YUY2"}},
  "controls": {"exposure": null, "gain": null, "white_balance": null,
               "auto_exposure": null, "auto_white_balance": null},
  "lens_notes": "5–50mm varifocal; zoom/focus/iris locked at install (UVC cannot read lens-ring positions)",
  "calibration": {"version": "…", "image_size": [5120, 3840],
                  "camera_matrix": [[..],[..],[..]], "distortion_model": "opencv-5",
                  "distortion_coeffs": [0,0,0,0,0], "bed_homography": [[..],[..],[..]],
                  "validation": {"rms_mm": null, "points": []}},
  "images": {"raw": "post_jet.raw.png", "registered": "post_jet.png"},
  "registered_space": {"mm_per_px": 0.05, "bed_extent_mm": [0, 0, 200, 200]},
  "checksum_sha256": "…"
}
```

Notes: requested vs **actual** capture params are both recorded; readable controls are stored where available and `null`/unknown otherwise (UVC often cannot read them, and never reads mechanical lens-ring positions). Storing registered images in a **fixed mm coordinate space** lets both deferred reference sources (Meteor slice bitmaps, rfam_tool geometry) be compared later by rendering the intended layer into the same mm space.

## Testing (TDD, red-green)

- **`registration.py`** (pure): homography recovery and `warp_to_bed` against synthetic point sets with a known transform; assert sub-pixel reprojection error and correct mm/px scaling.
- **`VisionService`** with `SimulatedFrameSource`: capture labels → expected files + sidecars written; queue overflow drops oldest (never blocks); a `grab()` that raises is swallowed and logged.
- **Non-blocking contract** (the safety-critical test): a `FrameSource` whose `grab()` sleeps long must **not** delay the sink's return — assert the sink returns within a tight bound while the worker is still busy.
- **`store.py`**: directory layout + manifest round-trip.
- **API**: endpoints with the simulated source (status, captures listing, calibrate compute).
- **`compile_print`**: the three capture `mark` steps are emitted at parked positions in the expected order per layer.

Not unit-testable (substitute concrete verification): actual UVC frame grab on hardware, MJPEG stream in the browser, real calibration-target reprojection. Verified live at the machine.

## Risks & open questions

1. **Advertised ≠ actual modes/controls.** UVC exposure/gain/white-balance locking (and even full-res YUY2 at 7.5 fps) may not be honored on a given host/OS — macOS/AVFoundation is especially limited. Verify on the printer host; record actual, not requested.
2. **Two identical-sensor cameras** enumerate with near-identical names — index/name are not reliable role identifiers. Requires stable device id + preview-based role assignment (see `cameras.py`).
3. **USB bandwidth** — simultaneous overview stream + full-res 20 MP science capture on one host may exceed a shared USB controller. Overview stays at 1080p; science is captured on demand (not streamed). Confirm on the host; separate USB buses if needed.
4. **Distortion & accuracy** — a homography alone does not correct lens distortion; the intrinsic/distortion pipeline is required. `mm/px` is an output grid, not an accuracy figure — installed measurement accuracy is established experimentally by the cross-bed validation.
5. **Bed-clear FOV geometry** — parked positions that leave the bed unobstructed must be confirmed against the real (tilted) mount/FOV; drives where the `mark` steps sit and whether sharpness holds across the whole tilted bed.
6. **Capture freshness** — buffered/delayed frames must never be assigned to the wrong stage (see Capture freshness).
7. **Illumination** — repeatable diffuse lighting is needed for reproducible measurement, and essential for later carbon-concentration work.
8. **Storage growth** — 20 MP stills × 3 stages × N layers is very large (YUY2/PNG especially); a retention/compression policy is out of Slice-1 scope but will be needed.

## Hardware acceptance checks (before trusting measurements)

Run at install, on the actual host, and record results:
- Confirm each camera's identity + supported modes on the host; assign roles by preview.
- Verify **simultaneous** overview streaming and full-res science capture.
- Verify exposure/gain/white-balance **locking** through the selected backend (or record that it is not controllable).
- Confirm focus/useful sharpness across the **entire tilted bed** at the installed distance.
- Confirm iris operation and that zoom/focus/aperture settings are retained.
- Validate dimensional error across the bed against **independent** known dimensions (near/far edges, corners).
- Verify **capture freshness** (no stale/buffered frame assigned to the wrong stage).
- Establish repeatable diffuse lighting (particularly for later carbon analysis).

## Later slices (for context, not this build)

- **Slice 2 — Comparison:** render the intended layer (Meteor slice bitmap, or rfam_tool geometry) into the registered mm space; compute dimensional match via `rfam_tool/dimension_analysis.py`; surface overlay/diff + metrics in the Cameras view.
- **Slice 3 — Carbon concentration:** illumination/color calibration + `rfam_ink_tool_carbon_content` per-layer estimate.
