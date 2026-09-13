# Layerwise Vision — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two RGB cameras to the Vention operator — an overview live view (embedded on Control/Prime/Print/Cameras) and a stationary high-res "science" camera that captures bed-registered, mm-scaled stills at each print stage, stored per-layer with metadata — without ever affecting motion-control timing.

**Architecture:** A new `vision/` package registers a **non-blocking sink** on the existing `control/events.py::EventLog` (same pattern as `Recorder`, `api/app.py:222`). The sink only enqueues; a worker thread grabs frames, warps them to the bed plane (homography), and writes images + JSON sidecars under the **active recorder run directory**. Capture points are `mark` steps added to `compile_print` (`control/print_settings.py`). Hardware sits behind a `FrameSource` ABC so the UVC 4K camera (or a simulated source in tests, or an industrial camera later) drops in unchanged.

**Tech Stack:** Python 3.11+ / FastAPI backend (pytest, ruff line-length 100, mypy strict); OpenCV (`opencv-python-headless`) + NumPy for capture/registration; React/TypeScript frontend (`node --test` for `lib/*.ts`, `tsc`+`vite` build for components).

**Spec:** `docs/superpowers/specs/2026-09-12-layerwise-vision-design.md`

> **⚠ 2026-09-13 Addendum at the end of this file supersedes the camera model and the registration approach used in the tasks below.** Finalized cameras are two ELP AR2020 modules; registration is now intrinsics + distortion + homography (not homography-only); capture must be fresh; metadata is expanded. Read the Addendum before implementing Tasks 3, 4–6 (extend), 7, 9, 11b, and Phase 8.

**Reconciliation vs spec:** the spec sketched storage as `runs/<run_id>/…`; this plan nests captures under the **recorder's active run dir** (`<run_dir>/vision/layer_NNNN/<stage>.png`) so a run's telemetry/events/vision live together. When no run is active, captures write to `<experiments_root>/vision_adhoc/<ts>/…`.

**Cross-platform requirement (macOS, Windows, Linux):** the operator is cross-platform (`install.sh` + `install.ps1`), and the vision module must not break that. Rules every task follows:
- **Paths:** `pathlib.Path` only — never string-concatenated separators; write PNG/JSON in binary/utf-8. No shell-outs (`networksetup`, etc. belong to the FLIR repo, not here).
- **OpenCV:** `opencv-python-headless` runs on all three. **Camera capture backend differs per OS** — AVFoundation (macOS), V4L2 (Linux), DirectShow/MSMF (Windows). `UvcFrameSource` accepts an explicit `backend` and `cameras.py` supplies a per-OS default; device selection is configurable (index or path) because enumeration differs.
- **`FrameSource.configure()` is best-effort:** exposure/gain/focus locks apply where the OS/driver supports them and silently no-op elsewhere (notably limited on macOS UVC) — never raise.
- **Tests stay hardware-free:** all unit tests use `SimulatedFrameSource` and mock `platform.system()`; nothing opens a real device, so the suite is green on any OS/CI.
- **Frontend:** unaffected (browser-based); `node --test` + `vite` build are already cross-platform.

---

## File Structure

**Backend — new (`backend/vention_printer_interface/vision/`):**
- `__init__.py` — package exports.
- `frame_source.py` — `Frame`, `FrameSource` ABC, `SimulatedFrameSource`, `UvcFrameSource`.
- `registration.py` — pure homography/warp/calibration-IO functions.
- `events.py` — `CaptureRequest`, capture-label constants, `label_to_stage()`.
- `store.py` — capture paths, sidecar + manifest writers.
- `capture.py` — `VisionService` (non-blocking sink + bounded queue + worker thread).
- `overview.py` — MJPEG frame generator for the overview camera.
- `cameras.py` — camera config/registry (device → role, resolution, calibration path).

**Backend — modified:**
- `control/print_settings.py` — add capture `mark` steps to `compile_print` + a `capture_stages` toggle field.
- `recording/recorder.py` — add `current_run_dir` accessor.
- `api/app.py` — construct `VisionService`, `events.add_sink(vision.on_event)`, add `/api/vision/*` routes.
- `pyproject.toml` — add `numpy`, `opencv-python-headless`.

**Backend — tests:** `test_vision_frame_source.py`, `test_vision_registration.py`, `test_vision_store.py`, `test_vision_capture.py`, `test_api_vision.py`; extend `test_print_settings.py`.

**Frontend — new:**
- `src/lib/vision.ts` (+ `vision.test.ts`) — pure logic (URLs, capture-list parsing, panel-visibility persistence).
- `src/components/OverviewCameraPanel.tsx` — reusable embedded panel.
- `src/components/views/CamerasView.tsx` — full Cameras page.

**Frontend — modified:** `src/lib/console.ts` (add `"cameras"` view), `src/App.tsx` (route CamerasView + embed panel), `PrintView.tsx`/`PrimingView.tsx`/`ControlView.tsx` (embed panel).

---

## Phase 1 — Dependencies & FrameSource seam

### Task 1: Add imaging dependencies

**Files:** Modify `backend/pyproject.toml`

- [ ] **Step 1: Add deps.** Under `[project].dependencies` add `"numpy>=1.26"` and `"opencv-python-headless>=4.9"`.
- [ ] **Step 2: Lock + verify import.**

Run: `cd backend && uv sync --extra dev && uv run python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"` (use `--extra dev` — the repo convention — so pytest/ruff/mypy stay installed)
Expected: prints versions, no error.

- [ ] **Step 3: Commit.** `git add backend/pyproject.toml backend/uv.lock && git commit -m "build(vision): add numpy + opencv-python-headless"`

### Task 2: FrameSource abstraction + SimulatedFrameSource

**Files:** Create `vision/__init__.py`, `vision/frame_source.py`, `tests/test_vision_frame_source.py`

- [ ] **Step 1: Write the failing test** (`tests/test_vision_frame_source.py`):

```python
import numpy as np
from vention_printer_interface.vision.frame_source import Frame, SimulatedFrameSource


def test_simulated_source_grabs_configured_frame():
    src = SimulatedFrameSource(width=64, height=48)
    src.open()
    f = src.grab()
    assert isinstance(f, Frame)
    assert f.image.shape == (48, 64, 3)
    assert f.image.dtype == np.uint8
    assert f.timestamp_ns > 0
    src.close()


def test_configure_records_effective_settings():
    src = SimulatedFrameSource(width=8, height=8)
    src.open()
    src.configure(exposure=0.02, gain=1.5, focus="manual-fixed")
    f = src.grab()
    assert f.settings == {"exposure": 0.02, "gain": 1.5, "focus": "manual-fixed"}
    src.close()
```

Run: `cd backend && uv run pytest tests/test_vision_frame_source.py -q`
Expected: FAIL (module missing).

- [ ] **Step 2: Implement `vision/frame_source.py`:**

```python
"""Camera frame sources behind one interface, so hardware choice never leaks upward."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray            # HxWx3 uint8 (BGR, OpenCV convention)
    timestamp_ns: int
    settings: dict[str, Any] = field(default_factory=dict)


class FrameSource(ABC):
    @abstractmethod
    def open(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def grab(self) -> Frame: ...
    def configure(self, **settings: Any) -> None:  # optional; default no-op
        self._settings = {**getattr(self, "_settings", {}), **settings}


class SimulatedFrameSource(FrameSource):
    """Deterministic synthetic frames for tests (a gradient + a bright square)."""

    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.width, self.height = width, height
        self._settings: dict[str, Any] = {}
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def configure(self, **settings: Any) -> None:
        self._settings = {**self._settings, **settings}

    def grab(self) -> Frame:
        if not self._open:
            raise RuntimeError("source not open")
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:, :, 1] = np.linspace(0, 255, self.width, dtype=np.uint8)[None, :]
        img[self.height // 4:self.height // 2, self.width // 4:self.width // 2] = 255
        return Frame(image=img, timestamp_ns=time.time_ns(), settings=dict(self._settings))
```

And `vision/__init__.py`:
```python
from vention_printer_interface.vision.frame_source import Frame, FrameSource, SimulatedFrameSource

__all__ = ["Frame", "FrameSource", "SimulatedFrameSource"]
```

- [ ] **Step 3: Run test → PASS.** `cd backend && uv run pytest tests/test_vision_frame_source.py -q`
- [ ] **Step 4: Lint.** `cd backend && uv run ruff check vision/ tests/test_vision_frame_source.py`
- [ ] **Step 5: Commit.** `git add backend/vention_printer_interface/vision/ backend/tests/test_vision_frame_source.py && git commit -m "feat(vision): FrameSource abstraction + simulated source"`

### Task 3: UvcFrameSource (OpenCV) — thin, hardware-gated

**Files:** Modify `vision/frame_source.py`

- [ ] **Step 1: Failing test** (append to `test_vision_frame_source.py`): construct `UvcFrameSource(device_index=0)` and assert it exposes `open/grab/close` and stores `device_index` (do NOT open real hardware in unit tests).

```python
from vention_printer_interface.vision.frame_source import UvcFrameSource

def test_uvc_source_constructs_without_opening_hardware():
    src = UvcFrameSource(device_index=2)
    assert src.device_index == 2
    assert hasattr(src, "open") and hasattr(src, "grab") and hasattr(src, "close")
```

Run → FAIL (UvcFrameSource missing).

- [ ] **Step 2: Implement `UvcFrameSource`** (lazy `import cv2` inside `open()` so tests/CI without a camera still import the module):

```python
class UvcFrameSource(FrameSource):
    """OpenCV VideoCapture over a UVC device. Real capture is verified on hardware."""

    def __init__(self, device_index: int = 0, width: int | None = None,
                 height: int | None = None, backend: int | None = None) -> None:
        self.device_index = device_index
        self.width, self.height = width, height
        self.backend = backend           # per-OS cv2.CAP_* (from cameras.default_backend())
        self._settings: dict[str, Any] = {"focus": "manual-fixed"}
        self._cap = None

    def open(self) -> None:
        import cv2
        cap = (cv2.VideoCapture(self.device_index, self.backend)
               if self.backend is not None else cv2.VideoCapture(self.device_index))
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open UVC device {self.device_index}")
        self._cap = cap

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def grab(self) -> Frame:
        if self._cap is None:
            raise RuntimeError("source not open")
        ok, img = self._cap.read()
        if not ok or img is None:
            raise RuntimeError("frame grab failed")
        return Frame(image=img, timestamp_ns=time.time_ns(), settings=dict(self._settings))
```

Add `UvcFrameSource` to `__init__.py` exports.

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): UVC OpenCV frame source"`

---

## Phase 2 — Registration (pure math, TDD-heavy)

### Task 4: Homography compute + reprojection error

**Files:** Create `vision/registration.py`, `tests/test_vision_registration.py`

- [ ] **Step 1: Failing test** — build a known homography, project world→image points, recover it, assert small reprojection error:

```python
import numpy as np
from vention_printer_interface.vision.registration import compute_homography, reprojection_error


def test_recovers_known_homography():
    world = np.array([[0, 0], [100, 0], [100, 80], [0, 80], [50, 40]], float)  # mm
    H_true = np.array([[2.0, 0.1, 30.0], [0.0, 2.0, 20.0], [0.0, 0.0, 1.0]])
    hom = np.hstack([world, np.ones((len(world), 1))])
    proj = (H_true @ hom.T).T
    image_pts = proj[:, :2] / proj[:, 2:]
    H = compute_homography(image_pts, world)          # image->world
    err = reprojection_error(H, image_pts, world)
    assert err < 1e-6
```

Run → FAIL.

- [ ] **Step 2: Implement** (`compute_homography` returns the image→world homography via `cv2.findHomography`; `reprojection_error` maps image points to world and RMS-compares to the truth):

```python
"""Bed-plane registration: pure functions over point correspondences + calibration IO."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


def compute_homography(image_pts: np.ndarray, world_pts_mm: np.ndarray) -> np.ndarray:
    import cv2
    src = np.asarray(image_pts, float).reshape(-1, 1, 2)
    dst = np.asarray(world_pts_mm, float).reshape(-1, 1, 2)
    H, _ = cv2.findHomography(src, dst, method=0)
    if H is None:
        raise ValueError("homography could not be computed")
    return H


def apply_homography(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float)
    hom = np.hstack([pts, np.ones((len(pts), 1))])
    out = (H @ hom.T).T
    return out[:, :2] / out[:, 2:]


def reprojection_error(H: np.ndarray, image_pts: np.ndarray, world_pts_mm: np.ndarray) -> float:
    mapped = apply_homography(H, image_pts)
    d = mapped - np.asarray(world_pts_mm, float)
    return float(np.sqrt((d ** 2).sum(axis=1).mean()))
```

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): homography compute + reprojection error"`

### Task 5: Warp to bed plane at fixed mm/px

**Files:** Modify `vision/registration.py`, `tests/test_vision_registration.py`

- [ ] **Step 1: Failing test** — warp a synthetic frame given `H`, `mm_per_px`, and bed extent; assert output size = `round(extent/mm_per_px)` and dtype uint8:

```python
from vention_printer_interface.vision.registration import warp_to_bed

def test_warp_output_dimensions():
    img = np.zeros((480, 640, 3), np.uint8)
    H = np.eye(3)  # image coords already == mm for this test
    bed = warp_to_bed(img, H, mm_per_px=0.5, bed_extent_mm=(0, 0, 100, 80))
    assert bed.shape == (160, 200, 3)  # 80/0.5=160 rows, 100/0.5=200 cols
    assert bed.dtype == np.uint8
```

Run → FAIL.

- [ ] **Step 2: Implement `warp_to_bed`** — compose `H` (image→mm) with an mm→pixel scale/offset and `cv2.warpPerspective` into the output raster:

```python
def warp_to_bed(image: np.ndarray, H: np.ndarray, mm_per_px: float,
                bed_extent_mm: tuple[float, float, float, float]) -> np.ndarray:
    import cv2
    x0, y0, x1, y1 = bed_extent_mm
    out_w = int(round((x1 - x0) / mm_per_px))
    out_h = int(round((y1 - y0) / mm_per_px))
    # mm -> output-pixel: translate by (x0,y0), scale by 1/mm_per_px
    S = np.array([[1 / mm_per_px, 0, -x0 / mm_per_px],
                  [0, 1 / mm_per_px, -y0 / mm_per_px],
                  [0, 0, 1]], float)
    M = S @ H  # image -> output pixels
    return cv2.warpPerspective(image, M, (out_w, out_h))
```

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): warp frame to bed plane at fixed mm/px"`

### Task 6: Calibration save/load

**Files:** Modify `vision/registration.py`, `tests/test_vision_registration.py`

- [ ] **Step 1: Failing test** — round-trip a `Calibration` dataclass through `save_calibration`/`load_calibration` in `tmp_path`. Fields (names must match the usage in Task 9): `H: np.ndarray`, `mm_per_px: float`, `bed_extent_mm: tuple[float,float,float,float]`, `version: str`, `reprojection_error: float`.

- [ ] **Step 2: Implement** `@dataclass Calibration` (fields above) + `save_calibration(path, calib)` (JSON) + `load_calibration(path) -> Calibration | None` (None when file absent). Store `H` via `.tolist()`, restore via `np.array(...)`; serialize `bed_extent_mm` as a list and restore as a tuple.

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): calibration persistence (.vision_calibration.json)"`

---

## Phase 3 — Storage

### Task 7: Capture store (paths, sidecar, manifest)

**Files:** Create `vision/store.py`, `tests/test_vision_store.py`

- [ ] **Step 1: Failing test:**

```python
import json
import numpy as np
from vention_printer_interface.vision.store import write_capture, capture_dir


def test_write_capture_lays_out_files(tmp_path):
    raw = np.zeros((8, 8, 3), np.uint8)
    reg = np.zeros((4, 4, 3), np.uint8)
    meta = {"run_id": "r1", "layer": 3, "stage": "post_jet"}
    paths = write_capture(tmp_path, layer=3, stage="post_jet", raw=raw, registered=reg, meta=meta)
    d = capture_dir(tmp_path, 3)
    assert (d / "post_jet.png").exists()
    assert (d / "post_jet.raw.png").exists()
    sidecar = json.loads((d / "post_jet.json").read_text())
    assert sidecar["stage"] == "post_jet" and sidecar["layer"] == 3
    assert "checksum_sha256" in sidecar
    assert paths["registered"].endswith("post_jet.png")
```

Run → FAIL.

- [ ] **Step 2: Implement `vision/store.py`** — `capture_dir(base, layer) -> base/"vision"/f"layer_{layer:04d}"`; `write_capture(...)` creates the dir, writes `raw` via `cv2.imwrite` to `<stage>.raw.png` and `registered` to `<stage>.png`, computes sha256 of the registered PNG bytes, merges it into `meta`, writes `<stage>.json`, returns a dict of relative paths. Add `read_manifest`/`append_manifest` helpers writing `base/"vision"/manifest.json` (list of capture records).

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): capture storage layout + sidecar + manifest"`

---

## Phase 4 — Events & VisionService

### Task 8: Capture event contract

**Files:** Create `vision/events.py`, `tests/test_vision_capture.py`

- [ ] **Step 1: Failing test** — `CAPTURE_LABELS == ("capture:pre_jet","capture:post_jet","capture:post_heat")`; `label_to_stage("capture:post_jet") == "post_jet"`; `label_to_stage("layer_started") is None`.
- [ ] **Step 2: Implement** `vision/events.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

CAPTURE_LABELS = ("capture:pre_jet", "capture:post_jet", "capture:post_heat")


def label_to_stage(label: str) -> str | None:
    return label.split("capture:", 1)[1] if label in CAPTURE_LABELS else None


@dataclass(frozen=True)
class CaptureRequest:
    layer: int
    stage: str
    host_timestamp_ns: int
    axis_positions_mm: dict[str, float] = field(default_factory=dict)
    job: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): capture event contract + labels"`

### Task 9: VisionService — the non-blocking sink + worker

**Files:** Create `vision/capture.py`, `tests/test_vision_capture.py`

- [ ] **Step 1: Failing test — behavior + the safety-critical non-blocking contract:**

```python
import time
import numpy as np
from vention_printer_interface.vision.frame_source import SimulatedFrameSource, FrameSource, Frame
from vention_printer_interface.vision.capture import VisionService


def _svc(tmp_path, source=None):
    return VisionService(
        source=source or SimulatedFrameSource(32, 24),
        run_dir_provider=lambda: tmp_path,
        calibration=None,           # no warp: registered == raw
        queue_max=8,
    )


def test_capture_event_writes_files(tmp_path):
    svc = _svc(tmp_path); svc.start()
    svc.on_event("capture:post_jet", {"layer": 2, "axis_positions_mm": {"build": 0.0}})
    svc.drain(timeout=2.0)          # test helper: block until queue processed
    assert (tmp_path / "vision" / "layer_0002" / "post_jet.png").exists()
    svc.stop()


def test_non_capture_labels_ignored(tmp_path):
    svc = _svc(tmp_path); svc.start()
    svc.on_event("layer_started", {"layer": 1})
    svc.drain(timeout=1.0)
    assert not (tmp_path / "vision").exists()
    svc.stop()


def test_grab_error_is_swallowed(tmp_path):
    class Boom(FrameSource):
        def open(self): ...
        def close(self): ...
        def grab(self): raise RuntimeError("camera fell off")
    svc = _svc(tmp_path, source=Boom()); svc.start()
    svc.on_event("capture:pre_jet", {"layer": 1})   # must not raise
    svc.drain(timeout=1.0)
    svc.stop()


def test_sink_is_non_blocking_even_when_source_is_slow(tmp_path):
    class Slow(FrameSource):
        def open(self): ...
        def close(self): ...
        def grab(self):
            time.sleep(1.0)
            return Frame(image=np.zeros((4, 4, 3), np.uint8), timestamp_ns=1)
    svc = _svc(tmp_path, source=Slow()); svc.start()
    t0 = time.monotonic()
    svc.on_event("capture:post_heat", {"layer": 1})   # returns immediately
    dt = time.monotonic() - t0
    assert dt < 0.05, f"sink blocked for {dt:.3f}s"
    svc.stop()
```

Run → FAIL.

- [ ] **Step 2: Implement `vision/capture.py`:**

```python
"""VisionService: non-blocking EventLog sink + worker thread. It must NEVER block the caller."""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any, Callable

from vention_printer_interface.vision.events import CaptureRequest, label_to_stage
from vention_printer_interface.vision.frame_source import FrameSource
from vention_printer_interface.vision.registration import Calibration, warp_to_bed
from vention_printer_interface.vision.store import write_capture

log = logging.getLogger(__name__)


class VisionService:
    def __init__(self, source: FrameSource, run_dir_provider: Callable[[], Path | None],
                 calibration: Calibration | None = None, queue_max: int = 16) -> None:
        self._source = source
        self._run_dir_provider = run_dir_provider
        self._calibration = calibration
        self._q: "queue.Queue[CaptureRequest]" = queue.Queue(maxsize=queue_max)
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._idle = threading.Event(); self._idle.set()
        self.drops = 0

    # ---- the EventLog sink: enqueue and return, nothing else -------------------------------
    def on_event(self, label: str, data: dict[str, Any]) -> None:
        stage = label_to_stage(label)
        if stage is None:
            return
        req = CaptureRequest(
            layer=int(data.get("layer", 0)), stage=stage,
            host_timestamp_ns=int(data.get("host_timestamp_ns", 0)),
            axis_positions_mm=dict(data.get("axis_positions_mm", {})),
            job=dict(data.get("job", {})),
        )
        try:
            self._q.put_nowait(req)
        except queue.Full:
            try:  # drop oldest, enqueue newest
                self._q.get_nowait(); self.drops += 1
                self._q.put_nowait(req)
            except queue.Empty:
                self.drops += 1

    def start(self) -> None:
        self._source.open()
        self._worker = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=3.0)
        self._source.close()

    def drain(self, timeout: float = 2.0) -> None:  # test/util: wait until queue is empty + idle
        end = threading.Event()
        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self._q.empty() and self._idle.is_set():
                return
            time.sleep(0.01)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                req = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._idle.clear()
            try:
                self._process(req)
            except Exception as exc:  # noqa: BLE001 - a capture failure must never crash the worker
                log.warning("vision capture failed (layer %s %s): %s", req.layer, req.stage, exc)
            finally:
                self._idle.set()

    def _process(self, req: CaptureRequest) -> None:
        base = self._run_dir_provider() or None
        if base is None:
            log.debug("no active run dir; dropping capture layer %s %s", req.layer, req.stage)
            return
        frame = self._source.grab()
        raw = frame.image
        if self._calibration is not None:
            registered = warp_to_bed(raw, self._calibration.H, self._calibration.mm_per_px,
                                     self._calibration.bed_extent_mm)
            reg_space = {"mm_per_px": self._calibration.mm_per_px,
                         "bed_extent_mm": list(self._calibration.bed_extent_mm)}
        else:
            registered, reg_space = raw, None
        meta = {
            "run_id": Path(base).name, "layer": req.layer, "stage": req.stage,
            "host_timestamp_ns": req.host_timestamp_ns or frame.timestamp_ns,
            "job": req.job, "axis_positions_mm": req.axis_positions_mm,
            "capture_settings": frame.settings, "registered_space": reg_space,
            "calibration_version": getattr(self._calibration, "version", None),
        }
        write_capture(Path(base), layer=req.layer, stage=req.stage,
                      raw=raw, registered=registered, meta=meta)
```

> Note: `_idle`/`drain` give tests a deterministic wait without arbitrary sleeps. The four tests together prove the contract: files written, non-capture ignored, grab error swallowed, and **sink returns in <50 ms even with a 1 s grab**.

- [ ] **Step 3: Run → PASS (all four); ruff; mypy.** `cd backend && uv run pytest tests/test_vision_capture.py -q && uv run ruff check vision/ && uv run mypy vision/`
- [ ] **Step 4: Commit.** `git commit -m "feat(vision): VisionService non-blocking sink + capture worker"`

---

## Phase 5 — Controller integration

### Task 10: Recorder exposes the active run dir

**Files:** Modify `recording/recorder.py`, `tests/test_recorder.py`

- [ ] **Step 1: Failing test** — after `recorder.start(...)`, `recorder.current_run_dir` is a `Path` that exists; after `recorder.stop()`, it is `None`. (Match the existing `test_recorder.py` fixture style.)
- [ ] **Step 2: Implement** a `current_run_dir` property returning the active run `Path` (the dir already created in `start`) or `None` when not recording. Do not change existing behavior.
- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(recording): expose current_run_dir for co-located artifacts"`

### Task 11: Capture marks in compile_print

**Files:** Modify `control/print_settings.py`, `tests/test_print_settings.py`

- [ ] **Step 1: Failing test** — compile a small plan with `capture_stages=True`; assert the step labels include, per layer and in order, `capture:pre_jet` before the jet pass, `capture:post_jet` after it, and `capture:post_heat` after the heater dwell; and that each capture `mark` sits at a point where the printhead/recoater are already parked (assert the immediately-preceding `move_abs`/`wait` positions match `printhead_start_mm` / recoater home). With `capture_stages=False`, no `capture:*` marks appear.

```python
def test_capture_marks_emitted_at_parked_points():
    plan = PrintSettings(total_layers=1, capture_stages=True)  # + minimal required fields
    steps = compile_print(plan)
    labels = [s.label for s in steps if s.kind == "mark"]
    assert labels.count("capture:pre_jet") == 1
    assert labels.index("capture:pre_jet") < labels.index("capture:post_jet") < labels.index("capture:post_heat")

def test_capture_marks_absent_when_disabled():
    steps = compile_print(PrintSettings(total_layers=1, capture_stages=False))
    assert not any(s.label.startswith("capture:") for s in steps if s.kind == "mark")
```

Run → FAIL.

- [ ] **Step 2: Implement** — add `capture_stages: bool = True` to `PrintSettings`; in `compile_print`, guard `add("mark", label="capture:pre_jet")` / `"capture:post_jet"` / `"capture:post_heat"` at the existing bed-clear points (after coat + printhead parked at `printhead_start_mm`; after the jet pass + park; after the heater dwell + park). Emit only when `plan.capture_stages`.
- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(print): emit capture:* marks at bed-clear stages"`

---

## Phase 6 — API wiring & endpoints

### Task 11b: Cross-platform camera config (cameras.py)

**Files:** Create `vision/cameras.py`, `tests/test_vision_cameras.py`

- [ ] **Step 1: Failing test** — `default_backend()` returns the right `cv2.CAP_*` per OS (mock `platform.system()`), and `CameraConfig` resolves overview/science device selection from a dict:

```python
from unittest.mock import patch
from vention_printer_interface.vision.cameras import default_backend, CameraConfig


def test_default_backend_per_os():
    import cv2
    with patch("platform.system", return_value="Darwin"):
        assert default_backend() == cv2.CAP_AVFOUNDATION
    with patch("platform.system", return_value="Linux"):
        assert default_backend() == cv2.CAP_V4L2
    with patch("platform.system", return_value="Windows"):
        assert default_backend() == cv2.CAP_DSHOW


def test_camera_config_roles():
    cfg = CameraConfig.from_dict({"science": {"index": 1}, "overview": {"index": 0}})
    assert cfg.science.index == 1 and cfg.overview.index == 0
    assert cfg.science.backend == default_backend()  # inherits OS default when unspecified
```

Run → FAIL.

- [ ] **Step 2: Implement `vision/cameras.py`** — `default_backend()` maps `platform.system()` → `cv2.CAP_AVFOUNDATION`/`cv2.CAP_V4L2`/`cv2.CAP_DSHOW` (fallback `cv2.CAP_ANY`); `@dataclass CameraSpec{index:int=0, path:str|None=None, backend:int|None=None, width:int|None, height:int|None}` (backend defaults to `default_backend()` when None); `@dataclass CameraConfig{overview:CameraSpec, science:CameraSpec}` with `from_dict`/`from_env`. `import cv2` lazily inside `default_backend()` so the module imports even where cv2 constants differ.

- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): cross-platform camera config + per-OS capture backend"`

### Task 12: Construct + wire VisionService

**Files:** Modify `api/app.py`, `vision/cameras.py` (new), `tests/test_api_vision.py`

- [ ] **Step 1: Failing test** (`test_api_vision.py`, mirror `test_api_priming.py` fixtures) — `GET /api/vision/status` returns 200 with `{"cameras": [...], "calibration": null|..., "queue": {"drops": 0}}`; with a simulated source injected via `create_app(..., vision_source=SimulatedFrameSource())`, driving a print through a `capture:*` event writes a file under the run dir.
- [ ] **Step 2: Implement** — add a `vision_source: FrameSource | None = None` param to `create_app`; load `CameraConfig.from_env()` (Task 11b); construct `VisionService(source=vision_source or UvcFrameSource(cfg.science.index, cfg.science.width, cfg.science.height, cfg.science.backend), run_dir_provider=lambda: recorder.current_run_dir, calibration=load_calibration(root/".vision_calibration.json"))`; `events.add_sink(vision.on_event)`; `vision.start()` on startup, `vision.stop()` on shutdown; store `app.state.vision`. Register a `/api/vision` router (below). Guard camera construction so a missing device never blocks app startup (log + serve without capture).
- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(api): wire VisionService as an EventLog sink"`

### Task 13: Vision REST endpoints

**Files:** Modify `api/app.py` (or new `api/vision_routes.py`), `tests/test_api_vision.py`

- [ ] **Step 1: Failing tests** — `GET /api/vision/cameras` lists roles; `GET /api/vision/captures?run=<r>` returns the manifest list; `POST /api/vision/calibrate` with posted image points + world points + mm/px + bed extent computes a homography, saves it, and returns the reprojection error; `GET /api/vision/overview/stream` returns `200` with content-type `multipart/x-mixed-replace` (assert headers only; read one boundary).
- [ ] **Step 2: Implement** the four routes using the modules from Phases 2–4. `calibrate` calls `compute_homography` + `reprojection_error` + `save_calibration` and hot-swaps `app.state.vision._calibration`.
- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(api): vision status/cameras/captures/calibrate/overview endpoints"`

### Task 14: Overview MJPEG generator

**Files:** Create `vision/overview.py`, `tests/test_vision_overview.py`

- [ ] **Step 1: Failing test** — `mjpeg_chunk(frame_bytes)` returns a bytes chunk beginning with `--frame` boundary and `Content-Type: image/jpeg`; `encode_jpeg(np_image)` returns non-empty bytes starting with the JPEG magic `\xff\xd8`.
- [ ] **Step 2: Implement** `encode_jpeg` (`cv2.imencode(".jpg", img)`) and `mjpeg_chunk` (boundary framing). The streaming endpoint (Task 13) loops a source `.grab()` → `encode_jpeg` → `mjpeg_chunk` in a `StreamingResponse`.
- [ ] **Step 3: Run → PASS; ruff; commit.** `git commit -m "feat(vision): MJPEG encoding for the overview stream"`

---

## Phase 7 — Frontend

### Task 15: Register the Cameras view

**Files:** Modify `src/lib/console.ts`, `src/lib/console.test.ts`

- [ ] **Step 1: Failing test** — `VIEWS` includes `"cameras"` and `View` accepts it (add an assertion to `console.test.ts`).
- [ ] **Step 2: Implement** — add `"cameras"` to the `VIEWS` array + `View` union; add default order/sizes entries if the console layout requires them.
- [ ] **Step 3: Run → PASS.** `cd frontend && npm test`
- [ ] **Step 4: Commit.** `git commit -m "feat(ui): register cameras view"`

### Task 16: Pure vision UI logic

**Files:** Create `src/lib/vision.ts`, `src/lib/vision.test.ts`

- [ ] **Step 1: Failing tests** — `overviewStreamUrl(base)` → `${base}/api/vision/overview/stream`; `parseCaptures(json)` maps the manifest into `{layer, stage, url}[]` sorted by layer then stage order (`pre_jet<post_jet<post_heat`); `panelVisible(view, store)` / `setPanelVisible(view, v, store)` persist per-view booleans (inject a fake storage object; default visible=true).
- [ ] **Step 2: Implement** `src/lib/vision.ts` with those pure functions (storage injected for testability, matching how `console.ts` handles persistence).
- [ ] **Step 3: Run → PASS; commit.** `git commit -m "feat(ui): vision lib (urls, capture parsing, panel persistence)"`

### Task 17: OverviewCameraPanel component

**Files:** Create `src/components/OverviewCameraPanel.tsx`

- [ ] **Step 1: Implement** — a collapsible panel showing `<img src={overviewStreamUrl(base)}>` with a show/hide toggle backed by `panelVisible`/`setPanelVisible`, an `onError` fallback (placeholder + "overview camera unavailable"), and a title. Props: `{ base: string; view: View }`. (Components are not unit-tested by `node --test`; verified via build + browser.)
- [ ] **Step 2: Verify build.** `cd frontend && npm run build`
Expected: `tsc` + `vite` succeed, no type errors.
- [ ] **Step 3: Commit.** `git commit -m "feat(ui): reusable OverviewCameraPanel"`

### Task 18: CamerasView + embed panel on Control/Prime/Print

**Files:** Create `src/components/views/CamerasView.tsx`; modify `src/App.tsx`, `PrintView.tsx`, `PrimingView.tsx`, `ControlView.tsx`

- [ ] **Step 1: Implement** — `CamerasView`: full overview stream, latest science stills per stage for the current layer (from `/api/vision/captures`), the calibration workflow form (post points → show reprojection error), and a capture browser. Render `<CamerasView>` in `App.tsx` when `ui.view === "cameras"`. Embed `<OverviewCameraPanel base={base} view="control|priming|print" />` into each of the three views.
- [ ] **Step 2: Verify build.** `cd frontend && npm run build` → succeeds.
- [ ] **Step 3: Commit.** `git commit -m "feat(ui): Cameras view + embedded overview on control/prime/print"`

---

## Phase 8 — Hardware bring-up (manual verification gate)

Not unit-testable; verify live at the machine and record results in the run notes.

- [ ] **Step 1:** Plug the UVC 4K science cam + overview cam; enumerate devices (`uv run python -c "import cv2; [print(i, cv2.VideoCapture(i).isOpened()) for i in range(4)]"`) and set overview/science via `CameraConfig` env/JSON. **Enumeration + capture backend differ per OS** — indices are not portable; on Linux prefer `/dev/video*` paths, on Windows the DirectShow order. `default_backend()` picks AVFoundation/V4L2/DSHOW automatically; override per camera only if a device misbehaves.
- [ ] **Step 2:** Start the backend (`uv run vpi-serve`), open the Cameras view, confirm overview stream renders and the embedded panels show on Control/Prime/Print.
- [ ] **Step 3:** Place the ChArUco/checkerboard target on the bed; run the calibration workflow; confirm reprojection error is small (< ~1 px). Confirm the parked positions (printhead 250, recoater ~5) leave the bed unobstructed in-frame; adjust mount/FOV or the `mark` placement if not.
- [ ] **Step 4:** Run a short dry/real print with `capture_stages=True`; confirm `<run>/vision/layer_0001/{pre_jet,post_jet,post_heat}.png` appear, registered images are square-to-bed, and sidecars carry correct layer/stage/positions.
- [ ] **Step 5:** Confirm no motion stutter with the camera attached (the non-blocking contract holds in practice).

---

## Final review

After all tasks: run full suites (`cd backend && uv run pytest -q && uv run ruff check . && uv run mypy vention_printer_interface/vision/`; `cd frontend && npm test && npm run build`), dispatch a final code review, then use **superpowers:finishing-a-development-branch** to merge `feat/layerwise-vision`.

---

## Addendum — 2026-09-13: finalized cameras, corrected registration, capture freshness

This addendum supersedes the camera model and registration approach in the tasks above. Phases 1–2 (basic `frame_source.py`, homography-only `registration.py`) are already committed and are **extended**, not rewritten. All TDD/cross-platform/quality-gate rules from the top of this plan still apply. Do these in place of / in addition to the noted tasks.

### A1 — Extend `UvcFrameSource` (supersedes/extends Task 3)
Add resolution + **pixel-format (FOURCC)** negotiation and **actual-mode readback**:
- `configure(width, height, pixel_format="YUY2"|"MJPG", fps=None, exposure=…, gain=…, white_balance=…)`. In `open()`, set `CAP_PROP_FOURCC` (via `cv2.VideoWriter_fourcc(*fourcc)`), width/height/fps, then **read them back** (`get(CAP_PROP_FRAME_WIDTH/HEIGHT/FPS/FOURCC)`) and store both **requested and actual** in `Frame.settings` (`{"requested": {...}, "actual": {...}}`).
- Read back controls where available: `CAP_PROP_EXPOSURE/GAIN/WB_TEMPERATURE/AUTO_EXPOSURE/AUTO_WB` → store, `null` when the driver won't report.
- **Fresh grab:** set `CAP_PROP_BUFFERSIZE=1` in `open()` and add `grab_fresh(discard=2)` that reads-and-discards N frames then returns the next — used for stage captures. TDD the FOURCC-decode and requested-vs-actual mapping with a **fake capture object** (inject a stub exposing `get/set/read`); no real hardware. Keep `SimulatedFrameSource` returning `{"requested":..., "actual":...}` shaped settings so downstream tests are realistic.

### A2 — Extend registration to the corrected pipeline (extends Tasks 4–6)
Extend `Calibration` (keep existing `H`, `mm_per_px`, `bed_extent_mm`, `version`, `reprojection_error`; **add** `camera_matrix: np.ndarray (3×3)`, `dist_coeffs: np.ndarray`, `distortion_model: str = "opencv-5"`, `image_size: tuple[int,int]`, `validation: dict`). `load_calibration` must tolerate old files missing the intrinsic fields (→ `camera_matrix=None`, homography-only, log a warning) for back-compat with Phase-2 files.
New pure functions + TDD (synthetic, hardware-free):
- `calibrate_intrinsics(object_points, image_points, image_size) -> (K, dist, rms)` (wrap `cv2.calibrateCamera`). Test: feed points generated from a known `K`/zero-distortion and assert recovery + small rms.
- `undistort_points(pts, K, dist)` / `undistort_image(img, K, dist)`.
- `build_bed_remap(K, dist, H, mm_per_px, bed_extent_mm) -> (map1, map2)` — precompute a **single fused** undistort+perspective map (via `cv2.initUndistortRectifyMap`-style or manual grid → `undistortPoints` → homography → `cv2.remap`). Test output dimensions == grid from mm/px, and that with `dist=0` and `K=eye`-scaled it agrees with `warp_to_bed` (the fused path must match the two-step path to sub-pixel).
- `validate_dimensions(known_points_mm, measured_points_mm) -> {"rms_mm":…, "max_mm":…, "points":[…]}`.
The worker uses `build_bed_remap` once (cache), then `cv2.remap` per frame. `warp_to_bed` (Task 5) stays for the homography-only/back-compat path.

### A3 — `cameras.py` for the two ELP modules + role identity (supersedes Task 11b)
Two `CameraSpec`s carrying `role`, `model`, `asin`, `stable_id` (USB path/serial where available), `index`, `width`, `height`, `pixel_format`, `fps`, `backend` (from `default_backend()`):
- Overview: `ELP-U3CAM20MP01-KV100` / `B0GMFM4CJV`, 1920×1080@30 MJPG.
- Science: `ELP-U3CAM20MP01-IB(5-50B)` / `B0GMFN5RTD`, 5120×3840, prefer YUY2@7.5 else MJPG@27.5.
Keep `default_backend()` + its per-OS test. **Because both share the AR2020 sensor and enumerate alike, do not trust index/name:** add `identify(preview_provider)` support and an API preview so the operator confirms roles; persist the chosen `stable_id`→role mapping. Unit-test the mapping/selection logic with stubbed device lists (hardware-free).

### A4 — Fresh capture + expanded metadata (extends Tasks 7 & 9)
- `VisionService` worker calls `source.grab_fresh()` (not `grab()`) for stage captures, records `frame_timestamp_ns`, and — when the event carries a timestamp — must not accept a frame older than the event (else re-grab/log).
- Registered image = `cv2.remap` via the fused `build_bed_remap` when intrinsics exist, else `warp_to_bed`. `"raw"` sidecar image is the **original unwarped decoded frame** (not Bayer RAW).
- `store.write_capture` sidecar/`meta` gains the fields in the spec's Data-model JSON: `camera{role,model,asin,device_id,device_index}`, `capture{requested,actual}`, `controls{exposure,gain,white_balance,auto_*}` (`null` when unknown), `lens_notes`, `calibration{version,image_size,camera_matrix,distortion_model,distortion_coeffs,bed_homography,validation}`, `frame_timestamp_ns`. Extend `test_vision_store.py`/`test_vision_capture.py` accordingly.

### A5 — Phase 8 hardware acceptance (replaces Phase 8 list)
Use the spec's **Hardware acceptance checks** section verbatim: identity + supported modes on host; simultaneous overview stream + full-res science capture; exposure/gain/WB locking through the backend; focus/sharpness across the **tilted** bed at ~2 ft / 30–45°; iris operation + setting retention; cross-bed dimensional validation vs independent known dimensions; capture-freshness (no stale frame mislabeled); repeatable diffuse lighting. Record all results.
