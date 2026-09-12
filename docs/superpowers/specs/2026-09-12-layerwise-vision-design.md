# Layerwise Vision — Design (Slice 1: Capture + Register + Store)

**Date:** 2026-09-12
**Status:** Approved 2026-09-12
**Author:** Matt McCoy (with Claude)
**Platforms:** macOS, Windows, Linux. The operator is cross-platform (`install.sh` + `install.ps1`); the vision module preserves that — `pathlib` paths, `opencv-python-headless`, a per-OS OpenCV capture backend (AVFoundation / V4L2 / DirectShow), configurable device selection, and best-effort (never-raising) camera controls. All unit tests are hardware-free and OS-agnostic.

## Goal

Add two cameras to the binder-jet operator:

1. **Overview camera** — a live view of the whole build area for the operator UI. "Just for viewing."
2. **Science camera** — a stationary, high-resolution camera that captures a still of the build bed at each process stage (pre-jet / post-jet / post-heat), geometrically **registered to the bed plane** (dewarped + scaled to millimetres) and stored with full metadata.

Slice 1 delivers the **data foundation**: cameras in, event-triggered registered stills, stored as a reproducible per-layer dataset — **without ever affecting motion-control timing**. Analysis (intended-vs-printed comparison, carbon concentration) is deferred to later slices but the data model is designed to serve them.

## Scope

**In scope (Slice 1):**
- A `vision` module in the operator backend, isolated from the control loop.
- `FrameSource` hardware abstraction; UVC implementation for the chosen camera; a simulated source for tests.
- Capture triggered by existing print events (`EventLog` sink) at bed-clear stages.
- Bed-plane registration (homography from a calibration target) → mm-scaled "bed images."
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
| Science-cam hardware | **UVC USB3.0 4K camera** (Amazon ASIN B0D2541JJ6: "4K 60FPS USB3.0, 2.8–12mm 4X manual zoom, CS mount, industrial-grade UVC") | Enumerates as a standard webcam (OpenCV); manual varifocal lens = fixed, repeatable optics with no autofocus drift. |
| Registration | **Homography from a calibration target on the bed** → warp to bed plane at fixed mm/px | Stationary camera ⇒ one calibration captures the dewarp + scale. |
| Slice-1 output | **Capture + register + store** | Foundation all later analysis feeds on. |

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

## Components (files)

All under `backend/vention_printer_interface/vision/`:

| File | Responsibility |
|---|---|
| `frame_source.py` | `FrameSource` ABC: `open()`, `close()`, `grab() -> Frame`, `configure(exposure, gain, focus)`. `Frame` = image ndarray + capture timestamp + effective settings. Implementations: `UvcFrameSource` (OpenCV `VideoCapture`), `SimulatedFrameSource` (synthetic bed image for tests). Future: `IndustrialFrameSource`. |
| `registration.py` | Pure functions: `compute_homography(image_pts, world_pts_mm)`, `warp_to_bed(frame, H, mm_per_px, bed_extent_mm) -> BedImage`, `reprojection_error(...)`, `load_calibration()/save_calibration()`. Calibration persisted to `.vision_calibration.json` (per camera). No I/O beyond the load/save helpers; unit-testable with synthetic points. |
| `capture.py` | `VisionService`: the non-blocking sink + worker thread + bounded queue. Consumes capture labels, grabs, optionally warps, writes via `store`. Structured logging; drop-oldest metric. |
| `events.py` | Capture contract: `CaptureRequest{run_id, layer:int, stage:str, host_timestamp_ns, axis_positions:dict, job_id}`; the set of capture labels it listens for. |
| `store.py` | Storage layout + manifest writer/reader (below). |
| `overview.py` | Overview camera: MJPEG live-stream generator (+ optional continuous record). No registration. |
| `cameras.py` | Camera registry/config: which device index/id is overview vs science, resolution, and per-camera calibration path. |

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

Each `<stage>.json` sidecar:
```json
{
  "run_id": "…", "layer": 1, "stage": "post_jet",
  "host_timestamp_ns": 0,
  "job": {"id": "…", "name": "…"},
  "axis_positions_mm": {"build": 0.0, "feed": 0.0, "printhead": 250.0, "recoater": 5.0},
  "camera": {"id": "science", "device": "…"},
  "capture_settings": {"exposure": null, "gain": null, "focus": "manual-fixed"},
  "calibration_version": "…",
  "images": {"raw": "post_jet.raw.png", "registered": "post_jet.png"},
  "registered_space": {"mm_per_px": 0.05, "bed_extent_mm": [0, 0, 200, 200]},
  "checksum_sha256": "…"
}
```

Storing registered images in a **fixed mm coordinate space** is what lets both deferred reference sources (Meteor slice bitmaps, rfam_tool geometry) be compared later by rendering the intended layer into the same mm space.

## Testing (TDD, red-green)

- **`registration.py`** (pure): homography recovery and `warp_to_bed` against synthetic point sets with a known transform; assert sub-pixel reprojection error and correct mm/px scaling.
- **`VisionService`** with `SimulatedFrameSource`: capture labels → expected files + sidecars written; queue overflow drops oldest (never blocks); a `grab()` that raises is swallowed and logged.
- **Non-blocking contract** (the safety-critical test): a `FrameSource` whose `grab()` sleeps long must **not** delay the sink's return — assert the sink returns within a tight bound while the worker is still busy.
- **`store.py`**: directory layout + manifest round-trip.
- **API**: endpoints with the simulated source (status, captures listing, calibrate compute).
- **`compile_print`**: the three capture `mark` steps are emitted at parked positions in the expected order per layer.

Not unit-testable (substitute concrete verification): actual UVC frame grab on hardware, MJPEG stream in the browser, real calibration-target reprojection. Verified live at the machine.

## Risks & open questions

1. **macOS UVC manual exposure/gain lock** via OpenCV/AVFoundation is often limited. Acceptable for Slice-1 capture/store; **matters for carbon/color later** (needs stable exposure + illumination). Flag before relying on quantitative color.
2. **Bed-clear FOV geometry** — the exact parked positions that leave the bed unobstructed in the science cam's frame must be confirmed against the real mount/FOV. Drives where the `mark` steps go.
3. **Illumination** — repeatable measurement (and later carbon) needs controlled, even lighting; ambient/room light will hurt reproducibility.
4. **Rolling shutter** — the UVC cam is almost certainly rolling-shutter; fine because captures happen at still, parked moments.
5. **Overview vs science on one Mac** — both likely USB (UVC); no new network subnets needed (unlike GigE). Confirm USB bandwidth with two 4K streams if both are high-res (overview can be downscaled).
6. **experiments_root growth** — 4K PNGs × 3 stages × N layers is large; consider retention/compression policy (out of Slice-1 scope but note it).

## Later slices (for context, not this build)

- **Slice 2 — Comparison:** render the intended layer (Meteor slice bitmap, or rfam_tool geometry) into the registered mm space; compute dimensional match via `rfam_tool/dimension_analysis.py`; surface overlay/diff + metrics in the Cameras view.
- **Slice 3 — Carbon concentration:** illumination/color calibration + `rfam_ink_tool_carbon_content` per-layer estimate.
