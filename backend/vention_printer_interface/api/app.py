"""FastAPI app (spec §5). GET /api/status and /ws/telemetry are the same payload.

Cross-origin policy is copied from FLIR/T&C: cross-origin state-changing /api/ requests must carry
``X-VPI-Client: 1``; CORS allows the hosted-site origin plus localhost.
"""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import io
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vention_printer_interface import __version__
from vention_printer_interface.analysis import plotting
from vention_printer_interface.analysis.dimensional import (
    DEFAULTS,
    _read_mm_per_px,
    _select_capture,
    _sidecar_path_for,
    analyze_run,
    load_report,
)
from vention_printer_interface.analysis.lane_b import analyze_lane_b_from_pngs
from vention_printer_interface.control.backlash_cal import (
    BacklashResult,
    default_positions,
    perturbed_positions,
    preflight_problems,
    validate_probe,
)
from vention_printer_interface.control.backlash_history import (
    list_backlash,
    load_backlash,
    save_backlash,
)
from vention_printer_interface.control.backlash_routine import BacklashRoutine
from vention_printer_interface.control.controller import REFERENCE_MATCH_TOL_MM, Controller
from vention_printer_interface.control.events import EventLog
from vention_printer_interface.control.heater_model import exposure
from vention_printer_interface.control.limits_store import load_limits, save_limits
from vention_printer_interface.control.macros import MACROS, macro_steps
from vention_printer_interface.control.meteor import HotFolderMeteorAdapter
from vention_printer_interface.control.primed_state import PrimedState, load_primed, save_primed
from vention_printer_interface.control.priming import PrimingSettings, compile_priming_setup
from vention_printer_interface.control.priming_store import load_priming, save_priming
from vention_printer_interface.control.print_controller import PrintController, PrintState
from vention_printer_interface.control.print_settings import (
    PrintSettings,
    compile_print,
    estimate_duration_s,
)
from vention_printer_interface.control.print_settings_store import (
    load_print_settings,
    save_print_settings,
)
from vention_printer_interface.control.reference_store import load_reference, save_reference
from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits
from vention_printer_interface.control.settle import settle
from vention_printer_interface.device import create_transport, registered_transports
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.jobs.store import (
    JobInfo,
    JobStore,
    layer_png,
    layer_png_scaled,
    load_job,
    preview_png,
)
from vention_printer_interface.offload import (
    OffloadJob,
    drive_dict,
    list_drives,
    offload_plan,
)
from vention_printer_interface.paths_config import (
    APP_DIR_NAME,
    PathsConfig,
    ResolvedRoot,
    config_path,
    load_persistent_paths,
    resolve_experiments_root,
    resolve_jobs_root,
    save_persistent_paths,
)
from vention_printer_interface.protocol import routes as r
from vention_printer_interface.recording.libraries import (
    merge_runs,
    resolve_run_across,
    run_roots,
)
from vention_printer_interface.recording.recorder import Recorder, list_runs_in
from vention_printer_interface.timing_config import TimingConfig, load_timing, save_timing
from vention_printer_interface.vision.avfoundation import list_avf_cameras
from vention_printer_interface.vision.board_gen import (
    generate_charuco_dxf,
    generate_charuco_svg,
    resolve_preset,
)
from vention_printer_interface.vision.cameras import (
    CameraConfig,
    CameraSpec,
    camera_access_state,
    enumerate_devices,
    load_camera_settings,
    load_role_map,
    resolve_roles,
    save_camera_settings,
    save_role_map,
    unresolved_roles,
)
from vention_printer_interface.vision.capture import (
    VisionService,
    image_has_usable_content,
    store_uploaded,
)
from vention_printer_interface.vision.center_sweep import best_center_pose
from vention_printer_interface.vision.circle_detect import center_offset_px, detect_piston_circle
from vention_printer_interface.vision.coverage import coverage
from vention_printer_interface.vision.events import label_to_stage
from vention_printer_interface.vision.frame_source import (
    AVFoundationFrameSource,
    FrameSource,
    UvcFrameSource,
)
from vention_printer_interface.vision.overview import OverviewStreamer, encode_jpeg
from vention_printer_interface.vision.registration import (
    BoardDetection,
    BoardSpec,
    Calibration,
    apply_homography,
    calibrate_intrinsics,
    calibrate_intrinsics_boards,
    calibration_validation_warning,
    compute_homography,
    detect_board,
    load_calibration,
    load_validation,
    reprojection_error,
    rigid_transform_2d,
    save_calibration,
    save_validation,
    undistort_points,
    validate_dimensions,
    view_tilt_deg,
)
from vention_printer_interface.vision.store import read_manifest, write_overview_frame

log = logging.getLogger(__name__)

API_VERSION = "0.1"
LOCAL_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
CLIENT_HEADER = "x-vpi-client"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
RUN_FILES = frozenset(
    {
        "telemetry.csv",
        "events.json",
        "metadata.json",
        "manifest.json",
        "layers.csv",
        "motion_profiles.csv",
        "layer_accuracy.csv",
    }
)
VISION_FILE_MEDIA_TYPES = {".webp": "image/webp", ".png": "image/png", ".json": "application/json"}
_DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
DEFAULT_HEATER_IO: tuple[int, int] = (1, 0)  # UNVERIFIED: identify during commissioning
OPERATOR_RESTART_DELAY_S = 0.4  # let the HTTP response flush before the process replaces itself


def schedule_operator_restart(delay_s: float = OPERATOR_RESTART_DELAY_S) -> None:
    """Replace THIS operator process with a fresh copy of itself (same interpreter, same argv),
    after a short delay so the POST /api/operator/restart response reaches the browser first.

    os.execv keeps the PID and re-runs the exact command line, so it works whether the operator
    was launched by `uv run`, a launchd/KeepAlive agent, or by hand — no external supervisor is
    required. Serving the console-script entry through the interpreter (sys.executable + sys.argv)
    avoids depending on the entry file's executable bit / shebang. Module-level so tests can patch
    it away without actually re-execing the test process."""

    def _do() -> None:
        time.sleep(delay_s)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=_do, daemon=True, name="operator-restart").start()


def _vision_file_url(run: str, rel_path: str) -> str:
    """URL for GET /api/vision/runs/{run}/file?path=<rel_path> (see that route below).
    `rel_path` is a run-relative POSIX path such as "vision/layer_0001/post_jet.png"."""
    return f"/api/vision/runs/{quote(run, safe='')}/file?path={quote(rel_path, safe='')}"


def _sidecar_rel_path(registered_rel_path: str) -> str:
    """The sidecar JSON's run-relative path for a registered image's run-relative path
    (vision/store.py writes both `<stage>.png` and `<stage>.json` in the same directory)."""
    stem, _, _ext = registered_rel_path.rpartition(".")
    return f"{stem or registered_rel_path}.json"


def _spec_to_settings(spec: CameraSpec) -> dict[str, Any]:
    """The operator-facing settings view of a CameraSpec (GET /api/vision/settings)."""
    return {
        "resolution": [spec.width, spec.height],
        "fps": spec.fps,
        "format": spec.pixel_format,
        "exposure": spec.exposure,
    }


def _parse_resolution(resolution: list[int] | str) -> tuple[int, int]:
    """Accept [width, height] or a "WxH" string; return (width, height)."""
    if isinstance(resolution, str):
        w_str, _, h_str = resolution.lower().partition("x")
        return int(w_str), int(h_str)
    return int(resolution[0]), int(resolution[1])


def _settings_to_override(settings: CameraRoleSettings) -> dict[str, Any]:
    """Translate an operator settings payload into CameraSpec-field overrides (only set fields)."""
    override: dict[str, Any] = {}
    if settings.resolution is not None:
        override["width"], override["height"] = _parse_resolution(settings.resolution)
    if settings.fps is not None:
        override["fps"] = float(settings.fps)
    if settings.format is not None:
        override["pixel_format"] = settings.format
    if settings.exposure is not None:
        override["exposure"] = float(settings.exposure)
    return override


def install_cross_origin_policy(app: FastAPI, *, site_origin: str | None) -> None:
    def _cross_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        host = request.headers.get("host", "")
        return origin.split("://", 1)[-1] != host

    @app.middleware("http")
    async def _client_header_guard(request: Request, call_next: Any) -> Any:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and _cross_origin(request)
            and request.headers.get(CLIENT_HEADER) != "1"
        ):
            detail = "browser requests must send the X-VPI-Client: 1 header"
            return JSONResponse({"detail": detail}, 403)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[site_origin] if site_origin else [],
        allow_origin_regex=LOCAL_ORIGIN_RE,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", CLIENT_HEADER],
        allow_private_network=True,
        max_age=600,
    )


class ConnectBody(BaseModel):
    backend: str
    ip: str | None = None
    heater_io: tuple[int, int] | None = None


class HomeBody(BaseModel):
    axes: list[int] = Field(default_factory=list)


class MoveBody(BaseModel):
    axis: int = Field(ge=1, le=4)
    mode: str = Field(pattern="^(abs|rel)$")
    mm: float


class StopBody(BaseModel):
    axes: list[int] = Field(default_factory=list)


class ControllerMover:
    """Adapts the live controller to the backlash routine's ``Mover`` protocol: absolute moves plus
    an in-process settle that polls the controller snapshot (same settle logic as the sweep)."""

    def __init__(self, controller: Any, settle_timeout_s: float = 30.0) -> None:
        self._ctrl = controller
        self._timeout_s = settle_timeout_s

    def move_abs(self, axis: int, mm: float) -> None:
        self._ctrl.move_absolute(axis, mm)

    def settle(self, axis: int) -> float:
        return settle(self._ctrl.snapshot, axis, timeout_s=self._timeout_s)


class BacklashStartBody(BaseModel):
    axis: int = Field(ge=1, le=2)  # 1 = build piston, 2 = feed piston
    positions: list[float] | None = None  # None -> safe defaults from the piston's max travel
    d_mm: float = Field(default=2.0, gt=0)
    reps: int = Field(default=8, ge=1, le=50)
    verify: bool = False  # re-measure at the midpoints BETWEEN the default depths (perturbed check)


class BacklashApplyBody(BaseModel):
    axis: int = Field(ge=1, le=2)


class PlotValidationBody(BaseModel):
    residuals_mm: list[float]  # absolute per-gap scale errors (ScaleResult.residuals_mm)
    target_mm: float = Field(default=0.05, gt=0)


class PlotSweepBody(BaseModel):
    rows: list[dict[str, Any]]  # piston_sweep.py rows: commanded_mm, deviation_mm, direction, ...


class CenterSweepStartBody(BaseModel):
    start_mm: float | None = None  # center of the sweep; None -> current capture_recoater_mm
    span_mm: float = Field(default=8.0, gt=0)  # sweep ±span around start
    step_mm: float = Field(default=1.0, gt=0)


class CenterSweepApplyBody(BaseModel):
    recoater_mm: float = Field(ge=0)


class OffloadStartBody(BaseModel):
    dest: str  # a mounted drive path (from /api/offload/drives)
    runs: list[str] | None = None  # None -> copy every run not already on the drive
    move: bool = False  # True -> MOVE (copy, verify, then delete the local source to free space)


class AxisMotionBody(BaseModel):
    max_speed: float | None = None
    max_accel: float | None = None


class LimitsBody(BaseModel):
    max_speed: dict[int, float] | None = None
    max_accel: dict[int, float] | None = None
    travel_min: dict[int, float] | None = None
    travel_max: dict[int, float] | None = None
    heater_max_on_s: float | None = None
    telemetry_timeout_s: float | None = None
    near_limit_mm: float | None = None


class RecordingStartBody(BaseModel):
    name: str = "run"
    notes: str = ""


class RecordingMetaBody(BaseModel):
    """PUT /api/recordings/{run}/meta body: edit a run's name and/or notes (both optional)."""

    name: str | None = None
    notes: str | None = None


class PrintStartBody(BaseModel):
    single_step: bool = False
    name: str = ""
    notes: str = ""


class AutoLogBody(BaseModel):
    enabled: bool


class SingleStepBody(BaseModel):
    on: bool


class SeekBody(BaseModel):
    index: int


class JobSelectBody(BaseModel):
    path: str


class IntrinsicsView(BaseModel):
    object_points: list[tuple[float, float, float]]
    image_points: list[tuple[float, float]]


class IntrinsicsBody(BaseModel):
    image_size: tuple[int, int]
    views: list[IntrinsicsView]


class CalibrationValidationBody(BaseModel):
    image_points: list[tuple[float, float]]
    world_points_mm: list[tuple[float, float]]


class VisionCalibrateBody(BaseModel):
    image_points: list[tuple[float, float]]
    world_points_mm: list[tuple[float, float]]
    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]
    intrinsics: IntrinsicsBody | None = None
    validation: CalibrationValidationBody | None = None


class RoleMapBody(BaseModel):
    """PUT /api/vision/roles body: the operator-confirmed stable_id -> role assignment."""

    mapping: dict[str, str]


class CameraRoleSettings(BaseModel):
    """One role's operator-facing camera settings (PUT /api/vision/settings)."""

    resolution: list[int] | str | None = None  # [width, height] or "WxH"
    fps: float | None = None
    format: str | None = None  # pixel format, e.g. "MJPG" / "YUY2"
    exposure: float | None = None


class CameraSettingsBody(BaseModel):
    """PUT /api/vision/settings body: per-role camera overrides (every role/field optional)."""

    overview: CameraRoleSettings | None = None
    science: CameraRoleSettings | None = None


class BoardSpecBody(BaseModel):
    """A calibration/validation board geometry (mirrors ``vision.registration.BoardSpec``)."""

    kind: Literal["charuco", "checkerboard"] = "charuco"
    squares_x: int = 0
    squares_y: int = 0
    square_length_mm: float = 0.0
    marker_length_mm: float = 0.0
    aruco_dict: str = "DICT_4X4_50"
    cols: int = 0
    rows: int = 0
    square_size_mm: float = 0.0


class CalibSessionBody(BaseModel):
    """POST /api/vision/calibrate/session body: the board to capture (default ChArUco)."""

    spec: BoardSpecBody | None = None


class CalibFinalizeBody(BaseModel):
    """POST /api/vision/calibrate/finalize body: raster scale + bed-plane correspondence.

    The bed homography is built EITHER from ``use_last_capture_as_bed`` (the last captured
    ChArUco view's own board object points in mm become the world coordinates) OR from an
    explicit ``bed_image_points`` <-> ``bed_world_points_mm`` correspondence.
    """

    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]
    image_size: tuple[int, int] | None = None
    use_last_capture_as_bed: bool = False
    bed_image_points: list[tuple[float, float]] | None = None
    bed_world_points_mm: list[tuple[float, float]] | None = None


class VisionValidateBody(BaseModel):
    """POST /api/vision/validate body: the checkerboard + its certified pitch (mm)."""

    spec: BoardSpecBody
    square_size_mm: float


_VALID_ROLES = {"overview", "science"}
_MIN_CALIB_VIEWS = 3
_DEFAULT_CALIB_SPEC = BoardSpec(
    kind="charuco",
    squares_x=7,
    squares_y=5,
    square_length_mm=20.0,
    marker_length_mm=15.0,
    aruco_dict="DICT_4X4_50",
)


def _grid_scale_bias(
    known_mm: np.ndarray, measured_mm: np.ndarray, pitch_mm: float
) -> float:
    """Ratio (measured mean pitch / certified pitch) over adjacent grid corner pairs.

    Adjacency is taken from the KNOWN grid (pairs one pitch apart); the measured distance of
    those same pairs is averaged. This is deliberately independent of the rigid alignment so a
    scale error that a scaled fit would hide is still surfaced (protocol §5.1, Analysis B).
    """
    known = np.asarray(known_mm, float)
    measured = np.asarray(measured_mm, float)
    n = len(known)
    iu, ju = np.triu_indices(n, k=1)
    known_d = np.sqrt(((known[iu] - known[ju]) ** 2).sum(axis=1))
    adjacent = np.abs(known_d - pitch_mm) < 0.25 * pitch_mm
    if not np.any(adjacent):
        return float("nan")
    measured_d = np.sqrt(((measured[iu[adjacent]] - measured[ju[adjacent]]) ** 2).sum(axis=1))
    return float(measured_d.mean() / pitch_mm)


def _board_spec(body: BoardSpecBody) -> BoardSpec:
    """Convert a request ``BoardSpecBody`` into a domain ``BoardSpec``."""
    return BoardSpec(
        kind=body.kind,
        squares_x=body.squares_x,
        squares_y=body.squares_y,
        square_length_mm=body.square_length_mm,
        marker_length_mm=body.marker_length_mm,
        aruco_dict=body.aruco_dict,
        cols=body.cols,
        rows=body.rows,
        square_size_mm=body.square_size_mm,
    )


def _tcp_open(ip: str, port: int, timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout_s):
            return True
    except OSError:
        return False


class CircleAnchor(BaseModel):
    """Operator-marked Ø100 mm outer circle in the capture's pixel space."""

    cx_px: float
    cy_px: float
    radius_px: float


class DimensionalAnalyzeRequest(BaseModel):
    """Optional body for POST /api/analysis/{run}/dimensional.

    All fields optional: an empty POST analyzes the default (post_jet) gold-standard
    capture with auto-located ROIs and the default nominals.
    """

    layer: int | None = None
    stage: str = "post_jet"
    rois: dict[str, list[int]] | None = None
    circle: CircleAnchor | None = None
    nominals: dict[str, Any] | None = None


def _resolve_run_dir(root: Path, run: str) -> Path:
    """Validate a recordings run name and return its directory.

    Uses the same traversal guard as the other recordings routes (the resolved directory must sit
    directly under ``root``): a traversal / bad name -> 400, an otherwise-valid but nonexistent
    run -> 404.
    """
    run_dir = (root / run).resolve()
    if run_dir.parent != root.resolve():
        raise HTTPException(400, "bad run")
    if not run_dir.is_dir():
        raise HTTPException(404, "unknown run")
    return run_dir


def _run_reveal_target(root: Path, run: str) -> Path:
    """Absolute path to reveal in Finder for a run: its metadata.json when present, else the run
    directory. Same within-root guard as the recordings routes — a traversing/bad name or a
    nonexistent run raises ``ValueError`` (the caller maps it to a 400). Touches nothing on disk
    beyond an ``exists()`` check, so it is safe to unit-test."""
    run_dir = (root / run).resolve()
    if run_dir.parent != root.resolve() or not run_dir.is_dir():
        raise ValueError("bad run")
    meta = run_dir / "metadata.json"
    return meta if meta.exists() else run_dir


def _fresh_axis_motion() -> dict[int, dict[str, float | None]]:
    return {n: {"max_speed": None, "max_accel": None} for n in (1, 2, 3, 4)}


def _attach(app: FastAPI, backend: str, ip: str | None, heater_io: tuple[int, int] | None) -> None:
    kwargs: dict[str, Any] = {}
    if backend == "machinemotion":
        kwargs["ip"] = ip or r.DEFAULT_IP_ETHERNET
    transport = create_transport(backend, **kwargs)
    device = PrinterDevice(transport, heater_io=heater_io or app.state.default_heater_io)
    # Lower the persist guard BEFORE the new poll loop starts, so an early tick can't overwrite the
    # saved reference seed with the fresh (unreferenced) state before we restore from it.
    app.state.reference_restored = False
    app.state.controller.attach_device(device, backend=backend)
    app.state.backend = backend
    app.state.axis_motion = _fresh_axis_motion()
    # Reconnect restore: if the MM kept power its positions are unchanged, so re-reference the axes
    # whose saved position still matches — this keeps a software disconnect from showing unref.
    seed = load_reference(app.state.experiments_root)
    if seed is not None:
        ctrl = app.state.controller
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and ctrl.snapshot().get("telemetry") is None:
            time.sleep(0.05)
        ctrl.restore_reference(seed[0], seed[1], REFERENCE_MATCH_TOL_MM)
    app.state.reference_restored = True


def choose_jobs_root(
    env_value: str | None, shared: Path, shared_exists: bool, fallback: Path
) -> tuple[Path, str | None]:
    """Pure decision for the default sliced-jobs folder. No filesystem I/O.

    Priority: an explicit ``VPI_JOBS_ROOT`` env value (per-machine override for a clone that
    lives OUTSIDE Dropbox, e.g. the Windows print PC) → the script-relative shared Dropbox Hot
    Folder, but only when it actually exists here (true on the Mac, where the code is inside
    Dropbox) → a last-resort fallback with a loud warning. Never silently return a bogus
    script-relative path: on the Windows standalone clone parents[5] resolves to
    ``C:\\Users\\code\\rfam-web\\Hot Folder`` which does not exist, so we must warn, not pretend.
    """
    if env_value:
        return Path(env_value), None
    if shared_exists:
        return shared, None
    return fallback, (
        f"No sliced-jobs folder found: the shared Dropbox Hot Folder ({shared}) is not next to "
        f"this code (a clone outside Dropbox?), so falling back to {fallback}. Pass --jobs-root "
        f"or set VPI_JOBS_ROOT to the machine's Hot Folder path."
    )


def resolve_default_jobs_root() -> ResolvedRoot:
    """Resolve the sliced-jobs folder when no ``--jobs-root`` is given, reporting its source.

    Priority: ``VPI_JOBS_ROOT`` env -> the PERSISTENT config (``~/.config/.../paths.json`` — the
    install-independent durable fix, survives reinstalls to a new clone) -> the script-relative
    shared Dropbox Hot Folder when it exists here -> a backend/jobs fallback that is FLAGGED loudly
    (``is_fallback``) and logged, never silently trusted (that fallback is the recurring
    wrong-directory bug — an empty local folder after a reinstall).
    """
    shared = Path(__file__).resolve().parents[5] / "code" / "rfam-web" / "Hot Folder"
    fallback = Path(__file__).resolve().parents[2] / "jobs"  # backend/jobs
    resolved = resolve_jobs_root(
        cli=None,
        env=os.environ.get("VPI_JOBS_ROOT"),
        config=load_persistent_paths().jobs_root,
        shared=shared,
        shared_exists=shared.is_dir(),
        fallback=fallback,
    )
    if resolved.is_fallback:
        log.warning(
            "No sliced-jobs folder configured: falling back to %s (an install-local folder that is "
            "empty after a reinstall). Set it in the UI (Setup -> data locations), pass "
            "--jobs-root, "
            "set VPI_JOBS_ROOT, or write ~/.config/%s/paths.json.",
            fallback, APP_DIR_NAME,
        )
    return resolved


def default_jobs_root() -> Path:
    """The sliced-jobs folder when no ``--jobs-root`` is given (see resolve_default_jobs_root)."""
    return resolve_default_jobs_root().path


def create_app(
    *,
    backend: str = "none",
    ip: str | None = None,
    poll_interval_s: float = 0.2,
    print_poll_interval_s: float | None = None,
    experiments_root: Path | None = None,
    limits: SafetyLimits | None = None,
    frontend_dist: Path | None = None,
    site_origin: str | None = None,
    heater_io: tuple[int, int] | None = None,
    # Fallback floor per wait step. With move-started detection (PrintController._blocking_done) a
    # wait after a real move ends as soon as the move finishes, so this only bites no-op moves and
    # is the safety margin against a stale "complete"; kept modest so the choreography stays fluid.
    print_min_wait_s: float = 0.25,
    print_step_timeout_s: float = 120.0,
    jobs_roots: list[Path] | None = None,
    vision_source: FrameSource | None = None,
    overview_source: FrameSource | None = None,
    device_enumerator: Callable[[], list[dict[str, Any]]] | None = None,
) -> FastAPI:
    # Experiments (runs) root: explicit arg -> VPI_EXPERIMENTS_ROOT env -> persistent config ->
    # CWD/experiments (install-local fallback, flagged loudly). Mirrors the jobs-root logic so a
    # reinstall to a new clone can't silently point runs at an empty local folder.
    _exp = resolve_experiments_root(
        cli=experiments_root,
        env=os.environ.get("VPI_EXPERIMENTS_ROOT"),
        config=load_persistent_paths().experiments_root,
        default=Path.cwd() / "experiments",
    )
    root = _exp.path
    # Print-timing knobs: a persisted UI value OVERRIDES the CLI/plist default (the Settings UI is
    # the source of truth for these — set once, survives restarts). Unset -> keep the CLI default.
    _timing = load_timing()
    if _timing.print_min_wait_s is not None:
        print_min_wait_s = _timing.print_min_wait_s
    if _timing.print_poll_interval_s is not None:
        print_poll_interval_s = _timing.print_poll_interval_s
    _jobs_resolved = (
        ResolvedRoot(jobs_roots[0], "cli", False)
        if jobs_roots
        else resolve_default_jobs_root()
    )
    jobs = JobStore(jobs_roots or [_jobs_resolved.path])
    vision_calibration_path = root / ".vision_calibration.json"
    vision_roles_path = root / ".vision_roles.json"
    vision_settings_path = root / ".vision_settings.json"
    # Operator-set AVFoundation unique id for the science camera (Phase-2 unattended capture). When
    # present, the server captures science by this STABLE per-camera id instead of a fragile index —
    # so the RIGHT camera is grabbed even with no browser tab open. Unset => current behavior.
    science_uid_path = root / ".vision_science_uid.json"
    # AVFoundation unique ids the operator has perpetually IGNORED (FaceTime, iPhone, etc.) so they
    # never clutter the science picker. Persisted server-side (survives browser changes, applies
    # unattended). A stable-id list, mirroring the science-uid file.
    ignored_cameras_path = root / ".vision_ignored_cameras.json"

    def load_science_uid() -> str | None:
        try:
            uid = json.loads(science_uid_path.read_text()).get("unique_id")
            return uid if isinstance(uid, str) and uid else None
        except (OSError, ValueError):
            return None

    def load_ignored_cameras() -> list[str]:
        try:
            uids = json.loads(ignored_cameras_path.read_text()).get("unique_ids")
            return [u for u in uids if isinstance(u, str) and u] if isinstance(uids, list) else []
        except (OSError, ValueError):
            return []

    def build_camera_config() -> CameraConfig:
        """CameraConfig from env/defaults, merged with any persisted per-role setting overrides.

        Overrides are stored in CameraSpec-field form, so from_dict layers them on top of the
        env-resolved specs -- picked up here the next time a camera is opened / roles refresh."""
        base = CameraConfig.from_env()
        overrides = load_camera_settings(vision_settings_path)
        if not overrides:
            return base
        merged: dict[str, dict[str, Any]] = {}
        for role, spec in (("overview", base.overview), ("science", base.science)):
            merged[role] = {**dataclasses.asdict(spec), **overrides.get(role, {})}
        return CameraConfig.from_dict(merged)

    camera_config = build_camera_config()
    enumerator = device_enumerator or enumerate_devices
    # macOS exposes OpenCV/AVFoundation camera indexes in a different order than browser and USB
    # enumeration. With two identical ELP cameras, opening the apparent science index can therefore
    # wake FaceTime or an iPhone Continuity Camera. Injected sources are deterministic and safe.
    server_science_fallback_blocked = platform.system() == "Darwin" and vision_source is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        controller = Controller(
            poll_interval_s=poll_interval_s,
            print_poll_interval_s=print_poll_interval_s,
            limits=limits or load_limits(root),
        )
        # The recorder tells the controller to poll faster while a run records (finer motion data).
        recorder = Recorder(root, on_active_change=controller.set_fast_poll)
        printer = PrintController(
            controller, min_wait_s=print_min_wait_s, step_timeout_s=print_step_timeout_s
        )
        app.state.auto_log = True
        app.state.auto_run_open = False
        # Browser science-capture client: capture_request is the "capture now" signal (seq ticks per
        # mark); science_client_until is the heartbeat deadline while a client is capturing. On
        # macOS the server index fallback is always blocked because it can select Continuity Camera.
        app.state.capture_request = None
        app.state.capture_seq = 0
        app.state.science_client_until = 0.0
        events = EventLog()
        events.add_sink(recorder.event)  # every event also lands in the durable run record

        def _vision_sink(label: str, data: dict[str, Any]) -> None:
            # Indirection so PUT /api/vision/roles can swap app.state.vision to a freshly
            # (re)opened VisionService without ever registering a second EventLog sink.
            stage = label_to_stage(label)
            if stage is not None:
                # Surface a "capture now" signal for the BROWSER (see it on the WS status): the
                # client grabs the still from the assigned science camera (right camera on macOS).
                app.state.capture_seq = getattr(app.state, "capture_seq", 0) + 1
                app.state.capture_request = {
                    "seq": app.state.capture_seq,
                    "layer": data.get("layer"),
                    "cad_layer": data.get("print_layer"),
                    "stage": stage,
                    "server_fallback_blocked": server_science_fallback_blocked,
                }
                # If a browser capture-client is live (recent heartbeat), IT captures — skip the
                # server cv2 grab (which mis-resolves between two identical cameras on macOS).
                if time.monotonic() < getattr(app.state, "science_client_until", 0.0):
                    return
                if server_science_fallback_blocked:
                    log.warning(
                        "science capture skipped for layer %s %s: browser has no usable frame and "
                        "unsafe macOS camera-index fallback is disabled",
                        data.get("layer"),
                        stage,
                    )
                    return
            vision = app.state.vision
            if vision is not None:
                vision.on_event(label, data)

        events.add_sink(_vision_sink)

        # Camera auto-connect + persistent role memory (A7): enumerate -> load the persisted
        # stable_id->role map -> resolve_roles, then auto-open the mapped overview+science
        # sources below (no per-device operator selection on a normal connect). `unresolved_roles`
        # is deliberately stricter than resolve_roles' index fallback -- it only trusts a role
        # whose device a currently-enumerated stable_id is CONFIRMED mapped to -- and is what
        # GET /api/vision/status's roles_resolved/unresolved (and the quick-start wizard) gate
        # on; auto-open itself still uses resolve_roles' best-effort fallback so a fresh machine
        # is never left with no cameras just because roles aren't confirmed yet.
        def refresh_role_resolution() -> dict[str, CameraSpec]:
            try:
                enumerated = enumerator()
            except Exception as exc:  # noqa: BLE001 - enumeration must never block startup
                log.warning("camera enumeration failed (%s); serving without auto-resolve", exc)
                enumerated = []
            mapping = load_role_map(vision_roles_path)
            resolved = resolve_roles(enumerated, mapping, camera_config)
            app.state.vision_enumerated_devices = enumerated
            app.state.vision_role_map = mapping
            app.state.vision_unresolved_roles = unresolved_roles(enumerated, mapping)
            return resolved

        # Vision: a science-camera capture worker fed by capture:* marks off the same EventLog.
        # Guard hardware: an absent/broken camera must never block or crash app startup.
        def open_science(spec: CameraSpec | None) -> None:
            # spec is None when the science role is unresolved (no assignable camera). Open NOTHING
            # then — never fall back to a default index, which would open the built-in/first camera
            # (the 2026-09-16 "FaceTime streamed despite no cameras detected" bug). An injected test
            # source still opens.
            science_uid = load_science_uid()
            # A configured AVFoundation unique id IS a resolution — open by it even when no
            # stable_id spec resolved (that is the whole point of the unattended-by-uid path).
            if spec is None and vision_source is None and not science_uid:
                app.state.vision = None
                app.state.vision_source = None
                return
            if vision_source is not None:
                source: FrameSource = vision_source
            elif science_uid:
                # Apply the science role's capture settings (resolution/fps/FORMAT — e.g. YUY2 for
                # uncompressed/lossless stills) to the server-side unique-id-bound capture.
                s = spec or camera_config.science
                source = AVFoundationFrameSource(
                    science_uid,
                    width=s.width if s else None,
                    height=s.height if s else None,
                    fps=s.fps if s else None,
                    pixel_format=s.pixel_format if s else None,
                )
            else:
                assert spec is not None  # guaranteed by the early return above
                source = UvcFrameSource(
                    spec.index, spec.width, spec.height, spec.effective_backend()
                )
            vision_svc = VisionService(
                source=source,
                run_dir_provider=lambda: recorder.current_run_dir,
                calibration=load_calibration(vision_calibration_path),
                camera_role="science",
            )
            try:
                vision_svc.start()
                app.state.vision = vision_svc
            except Exception as exc:  # noqa: BLE001 - a missing/broken camera must not block startup
                log.warning("vision service start failed (%s); serving without capture", exc)
                app.state.vision = None
            app.state.vision_source = source

        # Overview: a separate OVERVIEW camera for the live-view stream, distinct from the
        # science capture source above. Shared across stream clients via one OverviewStreamer
        # grabber thread — never falls back to the science source (that capture is owned by the
        # vision worker; a second reader racing its cv2.VideoCapture.read() is the I1 hazard).
        # Camera-on-demand: the streamer is only CONSTRUCTED here — it does not open the device.
        # The overview camera is opened lazily on the first stream viewer and released when the
        # last viewer disconnects (see OverviewStreamer), so it is never held open at idle. A
        # broken/absent camera therefore surfaces at stream time (503), never blocking startup.
        def open_overview(spec: CameraSpec | None) -> None:
            app.state.overview_source = None
            app.state.overview_streamer = None
            # spec is None when the overview role is unresolved (no assignable camera). Build
            # NOTHING then — never fall back to a default index, which would stream the built-in /
            # first camera (the 2026-09-16 "FaceTime in the overview panel despite no cameras
            # detected" bug). An injected test source still opens.
            if spec is None and overview_source is None:
                return
            # Hot-plug reconnect: on sustained grab failure the streamer rebuilds its source via
            # this factory, which RE-RESOLVES the overview camera's device index (the OS can hand
            # out a different index on replug) — so unplug/replug recovers the live feed by itself.
            def make_overview_source() -> FrameSource:
                resolved = refresh_role_resolution()
                ov = resolved.get("overview")
                if ov is None:
                    raise RuntimeError("overview camera not detected")
                return UvcFrameSource(ov.index, ov.width, ov.height, ov.effective_backend())

            try:
                factory = None if overview_source is not None else make_overview_source
                if overview_source is not None:
                    ov_source: FrameSource = overview_source
                else:
                    assert spec is not None  # guaranteed by the early return above
                    ov_source = UvcFrameSource(
                        spec.index, spec.width, spec.height, spec.effective_backend()
                    )
                app.state.overview_source = ov_source
                app.state.overview_streamer = OverviewStreamer(ov_source, source_factory=factory)
            except Exception as exc:  # noqa: BLE001 - constructing must never block startup
                log.warning("overview streamer setup failed (%s); serving without overview", exc)

        app.state.vision_refresh_role_resolution = refresh_role_resolution
        app.state.vision_open_science = open_science
        app.state.vision_open_overview = open_overview

        resolved = refresh_role_resolution()
        open_science(resolved.get("science"))
        open_overview(resolved.get("overview"))

        def on_print_event(label: str, data: dict[str, Any]) -> None:
            events.append(label, data)
            if label == "layer_completed":
                recorder.record_layer(data)
            if label in ("print_done", "print_aborted", "print_fault") and app.state.auto_run_open:
                app.state.auto_run_open = False
                recorder.stop()

        printer.on_event = on_print_event
        last_state = {"v": "disconnected"}

        def on_controller_state(snap: dict[str, Any]) -> None:
            if snap["state"] != last_state["v"]:
                last_state["v"] = snap["state"]
                if snap["state"] == "fault":
                    events.append("fault", {"reasons": snap["fault_reasons"]})

        # Persist the referenced-axis set + positions so reference survives a software reconnect
        # (guarded until restore has run so it never clobbers the saved seed; throttled for disk).
        ref_persist: dict[str, Any] = {"axes": None, "pos": {}}

        def persist_reference(snap: dict[str, Any]) -> None:
            if not getattr(app.state, "reference_restored", False):
                return
            tel = snap.get("telemetry")
            if not tel:
                return
            axes = {int(k) for k, v in (tel.get("referenced") or {}).items() if v}
            positions = {int(k): float(v) for k, v in tel["positions"].items()}
            prev_pos: dict[int, float] = ref_persist["pos"]
            # Save whenever the referenced set changes, or a referenced axis moved beyond the match
            # tolerance — so the saved positions stay within tol of reality and a reconnect matches.
            moved = any(
                abs(positions.get(a, 0.0) - prev_pos.get(a, 1e9)) > REFERENCE_MATCH_TOL_MM
                for a in axes
            )
            if axes != ref_persist["axes"] or moved:
                try:
                    save_reference(root, axes, positions)
                except OSError as exc:
                    log.warning("reference persist failed: %s", exc)
                ref_persist["axes"], ref_persist["pos"] = axes, positions

        # Order matters: the print controller ticks first so the recorder logs it.
        controller.add_listener(printer.tick)
        controller.add_listener(on_controller_state)
        controller.add_listener(recorder.record)
        controller.add_listener(persist_reference)
        app.state.events = events
        app.state.controller, app.state.recorder, app.state.printer = controller, recorder, printer
        app.state.print_settings = load_print_settings(root, controller.limits)
        app.state.priming = load_priming(root, controller.limits)
        app.state.primed = load_primed(root)
        app.state.experiments_root = root
        app.state.jobs = jobs  # the live JobStore, so /api/config/paths can re-point it
        # Surface how jobs/runs roots were resolved so the UI can shout when either fell back to an
        # empty install-local folder (the recurring wrong-directory bug), not fail silently.
        app.state.paths_info = {
            "jobs_root": str(_jobs_resolved.path),
            "jobs_root_source": _jobs_resolved.source,
            "jobs_root_is_fallback": _jobs_resolved.is_fallback,
            "experiments_root": str(root),
            "experiments_root_source": _exp.source,
            "experiments_root_is_fallback": _exp.is_fallback,
            "config_path": str(config_path()),
        }
        app.state.reference_restored = False
        app.state.job = None
        # Guided calibration-capture session (A6b): the active board + accumulated detections.
        app.state.calib_session_spec = None
        app.state.calib_session_views = []
        app.state.calib_session_image_size = None
        app.state.calib_session_cov = []
        app.state.backend = "none"
        app.state.default_heater_io = heater_io or DEFAULT_HEATER_IO
        app.state.axis_motion = _fresh_axis_motion()
        if backend != "none":
            try:
                _attach(app, backend, ip, heater_io)
            except Exception as exc:  # noqa: BLE001 - device may be absent; serve anyway
                log.warning("boot attach failed (%s); serving idle", exc)
        try:
            yield
        finally:
            if app.state.vision is not None:
                app.state.vision.stop()
            if app.state.overview_streamer is not None:
                app.state.overview_streamer.stop()
            if app.state.overview_source is not None:
                app.state.overview_source.close()
            recorder.stop()
            controller.stop()

    app = FastAPI(title="Vention Printer Interface", version=__version__, lifespan=lifespan)
    install_cross_origin_policy(app, site_origin=site_origin)

    @app.middleware("http")
    async def _no_cache_html(request: Request, call_next: Any) -> Any:
        resp = await call_next(request)
        if "text/html" in resp.headers.get("content-type", ""):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def ctrl() -> Controller:
        return app.state.controller  # type: ignore[no-any-return]

    def rec() -> Recorder:
        return app.state.recorder  # type: ignore[no-any-return]

    def printer() -> PrintController:
        return app.state.printer  # type: ignore[no-any-return]

    def vision_service() -> VisionService | None:
        return app.state.vision  # type: ignore[no-any-return]

    def overview_src() -> FrameSource | None:
        return app.state.overview_source  # type: ignore[no-any-return]

    def overview_streamer() -> OverviewStreamer | None:
        return app.state.overview_streamer  # type: ignore[no-any-return]

    def ev(label: str, data: dict[str, Any] | None = None) -> None:
        app.state.events.append(label, data)

    def job_payload() -> dict[str, Any] | None:
        job: JobInfo | None = app.state.job
        if job is None:
            return None
        snap = printer().snapshot()
        current = snap["layer"] if snap["state"] != "idle" and snap["phase"] == "printing" else 0
        return {**job.to_dict(), "current_layer": current}

    def print_settings_payload() -> dict[str, Any]:
        plan: PrintSettings = app.state.print_settings
        ex = exposure(
            layer_mm=plan.printing.layer_thickness_mm,
            area_mm2=plan.part_area_mm2,
            carbon_wt=plan.target_carbon_wt,
            powder_density_g_cm3=plan.powder_density_g_cm3,
            ink_carbon_wt=plan.ink_carbon_wt,
            ipa_dhvap_j_g=plan.ipa_dhvap_j_g,
            section_power_w=plan.heater_section_power_w,
            passes=plan.n_jet_passes,
        )
        pass_len = plan.printhead_end_mm - plan.printhead_home_mm
        return {
            "plan": plan.to_dict(),
            "validation": plan.validate(ctrl().limits),
            "n_steps": len(compile_print(plan)),
            "estimated_duration_s": estimate_duration_s(plan, print_min_wait_s),
            # The exact wait floor this operator runs with, so the UI's live estimate uses the SAME
            # constant as this payload (and as the real print) — deterministic, not a guessed 0.5.
            "min_wait_s": print_min_wait_s,
            "total_layers": plan.total_layers,
            "total_thickness_mm": plan.total_thickness_mm,
            "exposure": {
                "energy_j": ex.energy_j,
                "time_s": ex.time_s,
                "sweep_speed_mm_s": round(ex.sweep_speed_mm_s(pass_len), 2),
            },
            "bounds": HARD_BOUNDS,
            "limits": ctrl().limits.to_dict(),
        }

    def priming_payload() -> dict[str, Any]:
        s: PrimingSettings = app.state.priming
        steps = compile_priming_setup(s, ctrl().limits)
        return {
            "settings": s.to_dict(),
            "validation": s.validate(ctrl().limits),
            "n_steps": len(steps),
            "n_thick_precoats": s.n_thick_precoats,
            "limits": ctrl().limits.to_dict(),
        }

    def status_payload() -> dict[str, Any]:
        c, rc = ctrl(), rec()
        snap = c.snapshot()
        return {
            "device": snap.pop("device"),
            "controller": snap,
            "axis_motion": {str(k): v for k, v in app.state.axis_motion.items()},
            "print": printer().snapshot(),
            "job": job_payload(),
            "auto_log": app.state.auto_log,
            "events": app.state.events.recent(50),
            "recording": {
                "active": rc.active is not None,
                "run": rc.active.name if rc.active else None,
            },
            # "capture now" signal for the browser science-capture client: seq ticks on each capture
            # mark so the client grabs the assigned science camera + POSTs. None until first mark.
            "capture_request": getattr(app.state, "capture_request", None),
        }

    def guarded(fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    def check_axis(axis: int) -> None:
        if axis not in (1, 2, 3, 4):
            raise HTTPException(400, "axis must be 1..4")

    # ---- identity / status ------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "version": __version__,
            "api_version": API_VERSION,
            "backend": app.state.backend,
            "platform": platform.platform(),
            # Where jobs + runs are resolved from, and whether either fell back to an empty
            # install-local folder — the UI shows a loud banner when a fallback is in effect.
            "paths": getattr(app.state, "paths_info", None),
        }

    @app.get("/api/config/paths")
    def get_config_paths() -> dict[str, Any]:
        return getattr(app.state, "paths_info", None) or {}

    @app.put("/api/config/paths")
    def put_config_paths(body: dict[str, Any]) -> dict[str, Any]:
        """Persist the jobs/experiments roots to the install-independent config
        (~/.config/.../paths.json) so they survive reinstalls. Jobs re-point live; the experiments
        (runs) root needs an operator restart to take effect (reported in ``restart_required``)."""
        jr = body.get("jobs_root")
        er = body.get("experiments_root")
        for label, val in (("jobs_root", jr), ("experiments_root", er)):
            if val is not None and (not isinstance(val, str) or not val.strip()):
                raise HTTPException(400, f"{label} must be a non-empty string or null")
            if isinstance(val, str) and val.strip() and not Path(val).is_dir():
                raise HTTPException(400, f"{label} does not exist or is not a directory: {val}")
        cfg = PathsConfig(
            jobs_root=Path(jr) if isinstance(jr, str) and jr.strip() else None,
            experiments_root=Path(er) if isinstance(er, str) and er.strip() else None,
        )
        save_persistent_paths(cfg)
        restart_required = False
        if cfg.jobs_root is not None:  # re-point the live JobStore so jobs appear without a restart
            jobs.roots = [cfg.jobs_root]
            info = getattr(app.state, "paths_info", {}) or {}
            info.update({"jobs_root": str(cfg.jobs_root), "jobs_root_source": "config",
                         "jobs_root_is_fallback": False})
            app.state.paths_info = info
        if cfg.experiments_root is not None and cfg.experiments_root != app.state.experiments_root:
            restart_required = True
        info = getattr(app.state, "paths_info", {}) or {}
        return {**info, "restart_required": restart_required}

    @app.get("/api/config/timing")
    def get_config_timing() -> dict[str, Any]:
        return {
            "print_min_wait_s": printer().min_wait_s,
            "print_poll_interval_s": ctrl().print_poll_interval_s,
            "defaults": {"print_min_wait_s": 0.25, "print_poll_interval_s": 0.2},
        }

    @app.put("/api/config/timing")
    def put_config_timing(body: dict[str, Any]) -> dict[str, Any]:
        """Live-tune + persist the print-pacing knobs. ``print_min_wait_s`` is the per-step floor;
        ``print_poll_interval_s`` is the controller poll during a print. Applies IMMEDIATELY (no
        restart — read each tick) and writes the install-independent config so it survives
        restarts. Tighter = faster inter-move pacing; too tight risks advancing before a move
        settles, so values are range-checked."""

        def _num(label: str, v: Any, lo: float, hi: float) -> float | None:
            if v is None:
                return None
            if not isinstance(v, int | float) or not (lo <= float(v) <= hi):
                raise HTTPException(400, f"{label} must be a number in [{lo}, {hi}]")
            return float(v)

        mw = _num("print_min_wait_s", body.get("print_min_wait_s"), 0.0, 5.0)
        pp = _num("print_poll_interval_s", body.get("print_poll_interval_s"), 0.02, 1.0)
        if mw is not None:
            printer().min_wait_s = mw
        if pp is not None:
            ctrl().print_poll_interval_s = pp
        save_timing(TimingConfig(print_min_wait_s=printer().min_wait_s,
                                 print_poll_interval_s=ctrl().print_poll_interval_s))
        ev("print_timing_set", {"print_min_wait_s": printer().min_wait_s,
                                "print_poll_interval_s": ctrl().print_poll_interval_s})
        return get_config_timing()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return status_payload()

    @app.get("/api/discovery")
    def discovery() -> dict[str, Any]:
        cands: list[dict[str, Any]] = [
            {"backend": "simulated", "ip": None, "label": "simulator", "reachable": True}
        ]
        for label, cand_ip in (("ethernet", r.DEFAULT_IP_ETHERNET), ("usb", r.DEFAULT_IP_USB)):
            cands.append(
                {
                    "backend": "machinemotion",
                    "ip": cand_ip,
                    "label": label,
                    "reachable": _tcp_open(cand_ip, r.HTTP_PORT),
                }
            )
        return {"candidates": cands, "connected": {"backend": app.state.backend}}

    # ---- connection -------------------------------------------------------------------------
    @app.post("/api/connect")
    def connect(body: ConnectBody) -> dict[str, Any]:
        known = registered_transports()
        if body.backend not in known:
            raise HTTPException(400, f"unknown backend {body.backend!r}; known: {known}")
        try:
            _attach(app, body.backend, body.ip, body.heater_io)
        except Exception as exc:  # noqa: BLE001 - surface any connect failure as 503
            ev("connect_failed", {"backend": body.backend, "error": str(exc)})
            raise HTTPException(503, f"could not connect: {exc}") from exc
        ev("connected", {"backend": body.backend, "ip": body.ip})
        return status_payload()

    @app.post("/api/disconnect")
    def disconnect() -> dict[str, Any]:
        printer().abort("disconnect")
        ev("disconnected")
        rec().stop()
        ctrl().detach_device()
        app.state.backend = "none"
        return status_payload()

    @app.post("/api/arm")
    def arm() -> dict[str, Any]:
        guarded(ctrl().arm)
        ev("armed")
        return status_payload()

    @app.post("/api/disarm")
    def disarm() -> dict[str, Any]:
        printer().abort("disarm")
        ctrl().disarm()
        ev("disarmed")
        return status_payload()

    @app.post("/api/reference/current")
    def reference_current() -> dict[str, Any]:
        # Operator asserts the machine kept power and the reported positions are real: reference
        # every axis at its current position WITHOUT homing. The UI gates this behind a confirm.
        axes = guarded(ctrl().reference_current)
        ev("referenced_current", {"axes": sorted(axes)})
        return status_payload()

    @app.post("/api/operator/restart")
    def operator_restart() -> dict[str, Any]:
        """Re-launch the operator process in place (same command line). Refused while a print is
        RUNNING or PAUSED so an in-progress build is never dropped. The current process replaces
        itself a moment after this response is sent, so the browser reconnects after a beat."""
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            raise HTTPException(409, "a print is running; abort it before restarting the operator")
        ev("operator_restart")
        schedule_operator_restart()
        return {"ok": True, "restarting_in_s": OPERATOR_RESTART_DELAY_S}

    @app.post("/api/estop")
    def estop() -> Any:
        result = ctrl().estop()
        ev("estop", result)
        if not result["ok"]:
            # Never a false green: the operator must know which safe action did not reach the
            # controller (review C3).
            return JSONResponse(result, status_code=502)
        return result

    @app.post("/api/estop/release")
    def estop_release() -> dict[str, Any]:
        guarded(ctrl().estop_release)
        ev("estop_released")
        return status_payload()

    @app.post("/api/estop/reset-drives")
    def estop_reset_drives() -> dict[str, Any]:
        """Re-energize the drives in software after the e-stop is PHYSICALLY released (does not
        release the e-stop, which is physical-only)."""
        guarded(ctrl().reset_drives)
        ev("drives_reset")
        return status_payload()

    @app.post("/api/clear-fault")
    def clear_fault() -> dict[str, Any]:
        guarded(ctrl().clear_fault)
        ev("fault_cleared")
        return status_payload()

    # ---- motion -----------------------------------------------------------------------------
    @app.post("/api/motion/home")
    def home(body: HomeBody) -> dict[str, Any]:
        if body.axes:
            for a in body.axes:
                check_axis(a)
                guarded(ctrl().home, a)
        else:
            guarded(ctrl().home_all)
        ev("home", {"axes": body.axes or "all"})
        return status_payload()

    @app.post("/api/motion/move")
    def move(body: MoveBody) -> dict[str, Any]:
        fn = ctrl().move_absolute if body.mode == "abs" else ctrl().move_relative
        applied = guarded(fn, body.axis, body.mm)
        out = {"axis": body.axis, "mode": body.mode, "requested_mm": body.mm, "applied_mm": applied}
        ev("move", out)
        return out

    @app.post("/api/motion/stop")
    def stop(body: StopBody) -> dict[str, Any]:
        guarded(ctrl().stop_all)
        ev("stop", {"axes": body.axes or "all"})
        return status_payload()

    # ---- piston backlash calibration --------------------------------------------------------
    def backlash_routine() -> BacklashRoutine | None:
        return getattr(app.state, "backlash_routine", None)

    def piston_max_mm(axis: int) -> float:
        plan: PrintSettings = app.state.print_settings
        return plan.build_piston_max_mm if axis == 1 else plan.feed_piston_max_mm

    @app.post("/api/motion/backlash/session")
    def backlash_start(body: BacklashStartBody) -> dict[str, Any]:
        running = backlash_routine()
        if running is not None and running.snapshot()["state"] == "running":
            raise HTTPException(409, "a backlash calibration is already running")
        print_running = printer().state in (PrintState.RUNNING, PrintState.PAUSED)
        snap = ctrl().snapshot()
        problems = preflight_problems(snap, body.axis, print_running)
        if problems:
            raise HTTPException(409, "cannot calibrate backlash: " + "; ".join(problems))
        max_mm = piston_max_mm(body.axis)
        positions = body.positions or default_positions(max_mm)
        if body.verify:  # perturbed re-measure: probe the gaps BETWEEN the default depths
            midpoints = perturbed_positions(positions)
            positions = midpoints or positions
        try:
            validate_probe(max_mm, positions, body.d_mm)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        pos = ((snap.get("telemetry") or {}).get("positions") or {}).get(str(body.axis))
        if pos is None:
            raise HTTPException(409, f"no position reported for axis {body.axis} yet")
        start_mm = float(pos)
        def _persist_cal(result: BacklashResult) -> None:
            save_backlash(root / ".calibrations", dataclasses.asdict(result))

        routine = BacklashRoutine(
            ControllerMover(ctrl()), body.axis, positions, body.d_mm, body.reps,
            return_to_mm=start_mm, on_done=_persist_cal,
        )
        app.state.backlash_routine = routine
        routine.start_thread()
        ev("backlash_cal_start", {"axis": body.axis, "positions": positions, "d_mm": body.d_mm})
        return routine.snapshot()

    @app.get("/api/motion/backlash/session")
    def backlash_status() -> dict[str, Any]:
        routine = backlash_routine()
        if routine is None:
            return {"state": "idle", "axis": None, "progress": {"done": 0, "total": 0},
                    "current_ref_mm": None, "result": None, "error": None}
        return routine.snapshot()

    @app.post("/api/motion/backlash/cancel")
    def backlash_cancel() -> dict[str, Any]:
        routine = backlash_routine()
        if routine is None:
            raise HTTPException(409, "no backlash calibration to cancel")
        routine.cancel()
        ev("backlash_cal_cancel", {})
        return routine.snapshot()

    @app.post("/api/motion/backlash/apply")
    def backlash_apply(body: BacklashApplyBody) -> dict[str, Any]:
        routine = backlash_routine()
        snap = routine.snapshot() if routine is not None else None
        if snap is None or snap["state"] != "done" or snap["result"] is None:
            raise HTTPException(409, "no completed backlash measurement to apply")
        if snap["result"]["axis"] != body.axis:
            raise HTTPException(409, f"last measurement was for axis {snap['result']['axis']}")
        field = "build_backlash_mm" if body.axis == 1 else "feed_backlash_mm"
        recommended = float(snap["result"]["recommended_mm"])
        current = app.state.print_settings.to_dict()
        current[field] = recommended
        app.state.print_settings = PrintSettings.bounded(current, ctrl().limits)
        save_print_settings(root, app.state.print_settings)
        ev("backlash_cal_apply", {"axis": body.axis, field: recommended})
        return print_settings_payload()

    @app.get("/api/motion/backlash/history")
    def backlash_history() -> dict[str, Any]:
        """Saved backlash cals (newest first) — persisted under the experiments root, so past sweeps
        survive a restart and stay reviewable/exportable."""
        return {"calibrations": list_backlash(root / ".calibrations")}

    @app.get("/api/motion/backlash/history/{rec_id}")
    def backlash_history_record(rec_id: str) -> dict[str, Any]:
        record = load_backlash(root / ".calibrations", rec_id)
        if record is None:
            raise HTTPException(404, "no such calibration")
        return record

    # ---- seaborn figure exports (optional `plots` extra) -------------------------------------
    def _plot_response(data: bytes, fmt: str, stem: str) -> Response:
        return Response(
            content=data,
            media_type=plotting.FORMAT_CONTENT_TYPE[fmt],
            headers={"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'},
        )

    def _check_plot_fmt(fmt: str) -> None:
        """503 if the extra is absent, 400 if the requested format is unsupported."""
        if not plotting.plots_available():
            raise HTTPException(503, "plot export needs the 'plots' extra (uv sync --extra plots)")
        if fmt not in plotting.FORMAT_CONTENT_TYPE:
            raise HTTPException(400, f"unsupported format {fmt!r} (png | pdf)")

    @app.get("/api/plots/backlash.{fmt}")
    def plot_backlash(fmt: str) -> Response:
        """Backlash-per-depth strip plot for the live/last session — completed result if present,
        otherwise the in-progress partial positions. 404 when no measurements exist yet."""
        _check_plot_fmt(fmt)
        routine = backlash_routine()
        snap = routine.snapshot() if routine is not None else None
        result = (snap or {}).get("result")
        if result and result.get("positions"):
            positions = result["positions"]
            recommended = result.get("recommended_mm")
        elif snap and snap.get("partial_positions"):
            positions = snap["partial_positions"]
            recommended = None
        else:
            raise HTTPException(404, "no backlash measurements to plot yet")
        data = plotting.render_backlash(positions, recommended, fmt=fmt)
        return _plot_response(data, fmt, "backlash")

    @app.get("/api/plots/layer-accuracy/{run}.{fmt}")
    def plot_layer_accuracy(run: str, fmt: str) -> Response:
        """Cumulative commanded-vs-actual build height for one run's ``layer_accuracy.csv``."""
        _check_plot_fmt(fmt)
        run_dir = _run_dir_404(run)
        csv_path = run_dir / "layer_accuracy.csv"
        if not csv_path.exists():
            raise HTTPException(404, "run has no layer_accuracy.csv")
        with csv_path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        data = plotting.render_layer_accuracy(rows, fmt=fmt)
        return _plot_response(data, fmt, f"{run}_layer_accuracy")

    @app.post("/api/plots/validation.{fmt}")
    def plot_validation(fmt: str, body: PlotValidationBody) -> Response:
        """Histogram of world-space scale residuals (mm) vs the ±target acceptance line. The
        residuals come from the just-run validation (client-held), so this is a POST."""
        _check_plot_fmt(fmt)
        data = plotting.render_validation(body.residuals_mm, body.target_mm, fmt=fmt)
        return _plot_response(data, fmt, "scale_validation")

    @app.post("/api/plots/sweep.{fmt}")
    def plot_sweep(fmt: str, body: PlotSweepBody) -> Response:
        """Piston hysteresis (deviation vs commanded, up vs down) from posted piston-sweep rows."""
        _check_plot_fmt(fmt)
        data = plotting.render_sweep(body.rows, fmt=fmt)
        return _plot_response(data, fmt, "piston_sweep")

    @app.get("/api/axes/{axis}/motion")
    def axis_motion(axis: int) -> dict[str, Any]:
        check_axis(axis)
        return {
            **app.state.axis_motion[axis],
            "bounds": {
                "max_speed": HARD_BOUNDS["max_speed"][axis],
                "max_accel": HARD_BOUNDS["max_accel"][axis],
            },
            "limit_speed": ctrl().limits.max_speed[axis],
            "limit_accel": ctrl().limits.max_accel[axis],
        }

    @app.put("/api/axes/{axis}/motion")
    def set_axis_motion(axis: int, body: AxisMotionBody) -> dict[str, Any]:
        check_axis(axis)
        if body.max_speed is not None:
            applied = guarded(ctrl().set_max_speed, axis, body.max_speed)
            app.state.axis_motion[axis]["max_speed"] = applied
        if body.max_accel is not None:
            applied = guarded(ctrl().set_max_accel, axis, body.max_accel)
            app.state.axis_motion[axis]["max_accel"] = applied
        return axis_motion(axis)

    # ---- limits -----------------------------------------------------------------------------
    @app.get("/api/safety-limits")
    def get_limits() -> dict[str, Any]:
        return {**ctrl().limits.to_dict(), "bounds": HARD_BOUNDS}

    @app.put("/api/safety-limits")
    def put_limits(body: LimitsBody) -> dict[str, Any]:
        current = ctrl().limits.to_dict()
        for key, value in body.model_dump().items():
            if value is None:
                continue
            if isinstance(value, dict):
                current[key] = {**current[key], **{str(k): v for k, v in value.items()}}
            else:
                current[key] = value
        new_limits = SafetyLimits.bounded(**current)
        ctrl().set_limits(new_limits)
        save_limits(root, new_limits)
        return get_limits()

    # ---- heater -----------------------------------------------------------------------------
    @app.post("/api/heater/on")
    def heater_on() -> dict[str, Any]:
        guarded(ctrl().heater_on)
        ev("heater_on")
        return status_payload()

    @app.post("/api/heater/off")
    def heater_off() -> dict[str, Any]:
        ctrl().heater_off()
        ev("heater_off")
        return status_payload()

    # ---- print settings + print control ----------------------------------------------
    @app.get("/api/print-settings")
    def get_printer() -> dict[str, Any]:
        return print_settings_payload()

    @app.put("/api/print-settings")
    def put_print_settings(body: dict[str, Any]) -> dict[str, Any]:
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            raise HTTPException(409, "a print is running; abort it before editing")
        current = app.state.print_settings.to_dict()
        for key, value in body.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key] = {**current[key], **value}
            else:
                current[key] = value
        plan = PrintSettings.bounded(current, ctrl().limits)
        app.state.print_settings = plan
        save_print_settings(root, plan)
        return print_settings_payload()

    @app.post("/api/print/start")
    def print_start(body: PrintStartBody) -> dict[str, Any]:
        cal = backlash_routine()
        if cal is not None and cal.snapshot()["state"] == "running":
            raise HTTPException(409, "a backlash calibration is running; cancel it before printing")
        if getattr(app.state, "primed", None) is None:
            raise HTTPException(
                409,
                "prime the bed first — no primed bed state; run priming and capture positions",
            )
        plan: PrintSettings = app.state.print_settings
        # Open the auto-log run BEFORE starting so the print's own start event lands in it.
        opened = False
        if app.state.auto_log and rec().active is None:
            if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
                raise HTTPException(409, "a print is already running")
            if not ctrl().armed:
                raise HTTPException(409, "not armed — press ARM to take control of the printer")
            reasons = plan.validate(ctrl().limits)
            if reasons:
                raise HTTPException(409, "print settings invalid: " + "; ".join(reasons))
            name = body.name or "print"
            job: JobInfo | None = app.state.job
            rec().start(
                name,
                notes=body.notes,
                metadata={
                    "backend": app.state.backend,
                    "device": ctrl().snapshot()["device"],
                    "limits": ctrl().limits.to_dict(),
                    "print_settings": plan.to_dict(),
                    # Link the run to the selected job so Runs is a print-history page (its card can
                    # show the job preview). Absent for a manual print with no job selected.
                    **(
                        {"job_folder": job.dir.name, "job_name": job.name}
                        if job is not None
                        else {}
                    ),
                },
            )
            app.state.auto_run_open = True
            opened = True
        try:
            guarded(printer().start, plan, body.single_step)
        except HTTPException:
            if opened:
                app.state.auto_run_open = False
                rec().stop()
            raise
        return printer().snapshot()

    @app.post("/api/print/pause")
    def print_pause() -> dict[str, Any]:
        printer().pause()
        return printer().snapshot()

    @app.post("/api/print/resume")
    def print_resume() -> dict[str, Any]:
        guarded(printer().resume)
        return printer().snapshot()

    @app.post("/api/print/step")
    def print_step() -> dict[str, Any]:
        guarded(printer().step)
        return printer().snapshot()

    @app.post("/api/print/abort")
    def print_abort() -> dict[str, Any]:
        printer().abort()
        return printer().snapshot()

    @app.post("/api/print/single-step")
    def print_single_step(body: SingleStepBody) -> dict[str, Any]:
        guarded(printer().set_single_step, body.on)
        return printer().snapshot()

    @app.get("/api/print/steps")
    def print_steps() -> dict[str, Any]:
        return {
            "steps": [
                {
                    "index": s.index,
                    "phase": s.phase,
                    "layer": s.layer,
                    "kind": s.kind,
                    "axis": s.axis,
                    "value": s.value,
                    "label": s.label,
                }
                for s in printer().steps
            ]
        }

    @app.post("/api/print/seek")
    def print_seek(body: SeekBody) -> dict[str, Any]:
        guarded(printer().seek, body.index)
        return printer().snapshot()

    # ---- sliced jobs (Meteor RIP folders) --------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [j.to_dict() for j in jobs.scan()], "roots": [str(r) for r in jobs.roots]}

    @app.get("/api/meteor/status")
    def meteor_status() -> dict[str, Any]:
        """Pre-flight: does Meteor have a complete job loaded to fire for the selected build?

        Read-only (no motion, no firing). Firing itself is done by MetPrint from the hot folder;
        this only reports whether the selected job's RIP output is present + complete there, so the
        operator never sweeps the printhead over a bed that will receive no binder."""
        adapter = HotFolderMeteorAdapter(list(jobs.roots))
        return adapter.status(app.state.job).to_dict()

    @app.post("/api/jobs/select")
    def select_job(body: JobSelectBody) -> dict[str, Any]:
        path = Path(body.path)
        if not jobs.within_roots(path) or not (path / "job_info.json").is_file():
            raise HTTPException(
                400, "job must be a job_info.json folder under a configured jobs root"
            )
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            raise HTTPException(409, "a print is running; abort it before changing the job")
        try:
            job = load_job(path)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(400, f"could not read job: {exc}") from exc
        app.state.job = job
        current = app.state.print_settings.to_dict()
        current["printing"] = {**current["printing"], **job.print_settings_patch()["printing"]}
        plan = PrintSettings.bounded(current, ctrl().limits)
        app.state.print_settings = plan
        save_print_settings(root, plan)
        ev(
            "job_selected",
            {"job": job.name, "layers": job.layer_count, "layer_mm": job.layer_height_mm},
        )
        return {"job": job_payload(), "print_settings": print_settings_payload()}

    @app.post("/api/jobs/clear")
    def clear_job() -> dict[str, Any]:
        app.state.job = None
        return {"job": None}

    @app.post("/api/jobs/archive")
    def archive_job_route(body: dict[str, Any]) -> dict[str, Any]:
        """Move a completed job's folder into the hot folder's ``_archive/`` from the Jobs page.
        Refuses the job currently printing. The job stays listed (flagged ``archived``), out of the
        active print path."""
        folder = body.get("folder")
        if not isinstance(folder, str) or not folder:
            raise HTTPException(400, "folder required")
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            cur = app.state.job
            if cur is not None and cur.dir.name == folder:
                raise HTTPException(409, "cannot archive the job that is currently printing")
        try:
            dest = jobs.archive_job(folder)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if app.state.job is not None and app.state.job.dir.name == folder:
            app.state.job = None  # the selected job just moved; clear the stale selection
        return {"folder": folder, "archived_to": str(dest)}

    @app.get("/api/jobs/current/layers/{layer}.png")
    def job_layer_png(layer: int) -> Response:
        job: JobInfo | None = app.state.job
        if job is None:
            raise HTTPException(404, "no job selected")
        try:
            data = layer_png(job, layer)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "no-cache", "ETag": f'"{job.dir.name}-{layer}"'},
        )

    @app.get("/api/jobs/by-folder/{folder}/layers/{layer}.png")
    def job_layer_by_folder(folder: str, layer: int) -> Response:
        """Serve a layer PNG from a SPECIFIC job folder (incl. _archive), regardless of the
        selected job — the Runs/Analysis stills-vs-CAD compare needs any run's job layer.
        `folder` is matched against scanned job folders only (no path traversal /
        arbitrary reads)."""
        job = next((j for j in jobs.scan() if j.dir.name == folder), None)
        if job is None:
            raise HTTPException(404, f"no job folder {folder!r}")
        try:
            data = layer_png(job, layer)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "no-cache", "ETag": f'"{folder}-{layer}"'},
        )

    @app.get("/api/jobs/by-folder/{folder}/preview.png")
    def job_preview_by_folder(folder: str) -> Response:
        """Serve the slicer's splash/preview image for a job folder as a PNG. 404 when the job has
        no preview or the file can't be decoded."""
        job = next((j for j in jobs.scan() if j.dir.name == folder), None)
        if job is None:
            raise HTTPException(404, f"no job folder {folder!r}")
        try:
            data = preview_png(job)
        except (IndexError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "no-cache", "ETag": f'"{folder}-preview"'},
        )

    @app.post("/api/macro/{name}")
    def run_macro(name: str) -> dict[str, Any]:
        if name not in MACROS:
            raise HTTPException(400, f"unknown macro {name!r}; known: {sorted(MACROS)}")
        guarded(printer().start_macro, name, macro_steps(name, ctrl().limits))
        return printer().snapshot()

    @app.get("/api/macros")
    def list_macros() -> dict[str, Any]:
        return {"macros": MACROS}

    # ---- priming (powder-prep) routine -----------------------------------------------------
    @app.get("/api/priming")
    def get_priming() -> dict[str, Any]:
        return priming_payload()

    @app.put("/api/priming")
    def put_priming(body: dict[str, Any]) -> dict[str, Any]:
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            raise HTTPException(409, "a routine is running; abort it before editing")
        current = app.state.priming.to_dict()
        current.update(body)
        settings = PrimingSettings.bounded(current, ctrl().limits)
        app.state.priming = settings
        save_priming(root, settings)
        return priming_payload()

    @app.post("/api/priming/run")
    def run_priming() -> dict[str, Any]:
        settings: PrimingSettings = app.state.priming
        reasons = settings.validate(ctrl().limits)
        if reasons:
            raise HTTPException(409, "priming settings invalid: " + "; ".join(reasons))
        guarded(printer().start_macro, "priming", compile_priming_setup(settings, ctrl().limits))
        return printer().snapshot()

    # ---- primed bed state (piston snapshot a print starts from) ----------------------------
    @app.get("/api/primed")
    def get_primed() -> dict[str, Any]:
        primed: PrimedState | None = app.state.primed
        return {"primed": primed.to_dict() if primed is not None else None}

    @app.post("/api/primed/capture")
    def capture_primed() -> dict[str, Any]:
        tel = ctrl().snapshot()["telemetry"]
        positions = tel["positions"] if tel else None
        if not positions or "1" not in positions or "2" not in positions:
            raise HTTPException(
                409, "connect and read positions before capturing the primed bed state"
            )
        state = PrimedState(
            part_mm=positions["1"], feed_mm=positions["2"], captured_at=time.time()
        )
        save_primed(root, state)
        app.state.primed = state
        ev("primed_captured", state.to_dict())
        return {"primed": state.to_dict()}

    @app.get("/api/events")
    def get_events() -> dict[str, Any]:
        return {"events": app.state.events.recent(200)}

    @app.get("/api/auto-log")
    def get_auto_log() -> dict[str, Any]:
        return {"enabled": app.state.auto_log}

    @app.put("/api/auto-log")
    def put_auto_log(body: AutoLogBody) -> dict[str, Any]:
        app.state.auto_log = body.enabled
        return {"enabled": app.state.auto_log}

    # ---- recording --------------------------------------------------------------------------
    @app.post("/api/recording/start")
    def recording_start(body: RecordingStartBody) -> dict[str, Any]:
        if rec().active is not None:
            raise HTTPException(409, "already recording")
        run = rec().start(
            body.name,
            notes=body.notes,
            metadata={
                "backend": app.state.backend,
                "device": ctrl().snapshot()["device"],
                "limits": ctrl().limits.to_dict(),
            },
        )
        return {"run": run.name}

    @app.post("/api/recording/stop")
    def recording_stop() -> dict[str, Any]:
        run = rec().stop()
        return {"run": run.name if run else None, "stopped": run is not None}

    @app.get("/api/recording/status")
    def recording_status() -> dict[str, Any]:
        recording: dict[str, Any] = status_payload()["recording"]
        return recording

    def _scan_drives() -> list[Any]:
        """Mounted offload drives to include when enumerating/resolving runs. Disabled by
        ``VPI_DISABLE_DRIVE_SCAN`` so tests stay hermetic (never see the dev's real drives)."""
        if os.environ.get("VPI_DISABLE_DRIVE_SCAN"):
            return []
        return list_drives()

    def _run_dir_opt(run: str) -> Path | None:
        """Resolve a run's directory across the local root AND every mounted drive's vpi-runs/
        folder (local-first), or None when no location has it. Raises HTTP 400 on a bad/traversing
        name. Lets an offloaded run stay reachable by every run route."""
        try:
            found = resolve_run_across(run_roots(root, _scan_drives()), run)
        except ValueError as exc:
            raise HTTPException(400, "bad run") from exc
        return found[0] if found is not None else None

    def _run_dir(run: str) -> Path:
        """Resolve across roots; 400 "bad run" when the run exists nowhere. Preserves the contract
        of the run-file / archive / timelapse / delete routes (a bad/missing run is a 400)."""
        d = _run_dir_opt(run)
        if d is None:
            raise HTTPException(400, "bad run")
        return d

    def _run_dir_404(run: str) -> Path:
        """Resolve across roots; 404 "unknown run" when the run exists nowhere. Preserves the
        contract of the plots / meta / analysis / vision-file routes (missing run is a 404)."""
        d = _run_dir_opt(run)
        if d is None:
            raise HTTPException(404, "unknown run")
        return d

    @app.get("/api/recordings")
    def recordings() -> dict[str, Any]:
        # Union runs across the local experiments root AND every mounted drive's vpi-runs/ folder,
        # so an offloaded run stays visible in the browser (FLIR-parity). Deduped by name; each row
        # carries `locations` (e.g. ["local"], ["FLIR SSD"], or both).
        active = rec().active
        labeled = [
            (lib, list_runs_in(r, active=active)) for lib, r in run_roots(root, _scan_drives())
        ]
        return {"runs": merge_runs(labeled)}

    @app.get("/api/recordings/{run}/archive.zip")
    def recording_archive(run: str) -> Response:
        """Stream a zip of the whole run directory (telemetry, motion_profiles, events, manifest,
        layers, metadata, and any nested vision/ stills+sidecars). Same run-name validation as the
        run-file route: the resolved directory must sit directly under ``root`` (no traversal)."""
        run_dir = _run_dir(run)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(run_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(path.relative_to(run_dir.parent).as_posix()))
        buffer.seek(0)
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run}.zip"'},
        )

    @app.get("/api/recordings/{run}/timelapse.gif")
    def recording_timelapse(
        run: str, source: str = "science", stage: str | None = None, fps: float = 6.0
    ) -> Response:
        """Animated-GIF timelapse of a run (#4). ``source=science`` (default) uses the per-layer
        science stills for one ``stage`` (defaults to the fullest); ``source=overview`` uses the
        time-ordered wide-view overview frames. 404 when the run has no frames for that source. GIF
        so it plays inline in an <img> with no codec dependency."""
        run_dir = _run_dir(run)
        from vention_printer_interface.vision.timelapse import (
            best_stage,
            build_overview_timelapse_gif,
            build_timelapse_gif,
        )
        fps = min(max(fps, 0.5), 30.0)
        if source == "overview":
            data = build_overview_timelapse_gif(run_dir, fps)
            label = "overview"
            empty = "no overview frames recorded for this run"
        elif source == "science":
            chosen = stage or best_stage(run_dir)
            if chosen is None:
                raise HTTPException(404, "no science-cam stills recorded for this run")
            data = build_timelapse_gif(run_dir, chosen, fps)
            label = chosen
            empty = f"no {chosen} stills for this run"
        else:
            raise HTTPException(400, f"bad source {source!r} (science | overview)")
        if data is None:
            raise HTTPException(404, empty)
        return Response(
            content=data,
            media_type="image/gif",
            headers={"Content-Disposition": f'inline; filename="{run}_{label}_timelapse.gif"'},
        )

    @app.delete("/api/recordings/{run}")
    def recording_delete(run: str) -> dict[str, Any]:
        """Delete a run directory (telemetry, stills, everything). Refuses the run currently being
        recorded (409). Same run-name validation as the archive/file routes (no traversal)."""
        run_dir = _run_dir(run)
        active = rec().current_run_dir
        if active is not None and active.resolve() == run_dir:
            raise HTTPException(409, "cannot delete the run that is currently recording")
        shutil.rmtree(run_dir)
        return {"run": run, "deleted": True}

    @app.put("/api/recordings/{run}/meta")
    def recording_meta(run: str, body: RecordingMetaBody) -> dict[str, str]:
        """Edit a run's human-readable name/notes in its metadata.json (all other keys preserved).

        Writes the same ``experiment.name`` / ``experiment.notes`` keys the recorder writes at
        start and the recordings list reads back, so an edit round-trips through the list.
        """
        run_dir = _run_dir_404(run)
        meta_path = run_dir / "metadata.json"
        try:
            loaded = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            loaded = {}
        meta: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        raw_experiment = meta.get("experiment")
        experiment: dict[str, Any] = raw_experiment if isinstance(raw_experiment, dict) else {}
        meta["experiment"] = experiment
        if body.name is not None:
            experiment["name"] = body.name
        if body.notes is not None:
            experiment["notes"] = body.notes
        meta_path.write_text(json.dumps(meta, indent=2, default=str))
        return {"name": experiment.get("name", ""), "notes": experiment.get("notes", "")}

    @app.post("/api/recordings/{run}/reveal")
    def recording_reveal(run: str) -> dict[str, Any]:
        """Reveal a run's metadata on disk in the OS file browser (operator is local — localhost).

        Returns the absolute path either way so the UI can show/copy it even where opening a file
        browser isn't possible (headless/remote). The ``open`` call is best-effort glue: a failure
        (or a non-desktop host) still returns the path with ``revealed: false`` and a reason.
        """
        try:
            target = _run_reveal_target(root, run)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        revealed, note = False, ""
        # macOS: `open -R` selects the file in Finder; Linux/Windows: open the containing folder.
        opener = (
            ["open", "-R", str(target)] if sys.platform == "darwin"
            else ["xdg-open", str(target.parent)] if sys.platform.startswith("linux")
            else ["explorer", str(target.parent)] if sys.platform.startswith("win") else None
        )
        if opener is None:
            note = f"no file browser opener for platform {sys.platform!r}"
        else:
            try:
                subprocess.run(opener, check=True, capture_output=True, timeout=5.0)
                revealed = True
            except Exception as exc:  # noqa: BLE001 - reveal is best-effort; report, never 500
                note = f"could not open a file browser: {exc}"
                log.warning("reveal failed for %s: %s", run, exc)
        return {"run": run, "path": str(target), "revealed": revealed, "note": note}

    @app.get("/api/recordings/{run}/{name}")
    def recording_file(run: str, name: str) -> FileResponse:
        if name not in RUN_FILES:
            raise HTTPException(404, "unknown file")
        run_dir = _run_dir(run)  # local or a mounted drive
        target = (run_dir / name).resolve()
        if target.parent != run_dir.resolve() or not target.exists():
            raise HTTPException(400, "bad run")
        return FileResponse(target)

    # ---- data offload (verified copy of runs to a picked external drive) ----------------------
    def _offload_job() -> OffloadJob | None:
        return getattr(app.state, "offload_job", None)

    def _source_run_names() -> list[str]:
        try:
            return sorted((p.name for p in root.iterdir() if p.is_dir()), reverse=True)
        except OSError:
            return []

    @app.get("/api/offload/drives")
    def offload_drives() -> dict[str, Any]:
        return {"drives": [drive_dict(d) for d in list_drives()]}

    @app.get("/api/offload/plan")
    def offload_plan_endpoint(dest: str = Query(...)) -> dict[str, Any]:
        dpath = Path(dest)
        if not dpath.is_dir():
            raise HTTPException(400, "destination is not a mounted directory")
        job = _offload_job()
        return {"plan": offload_plan(_source_run_names(), dpath),
                "job": job.snapshot() if job is not None else {"state": "idle"}}

    @app.get("/api/offload/job")
    def offload_job_status() -> dict[str, Any]:
        job = _offload_job()
        return job.snapshot() if job is not None else {"state": "idle"}

    @app.post("/api/offload/start")
    def offload_start(body: OffloadStartBody) -> dict[str, Any]:
        running = _offload_job()
        if running is not None and running.snapshot()["state"] == "running":
            raise HTTPException(409, "an offload is already running")
        dpath = Path(body.dest)
        if not dpath.is_dir():
            raise HTTPException(400, "destination is not a mounted directory")
        names = _source_run_names()
        if body.runs is not None:
            known = set(names)
            chosen = [r for r in body.runs if r in known]
        elif body.move:  # move all local runs (a move deletes source, so 'present' can't skip)
            chosen = names
        else:  # copy: every run not already on the drive
            present = {p["run"] for p in offload_plan(names, dpath) if p["at_dest"]}
            chosen = [r for r in names if r not in present]
        if not chosen:
            raise HTTPException(400, "no runs to copy (all already present, or none matched)")
        job = OffloadJob(root, dpath, chosen, mode="move" if body.move else "copy")
        app.state.offload_job = job
        job.start_thread()
        ev("offload_start", {"dest": str(dpath), "runs": len(chosen),
                             "mode": "move" if body.move else "copy"})
        return job.snapshot()

    @app.post("/api/offload/cancel")
    def offload_cancel() -> dict[str, Any]:
        job = _offload_job()
        if job is None:
            raise HTTPException(409, "no offload to cancel")
        job.cancel()
        return job.snapshot()

    # ---- vision (overview + science cameras) -------------------------------------------------
    @app.get("/api/vision/status")
    def vision_status() -> dict[str, Any]:
        vision = vision_service()
        active_roles: list[str] = []
        if overview_src() is not None:
            active_roles.append(camera_config.overview.role)
        if vision is not None:
            active_roles.append(camera_config.science.role)
        calib: Calibration | None = vision.calibration if vision is not None else None
        unresolved: list[str] = list(getattr(app.state, "vision_unresolved_roles", []))
        return {
            "cameras": active_roles,
            "calibration": calib.version if calib is not None else None,
            "queue": {"drops": vision.drops if vision is not None else 0},
            "active": bool(active_roles),
            "roles_resolved": not unresolved,
            "unresolved": unresolved,
        }

    # ---- camera-center sweep (browser-driven: the client steps the recoater + captures per pose,
    #      the server scores each frame's bore offset and picks the centering pose) ----------------
    def _center_sweep() -> dict[str, Any] | None:
        return getattr(app.state, "center_sweep", None)

    def _sweep_poses(start: float, span: float, step: float, end_mm: float) -> list[float]:
        n = int(round(span / step))
        poses = [round(start + i * step, 3) for i in range(-n, n + 1)]
        return [p for p in poses if 0.0 <= p <= end_mm]

    @app.post("/api/vision/center-sweep/session")
    def center_sweep_start(body: CenterSweepStartBody) -> dict[str, Any]:
        plan: PrintSettings = app.state.print_settings
        start = body.start_mm
        if start is None:
            start = plan.capture_recoater_mm if plan.capture_recoater_mm > 0 else 0.0
        poses = _sweep_poses(start, body.span_mm, body.step_mm, plan.recoater_end_mm)
        if not poses:
            raise HTTPException(400, "sweep range is empty (check start/span vs recoater travel)")
        app.state.center_sweep = {"poses": poses, "start_mm": float(start), "samples": []}
        ev("center_sweep_start", {"poses": poses, "start_mm": start})
        return {"active": True, "poses": poses, "start_mm": float(start), "samples": []}

    @app.get("/api/vision/center-sweep/session")
    def center_sweep_status() -> dict[str, Any]:
        sess = _center_sweep()
        if sess is None:
            return {"active": False, "poses": [], "start_mm": None, "samples": [], "done": False}
        return {"active": True, **sess, "done": len(sess["samples"]) >= len(sess["poses"])}

    @app.post("/api/vision/center-sweep/sample")
    async def center_sweep_sample(
        request: Request, recoater_mm: float = Query(...)
    ) -> dict[str, Any]:
        """Score one browser-captured overhead frame at ``recoater_mm``: detect the bore, record
        its radial offset from the frame center. ``found=false`` when no bore is detected."""
        sess = _center_sweep()
        if sess is None:
            raise HTTPException(409, "no center sweep in progress; start a session first")
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty image body")
        import cv2

        arr = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode uploaded image")
        circle = detect_piston_circle(arr)
        offset = center_offset_px(arr)
        h, w = arr.shape[:2]
        sess["samples"].append({"recoater_mm": float(recoater_mm),
                                "offset_px": None if offset is None else float(offset)})
        return {
            "recoater_mm": float(recoater_mm),
            "found": circle is not None,
            "offset_px": None if offset is None else float(offset),
            "cx": None if circle is None else circle[0],
            "cy": None if circle is None else circle[1],
            "r": None if circle is None else circle[2],
            "image_size": [w, h],
        }

    @app.post("/api/vision/center-sweep/best")
    def center_sweep_best() -> dict[str, Any]:
        sess = _center_sweep()
        if sess is None:
            raise HTTPException(409, "no center sweep in progress")
        pts = [(s["recoater_mm"], s["offset_px"]) for s in sess["samples"]
               if s["offset_px"] is not None]
        if not pts:
            raise HTTPException(409, "no bore detected in any frame; re-run the sweep")
        result = best_center_pose(pts, sess["start_mm"])
        return {"pose_mm": result.pose_mm, "offset_px": result.offset_px,
                "improved": result.improved}

    @app.post("/api/vision/center-sweep/apply")
    def center_sweep_apply(body: CenterSweepApplyBody) -> dict[str, Any]:
        current = app.state.print_settings.to_dict()
        current["capture_recoater_mm"] = body.recoater_mm
        app.state.print_settings = PrintSettings.bounded(current, ctrl().limits)
        save_print_settings(root, app.state.print_settings)
        ev("center_sweep_apply", {"capture_recoater_mm": body.recoater_mm})
        return print_settings_payload()

    @app.post("/api/vision/center-sweep/cancel")
    def center_sweep_cancel() -> dict[str, Any]:
        app.state.center_sweep = None
        return {"active": False}

    @app.post("/api/vision/deactivate")
    def vision_deactivate() -> dict[str, Any]:
        """Force-release every camera source right now (turn all camera lights off).

        Stops the science capture worker and the overview streamer and closes their devices,
        then tears the services down so GET /api/vision/status reports inactive. Guarded end to
        end so a stuck worker or a close failure can never 500 this safety-release path."""
        vision = vision_service()
        if vision is not None:
            try:
                vision.stop()  # joins worker + closes the science device if open
            except Exception as exc:  # noqa: BLE001 - a stuck worker must not block release
                log.warning("vision service stop on deactivate failed (%s)", exc)
            app.state.vision = None

        streamer = overview_streamer()
        if streamer is not None:
            try:
                streamer.stop()  # stops grabber + closes the overview device if open
            except Exception as exc:  # noqa: BLE001 - guarded release
                log.warning("overview streamer stop on deactivate failed (%s)", exc)
            app.state.overview_streamer = None

        src = overview_src()
        if src is not None:
            try:
                src.close()  # belt-and-suspenders: explicit close even if streamer setup failed
            except Exception as exc:  # noqa: BLE001 - guarded release
                log.warning("overview source close on deactivate failed (%s)", exc)
            app.state.overview_source = None

        ev("vision_deactivated")
        return vision_status()

    @app.get("/api/vision/cameras")
    def vision_cameras() -> dict[str, Any]:
        return {
            "overview": dataclasses.asdict(camera_config.overview),
            "science": dataclasses.asdict(camera_config.science),
        }

    @app.get("/api/vision/settings")
    def vision_get_settings() -> dict[str, Any]:
        """Per-role camera settings (resolution/fps/format/exposure) from the current
        CameraConfig -- env/defaults with any persisted overrides already merged in."""
        return {
            "overview": _spec_to_settings(camera_config.overview),
            "science": _spec_to_settings(camera_config.science),
        }

    @app.put("/api/vision/settings")
    def vision_put_settings(body: CameraSettingsBody) -> dict[str, Any]:
        """Persist per-role camera-setting overrides (field-level merge) alongside the role map,
        then rebuild the CameraConfig so the change takes effect the next time a camera opens."""
        nonlocal camera_config
        overrides = load_camera_settings(vision_settings_path)
        for role, role_settings in (("overview", body.overview), ("science", body.science)):
            if role_settings is None:
                continue
            overrides.setdefault(role, {}).update(_settings_to_override(role_settings))
        save_camera_settings(vision_settings_path, overrides)
        camera_config = build_camera_config()
        return {
            "overview": _spec_to_settings(camera_config.overview),
            "science": _spec_to_settings(camera_config.science),
        }

    @app.get("/api/vision/devices")
    def vision_devices() -> dict[str, Any]:
        """Detected cameras (A7 auto-connect/quick-start) plus an overall camera-permission
        signal. Each device carries its currently RESOLVED role (via `resolve_roles` against the
        persisted map — `None` when not yet assigned), a best-effort live preview URL when that
        role's dedicated source is already open, and `has_frame` (whether `enumerate_devices`'s
        probe actually got a frame off it — never touches the science source directly here; I1:
        only the overview live-view stream is safe to share across concurrent readers).

        `camera_access` aggregates `has_frame` across every enumerated device (see
        `camera_access_state`): `"no_devices"` when nothing enumerated, `"denied"` when device(s)
        enumerated but none yielded a frame (the macOS Privacy & Security "not authorized"
        signature), `"ok"` otherwise -- this is what the quick-start UI shows in place of an
        empty/silent device list when the OS is simply blocking camera access.
        """
        try:
            enumerated = enumerator()
        except Exception as exc:  # noqa: BLE001 - enumeration must never fail the request
            log.warning("device enumeration failed (%s)", exc)
            enumerated = []
        mapping = load_role_map(vision_roles_path)
        resolved = resolve_roles(enumerated, mapping, camera_config)
        role_by_index = {spec.index: role for role, spec in resolved.items()}
        overview_active = overview_streamer() is not None
        devices: list[dict[str, Any]] = []
        for device in enumerated:
            # Only real external USB cameras are assignable — never show the built-in FaceTime or an
            # iPhone Continuity camera in the device list (they can't hold a role either).
            if not device.get("assignable", True):
                continue
            role = role_by_index.get(int(device["index"]))
            preview_url = (
                "/api/vision/overview/stream" if role == "overview" and overview_active else None
            )
            devices.append(
                {
                    "index": device.get("index"),
                    "stable_id": device.get("stable_id"),
                    "name": device.get("name"),
                    "role": role,
                    "preview_url": preview_url,
                    "has_frame": device.get("has_frame"),
                }
            )
        return {"devices": devices, "camera_access": camera_access_state(enumerated)}

    @app.get("/api/vision/roles")
    def vision_get_roles() -> dict[str, str]:
        return load_role_map(vision_roles_path)

    @app.put("/api/vision/roles")
    def vision_put_roles(body: RoleMapBody) -> dict[str, Any]:
        """Persist the operator-confirmed stable_id->role map, then (re)open the mapped
        overview+science sources so the change takes effect immediately -- guarded end to end
        so a role pointed at a device that isn't currently plugged in can never crash the
        request or leave the app in a half-open state."""
        bad_roles = sorted(set(body.mapping.values()) - _VALID_ROLES)
        if bad_roles:
            raise HTTPException(
                400, f"invalid role value(s): {bad_roles!r} (must be in {sorted(_VALID_ROLES)!r})"
            )
        save_role_map(vision_roles_path, body.mapping)
        resolved = app.state.vision_refresh_role_resolution()

        vision = vision_service()
        if vision is not None:
            try:
                vision.stop()
            except Exception as exc:  # noqa: BLE001 - a stuck worker must not block the reopen
                log.warning("vision service stop before reopen failed (%s)", exc)
        app.state.vision_open_science(resolved.get("science"))

        streamer = overview_streamer()
        if streamer is not None:
            try:
                streamer.stop()
            except Exception as exc:  # noqa: BLE001 - guarded reopen
                log.warning("overview streamer stop before reopen failed (%s)", exc)
        src = overview_src()
        if src is not None:
            try:
                src.close()
            except Exception as exc:  # noqa: BLE001 - guarded reopen
                log.warning("overview source close before reopen failed (%s)", exc)
        app.state.vision_open_overview(resolved.get("overview"))

        unresolved: list[str] = list(app.state.vision_unresolved_roles)
        return {"mapping": body.mapping, "roles_resolved": not unresolved, "unresolved": unresolved}

    @app.get("/api/vision/avf-cameras")
    def vision_avf_cameras() -> dict[str, Any]:
        """macOS cameras with their STABLE AVFoundation unique ids (Phase-2 unattended capture).
        The operator picks the science camera's unique id from this list; empty on non-macOS."""
        cams = list_avf_cameras()
        return {
            "cameras": [
                {"index": c.index, "name": c.name, "unique_id": c.unique_id} for c in cams
            ],
            "science_uid": load_science_uid(),
            "ignored_uids": load_ignored_cameras(),
        }

    @app.get("/api/vision/ignored-cameras")
    def vision_get_ignored_cameras() -> dict[str, list[str]]:
        return {"unique_ids": load_ignored_cameras()}

    @app.put("/api/vision/ignored-cameras")
    def vision_put_ignored_cameras(body: dict[str, Any]) -> dict[str, list[str]]:
        """Set the perpetually-ignored camera list (AVFoundation unique ids). Idempotent: replaces
        the whole list, so the UI toggles by sending the new set. De-duplicated, strings only."""
        raw = body.get("unique_ids")
        if not isinstance(raw, list) or not all(isinstance(u, str) for u in raw):
            raise HTTPException(400, "unique_ids must be a list of strings")
        uids = list(dict.fromkeys(u for u in raw if u))  # de-dup, drop empties, keep order
        ignored_cameras_path.write_text(json.dumps({"unique_ids": uids}))
        return {"unique_ids": uids}

    @app.get("/api/vision/science-uid")
    def vision_get_science_uid() -> dict[str, str | None]:
        return {"unique_id": load_science_uid()}

    @app.put("/api/vision/science-uid")
    def vision_put_science_uid(body: dict[str, Any]) -> dict[str, str | None]:
        """Set (or clear, with null) the science camera's AVFoundation unique id and reopen the
        science source so unattended server captures grab the RIGHT camera by that stable id."""
        uid = body.get("unique_id")
        if uid is not None and (not isinstance(uid, str) or not uid.strip()):
            raise HTTPException(400, "unique_id must be a non-empty string or null")
        science_uid_path.write_text(json.dumps({"unique_id": uid}))
        vision = vision_service()
        if vision is not None:
            try:
                vision.stop()
            except Exception as exc:  # noqa: BLE001 - a stuck worker must not block the reopen
                log.warning("vision stop before science-uid reopen failed (%s)", exc)
        resolved = app.state.vision_refresh_role_resolution()
        app.state.vision_open_science(resolved.get("science"))
        return {"unique_id": load_science_uid()}

    @app.get("/api/vision/board")
    def vision_board(
        fmt: str = Query("svg", alias="format"),
        kind: str = "charuco",
        preset: str | None = None,
        squares_x: int | None = None,
        squares_y: int | None = None,
        square_mm: float | None = None,
        marker_mm: float | None = None,
        dict_name: str = Query("DICT_4X4_50", alias="dict"),
        engrave_black: bool = True,
        label: bool = True,
        cut_outline: bool = True,
    ) -> Response:
        """Generate a TRUE-VECTOR ChArUco calibration board (SVG or DXF) for laser engraving.

        Either a named ``preset`` (with optional explicit field overrides) or an explicit
        ``squares_x``/``squares_y``/``square_mm``/``marker_mm`` set must be supplied. Returns
        the file with the right content-type + an attachment download name; 400 on bad params.
        """
        if kind != "charuco":
            raise HTTPException(400, "only kind=charuco is supported")
        if fmt not in ("svg", "dxf"):
            raise HTTPException(400, "format must be 'svg' or 'dxf'")

        # I-1: validate BEFORE touching cv2/board_gen -- an unbounded squares_x/squares_y or a
        # bogus dict name must never reach board generation (CPU-burn / crash risk).
        import cv2
        import cv2.aruco as aruco

        dict_allowlist = {name for name in dir(aruco) if name.startswith("DICT_")}
        if dict_name not in dict_allowlist:
            raise HTTPException(400, f"unknown aruco dictionary: {dict_name!r}")

        try:
            if preset is not None:
                overrides: dict[str, Any] = {}
                if squares_x is not None:
                    overrides["squares_x"] = squares_x
                if squares_y is not None:
                    overrides["squares_y"] = squares_y
                if square_mm is not None:
                    overrides["square_length_mm"] = square_mm
                if marker_mm is not None:
                    overrides["marker_length_mm"] = marker_mm
                if dict_name != "DICT_4X4_50":
                    overrides["aruco_dict"] = dict_name
                spec = resolve_preset(preset, **overrides)
                filename_base = preset
            else:
                if squares_x is None or squares_y is None or square_mm is None or marker_mm is None:
                    raise HTTPException(
                        400,
                        "provide a preset or all of squares_x, squares_y, square_mm, marker_mm",
                    )
                spec = BoardSpec(
                    kind="charuco",
                    squares_x=squares_x,
                    squares_y=squares_y,
                    square_length_mm=square_mm,
                    marker_length_mm=marker_mm,
                    aruco_dict=dict_name,
                )
                filename_base = f"charuco_{squares_x}x{squares_y}"
        except KeyError as exc:
            raise HTTPException(400, f"unknown preset: {preset!r}") from exc

        # Range/consistency validation on the FINAL resolved spec (covers both the explicit
        # path and a preset with overrides) -- still before any cv2 board-generation compute.
        if not (1 <= spec.squares_x <= 40):
            raise HTTPException(400, "squares_x must be between 1 and 40")
        if not (1 <= spec.squares_y <= 40):
            raise HTTPException(400, "squares_y must be between 1 and 40")
        if not (0 < spec.marker_length_mm < spec.square_length_mm):
            raise HTTPException(400, "marker_mm must be > 0 and less than square_mm")

        polarity = "black" if engrave_black else "white"
        try:
            if fmt == "svg":
                svg = generate_charuco_svg(
                    spec, engrave_black=engrave_black, label=label, cut_outline=cut_outline
                )
                return Response(
                    content=svg,
                    media_type="image/svg+xml",
                    headers={
                        "Content-Disposition": (
                            f'attachment; filename="{filename_base}_{polarity}.svg"'
                        )
                    },
                )
            dxf = generate_charuco_dxf(
                spec, engrave_black=engrave_black, label=label, cut_outline=cut_outline
            )
        except (ValueError, AttributeError, TypeError, cv2.error) as exc:
            raise HTTPException(400, f"invalid board spec: {exc}") from exc
        return Response(
            content=dxf,
            media_type="application/dxf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}_{polarity}.dxf"'
            },
        )

    @app.post("/api/vision/calibrate")
    def vision_calibrate(body: VisionCalibrateBody) -> dict[str, Any]:
        # Bed correspondence points (raw image px <-> world mm on the bed plane).
        bed_image_pts = np.asarray(body.image_points, dtype=float)
        bed_world_pts = np.asarray(body.world_points_mm, dtype=float)
        version = datetime.now(UTC).strftime("cal-%Y%m%dT%H%M%SZ")

        k_matrix: np.ndarray | None = None
        dist_coeffs: np.ndarray | None = None
        image_size: tuple[int, int] | None = None
        intrinsics_rms: float | None = None

        # Coordinate contract: when intrinsics are provided, the bed homography MUST be built on
        # UNDISTORTED image points, so it composes with the runtime `undistort_image -> warp_to_bed`
        # path (Calibration.H is defined on undistorted-image coordinates). Without intrinsics, keep
        # the homography-only behavior on raw points (back-compat, camera_matrix=None).
        if body.intrinsics is not None:
            image_size = (int(body.intrinsics.image_size[0]), int(body.intrinsics.image_size[1]))
            object_points = [
                np.asarray(v.object_points, dtype=float) for v in body.intrinsics.views
            ]
            view_image_points = [
                np.asarray(v.image_points, dtype=float) for v in body.intrinsics.views
            ]
            k_matrix, dist_coeffs, intrinsics_rms = calibrate_intrinsics(
                object_points, view_image_points, image_size
            )
            bed_img_for_h = undistort_points(bed_image_pts, k_matrix, dist_coeffs)
        else:
            bed_img_for_h = bed_image_pts

        h_matrix = compute_homography(bed_img_for_h, bed_world_pts)
        err = reprojection_error(h_matrix, bed_img_for_h, bed_world_pts)

        validation: dict[str, Any] | None = None
        if body.validation is not None:
            val_image_pts = np.asarray(body.validation.image_points, dtype=float)
            val_world_pts = np.asarray(body.validation.world_points_mm, dtype=float)
            if k_matrix is not None and dist_coeffs is not None:
                val_image_pts = undistort_points(val_image_pts, k_matrix, dist_coeffs)
            measured_mm = apply_homography(h_matrix, val_image_pts)
            validation = validate_dimensions(val_world_pts, measured_mm)

        calib = Calibration(
            H=h_matrix,
            mm_per_px=body.mm_per_px,
            bed_extent_mm=body.bed_extent_mm,
            version=version,
            reprojection_error=err,
            camera_matrix=k_matrix,
            dist_coeffs=dist_coeffs,
            distortion_model="opencv-5",
            image_size=image_size,
            validation=validation or {},
        )
        save_calibration(vision_calibration_path, calib)
        vision = vision_service()
        if vision is not None:
            vision.set_calibration(calib)
        return {
            "calibration_version": version,
            "reprojection_error": err,
            "intrinsics_rms": intrinsics_rms,
            "validation": validation,
            "corrected": k_matrix is not None,
        }

    # ---- guided calibration-capture session (A6b) ------------------------------------------
    def _calib_session_state() -> dict[str, Any]:
        spec: BoardSpec | None = app.state.calib_session_spec
        views: list[BoardDetection] = app.state.calib_session_views
        return {
            "n_views": len(views),
            "spec": dataclasses.asdict(spec) if spec is not None else None,
            "ready": len(views) >= _MIN_CALIB_VIEWS,
            "coverage": dataclasses.asdict(coverage(app.state.calib_session_cov)),
        }

    @app.post("/api/vision/calibrate/session")
    def vision_calibrate_session_start(body: CalibSessionBody) -> dict[str, Any]:
        """Start/reset a guided calibration-capture session. Clears accumulated views."""
        spec = _board_spec(body.spec) if body.spec is not None else _DEFAULT_CALIB_SPEC
        app.state.calib_session_spec = spec
        app.state.calib_session_views = []
        app.state.calib_session_image_size = None
        app.state.calib_session_cov = []
        return _calib_session_state()

    @app.get("/api/vision/calibrate/session")
    def vision_calibrate_session_get() -> dict[str, Any]:
        return _calib_session_state()

    def _accumulate_calibration_view(image: np.ndarray, spec: BoardSpec) -> dict[str, Any]:
        """Detect the session board in one frame and, if found, accumulate it. Shared by the
        server-grab and browser-upload capture endpoints so both feed calibration identically.
        Never raises on a blank/board-less frame: reports ``{captured: false, reason}``."""
        detection = detect_board(image, spec)
        if detection is None:
            return {"captured": False, "reason": "no board detected in frame"}
        views: list[BoardDetection] = app.state.calib_session_views
        views.append(detection)
        app.state.calib_session_image_size = (int(image.shape[1]), int(image.shape[0]))
        # Coverage descriptor for capture guidance: where in the frame + how tilted this view is.
        centroid = np.asarray(detection.image_points, float).reshape(-1, 2).mean(axis=0)
        app.state.calib_session_cov.append({
            "centroid_px": (float(centroid[0]), float(centroid[1])),
            "tilt_deg": view_tilt_deg(detection.image_points, detection.object_points),
            "image_size": (int(image.shape[1]), int(image.shape[0])),
        })
        return {
            "captured": True,
            "count": len(views),
            "corners_found": int(len(detection.image_points)),
        }

    @app.post("/api/vision/calibrate/capture")
    def vision_calibrate_capture() -> dict[str, Any]:
        """Grab one fresh frame from the SERVER science camera and accumulate it. Kept for setups
        with a resolvable server camera; the UI uses ``/capture-upload`` (browser frame) so
        calibration shares the same source as the print-time captures. Never raises on a board-less
        frame: reports ``{captured: false, reason}``."""
        spec: BoardSpec | None = app.state.calib_session_spec
        if spec is None:
            raise HTTPException(400, "no active calibration session; start one first")
        vision = vision_service()
        if vision is None:
            raise HTTPException(503, "no science camera available")
        try:
            frame = vision.grab_once()  # on-demand: open -> grab -> close, never held open
        except Exception as exc:  # noqa: BLE001 - a grab failure must not 500 the capture flow
            return {"captured": False, "reason": f"frame grab failed: {exc}"}
        return _accumulate_calibration_view(frame.image, spec)

    @app.post("/api/vision/calibrate/capture-upload")
    async def vision_calibrate_capture_upload(request: Request) -> dict[str, Any]:
        """Browser-side calibration capture: the operator grabs the science still from its ASSIGNED
        deviceId (reliable on macOS, unlike the server's cv2 index) and POSTs the encoded image as
        the raw body. Detection + accumulation run on the UPLOADED frame, so the intrinsics/bed
        homography are fit from the SAME getUserMedia source the print-time science captures use —
        and no server camera is needed (removes the macOS "no science camera" 503)."""
        spec: BoardSpec | None = app.state.calib_session_spec
        if spec is None:
            raise HTTPException(400, "no active calibration session; start one first")
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty image body")
        import cv2

        arr = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode uploaded image")
        return _accumulate_calibration_view(arr, spec)

    @app.post("/api/vision/calibrate/finalize")
    def vision_calibrate_finalize(body: CalibFinalizeBody) -> dict[str, Any]:
        """Compute intrinsics from the accumulated views + a bed homography on UNDISTORTED
        points, persist the calibration, and hot-swap it onto the live capture worker."""
        import cv2

        spec: BoardSpec | None = app.state.calib_session_spec
        if spec is None:
            raise HTTPException(400, "no active calibration session; start one first")
        views: list[BoardDetection] = app.state.calib_session_views
        if not views:
            raise HTTPException(400, "no calibration views captured; capture a board first")

        # Resolve the bed-plane correspondence BEFORE the heavy intrinsics compute.
        if body.use_last_capture_as_bed:
            last = views[-1]
            bed_image_pts = np.asarray(last.image_points, dtype=float)
            bed_world_pts = np.asarray(last.object_points, dtype=float)[:, :2]
        elif body.bed_image_points is not None and body.bed_world_points_mm is not None:
            bed_image_pts = np.asarray(body.bed_image_points, dtype=float)
            bed_world_pts = np.asarray(body.bed_world_points_mm, dtype=float)
        else:
            raise HTTPException(
                400,
                "no bed view: set use_last_capture_as_bed or provide bed_image_points + "
                "bed_world_points_mm",
            )

        image_size_raw = body.image_size or app.state.calib_session_image_size
        if image_size_raw is None:
            raise HTTPException(400, "unknown image size; capture at least one frame first")
        image_size = (int(image_size_raw[0]), int(image_size_raw[1]))

        try:
            k_matrix, dist_coeffs, intrinsics_rms = calibrate_intrinsics_boards(
                views, spec, image_size
            )
        except (cv2.error, ValueError) as exc:
            raise HTTPException(400, f"intrinsics calibration failed: {exc}") from exc

        bed_img_for_h = undistort_points(bed_image_pts, k_matrix, dist_coeffs)
        h_matrix = compute_homography(bed_img_for_h, bed_world_pts)
        err = reprojection_error(h_matrix, bed_img_for_h, bed_world_pts)

        version = datetime.now(UTC).strftime("cal-%Y%m%dT%H%M%SZ")
        calib = Calibration(
            H=h_matrix,
            mm_per_px=body.mm_per_px,
            bed_extent_mm=body.bed_extent_mm,
            version=version,
            reprojection_error=err,
            camera_matrix=k_matrix,
            dist_coeffs=dist_coeffs,
            distortion_model="opencv-5",
            image_size=image_size,
            validation={},
        )
        save_calibration(vision_calibration_path, calib)
        vision = vision_service()
        if vision is not None:
            vision.set_calibration(calib)
        return {
            "corrected": True,
            "intrinsics_rms": intrinsics_rms,
            "reprojection_error": err,
            "calibration_version": version,
            "n_views": len(views),
        }

    # ---- checkerboard-validation mode --------------------------------------------------------
    @app.post("/api/vision/validate")
    def vision_validate(body: VisionValidateBody) -> dict[str, Any]:
        """Validate dimensional accuracy against a certified checkerboard (protocol §5).

        Maps detected corners to bed-mm via point correspondences (undistort_points ->
        apply_homography on the CURRENT calibration, never off the warped raster), rigidly
        aligns (rotation + translation, NO scale) the measured points onto the known grid so
        residuals are not dominated by placement offset, then scores with validate_dimensions.
        A SEPARATE scale_bias (measured mean pitch / certified pitch) is returned so a scale
        error — which the no-scale fit deliberately does not absorb — is still caught.
        """
        vision = vision_service()
        calib: Calibration | None = vision.calibration if vision is not None else None
        if calib is None:
            raise HTTPException(400, "no calibration loaded; calibrate before validating")

        spec = _board_spec(body.spec)
        if spec.kind != "checkerboard":
            raise HTTPException(400, "validate requires a checkerboard spec")
        if spec.square_size_mm <= 0:
            raise HTTPException(400, "spec.square_size_mm must be > 0")
        if body.square_size_mm <= 0:
            raise HTTPException(400, "square_size_mm (certified pitch) must be > 0")

        if vision is None:
            raise HTTPException(503, "no science camera available")
        try:
            frame = vision.grab_once()  # on-demand: open -> grab -> close, never held open
        except Exception as exc:  # noqa: BLE001 - a grab failure must not 500 the request
            raise HTTPException(400, f"frame grab failed: {exc}") from exc
        return _score_checkerboard_mm(frame.image, spec, body.square_size_mm, calib)

    def _score_checkerboard_mm(
        image: np.ndarray, spec: BoardSpec, certified_mm: float, calib: Calibration,
        target_mm: float = 0.05,
    ) -> dict[str, Any]:
        """Score a checkerboard image against its certified pitch through the CURRENT calibration:
        corners -> undistort -> bed-mm homography -> rigid (no-scale) align onto the known grid ->
        residuals (mm). A separate scale_bias catches a pure scale error the no-scale fit ignores.
        ``passed`` is advisory vs ``target_mm`` (the ±0.05 mm band)."""
        detection = detect_board(image, spec)
        if detection is None:
            raise HTTPException(400, "checkerboard not detected in frame")
        img_pts = np.asarray(detection.image_points, dtype=float)
        if calib.camera_matrix is not None:
            dist = calib.dist_coeffs if calib.dist_coeffs is not None else np.zeros(5)
            img_pts = undistort_points(img_pts, calib.camera_matrix, dist)
        measured_mm = apply_homography(calib.H, img_pts)
        known_mm = np.asarray(detection.object_points, dtype=float)[:, :2]
        known_mm = known_mm * (certified_mm / spec.square_size_mm)
        r_mat, t_vec = rigid_transform_2d(measured_mm, known_mm)
        aligned_mm = measured_mm @ r_mat.T + t_vec
        scored = validate_dimensions(known_mm, aligned_mm)
        return {
            "rms_mm": scored["rms_mm"],
            "max_mm": scored["max_mm"],
            "per_point": scored["points"],
            "scale_bias": _grid_scale_bias(known_mm, measured_mm, certified_mm),
            "n_points": int(len(known_mm)),
            "target_mm": target_mm,
            "passed": bool(scored["max_mm"] <= target_mm),
        }

    @app.post("/api/vision/validate/scale-upload")
    async def vision_validate_scale_upload(
        request: Request,
        cols: int = Query(...),
        rows: int = Query(...),
        square_size_mm: float = Query(...),
        certified_mm: float = Query(...),
        target_mm: float = Query(default=0.05),
    ) -> dict[str, Any]:
        """Browser-image scale validation: the operator captures the chessboard via getUserMedia and
        POSTs the encoded image (raw body); scored against the current calibration in world-mm. Same
        source as the print-time captures (fixes the server-grab frame-source mismatch)."""
        vision = app.state.vision
        calib = vision.calibration if vision is not None else load_calibration(
            vision_calibration_path
        )
        if calib is None:
            raise HTTPException(400, "no calibration loaded; calibrate before validating")
        if square_size_mm <= 0 or certified_mm <= 0:
            raise HTTPException(400, "square_size_mm and certified_mm must be > 0")
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty image body")
        import cv2

        arr = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode uploaded image")
        spec = BoardSpec(kind="checkerboard", cols=cols, rows=rows, square_size_mm=square_size_mm)
        result = _score_checkerboard_mm(arr, spec, certified_mm, calib, target_mm)
        # Persist trust keyed to this calibration version, so the analysis can tell validated apart.
        save_validation(
            root / ".vision_validation.json",
            calib.version,
            {"max_mm": result["max_mm"], "rms_mm": result["rms_mm"],
             "passed": result["passed"], "target_mm": target_mm,
             "scale_bias": result["scale_bias"]},
        )
        return result

    @app.get("/api/vision/captures")
    def vision_captures(run: str) -> list[dict[str, Any]]:
        target = _run_dir_opt(run)  # local or a mounted drive; None -> no run yet -> empty list
        records = read_manifest(target) if target is not None else []
        for record in records:
            registered = record.get("registered")
            if isinstance(registered, str) and registered:
                record["url"] = _vision_file_url(run, registered)
                record["sidecar_url"] = _vision_file_url(run, _sidecar_rel_path(registered))
        return records

    @app.post("/api/vision/science/client-heartbeat")
    def science_client_heartbeat() -> dict[str, Any]:
        """The browser science-capture client pings this while it's mounted and ready to capture.
        While the heartbeat is fresh, the server SKIPS its own cv2 grab on each capture mark (the
        client captures from the right camera instead). On non-macOS systems a lapse after ~8s lets
        the server resume; macOS never falls back to an ambiguous OS camera index."""
        app.state.science_client_until = time.monotonic() + 8.0
        return {"ok": True, "until_s": 8.0}

    @app.post("/api/vision/science/client-fallback")
    def science_client_fallback(seq: int = Query(...)) -> dict[str, Any]:
        """Hand a capture back to the server when a browser that had claimed ownership can no
        longer produce a frame. The sequence guard prevents a delayed browser failure from
        recapturing a newer layer or stage."""
        capture = getattr(app.state, "capture_request", None)
        if not isinstance(capture, dict) or int(capture.get("seq", -1)) != seq:
            raise HTTPException(409, "capture request is no longer current")
        if rec().current_run_dir is None:
            raise HTTPException(409, "no active recording run")
        if server_science_fallback_blocked:
            raise HTTPException(
                503,
                "server science fallback is disabled on macOS because camera indexes can open "
                "FaceTime or Continuity Camera; the assigned USB camera must capture in-browser",
            )
        vision = vision_service()
        if vision is None:
            raise HTTPException(503, "science capture service is not running")
        stage = str(capture.get("stage", ""))
        if label_to_stage(f"capture:{stage}") is None:
            raise HTTPException(400, "invalid capture stage")
        app.state.science_client_until = 0.0
        vision.on_event(
            f"capture:{stage}",
            {
                "layer": capture.get("layer"),
                "print_layer": capture.get("cad_layer"),
                "host_timestamp_ns": time.time_ns(),
            },
        )
        return {"queued": True}

    @app.post("/api/vision/science/capture")
    async def science_capture(
        request: Request,
        layer: int = Query(...),
        stage: str = Query(...),
        cad_layer: int | None = Query(default=None),
    ) -> dict[str, Any]:
        """CLIENT-side science capture: the browser grabs the still from the ASSIGNED science camera
        (opened by its deviceId — reliable on macOS, unlike the server's cv2 device index) and POSTs
        the encoded image as the raw body. The operator decodes it and stores it through the same
        path as a server grab, enriching job + axis positions server-side (the browser can't read
        the recoater position). Query: layer (absolute), stage, cad_layer (printing index)."""
        if stage not in ("pre_jet", "post_jet", "post_heat"):
            raise HTTPException(400, f"bad stage {stage!r}")
        # Browser device assignments are independent of server camera discovery. Saving an
        # already captured image needs a run and calibration, not an open server camera.
        vision = app.state.vision
        calibration = vision.calibration if vision is not None else load_calibration(
            vision_calibration_path
        )
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty image body")
        import cv2

        arr = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode uploaded image")
        if not image_has_usable_content(arr):
            raise HTTPException(422, "uploaded science image is blank or near-uniform")
        job = app.state.job.to_dict() if app.state.job is not None else {}
        axis: dict[str, float] = {}
        try:
            ctrl = getattr(app.state, "controller", None)
            tel = ctrl.snapshot().get("telemetry") if ctrl is not None else None
            if tel and tel.get("positions"):
                names = {1: "build", 2: "feed", 3: "printhead", 4: "recoater"}
                axis = {names.get(int(k), str(k)): float(v) for k, v in tel["positions"].items()}
        except Exception:  # noqa: BLE001 - axis positions are best-effort metadata
            axis = {}
        paths = store_uploaded(
            arr, run_dir=rec().current_run_dir, calibration=calibration,
            layer=layer, stage=stage, cad_layer=cad_layer, axis_positions=axis, job=job,
        )
        if paths is None:
            raise HTTPException(409, "no active recording run to store the capture under")
        return {"stored": True}

    @app.post("/api/vision/overview/capture")
    async def overview_capture(request: Request) -> dict[str, Any]:
        """CLIENT-side OVERVIEW timelapse frame: the browser grabs a frame off the ASSIGNED overview
        camera on a timer during a recorded print and POSTs the encoded image as the raw body.
        Stored
        time-ordered under ``<run>/overview/`` for a whole-print overview timelapse. 409 when no run
        is recording (frames only make sense inside a run)."""
        run_dir = rec().current_run_dir
        if run_dir is None:
            raise HTTPException(409, "no active recording run to store the overview frame under")
        body = await request.body()
        if not body:
            raise HTTPException(400, "empty image body")
        import cv2

        arr = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode uploaded image")
        write_overview_frame(run_dir, arr)
        return {"stored": True}

    def _with_calibration_trust(out: dict[str, Any]) -> dict[str, Any]:
        """Advisory: flag when the active calibration has no PASSING scale validation, so a
        never read as trustworthy on an unvalidated calibration. Never overrides an existing warning
        and never changes status."""
        calib = load_calibration(vision_calibration_path)
        if calib is not None and not out.get("calibration_warning"):
            warn = calibration_validation_warning(
                calib.version, load_validation(root / ".vision_validation.json")
            )
            if warn:
                out["calibration_warning"] = warn
        return out

    @app.post("/api/analysis/{run}/dimensional")
    def analysis_dimensional_run(
        run: str, body: DimensionalAnalyzeRequest | None = None
    ) -> dict[str, Any]:
        """Run (or re-run) Lane A dimensional analysis on a recorded run and persist it.

        Returns the report dict. Non-ok statuses (no_capture / no_calibration / roi_failed)
        are honest 200 reports, not HTTP errors; only a bad run name (400) or unknown run
        (404) are errors, via the shared run-path validation.
        """
        run_dir = _run_dir_404(run)
        req = body or DimensionalAnalyzeRequest()
        nominals = {**DEFAULTS, **req.nominals} if req.nominals else DEFAULTS
        report = analyze_run(
            run_dir,
            layer=req.layer,
            stage=req.stage,
            rois=req.rois,
            circle=req.circle.model_dump() if req.circle else None,
            nominals=nominals,
        )
        return _with_calibration_trust(report.to_dict())

    @app.get("/api/analysis/{run}/dimensional")
    def analysis_dimensional_get(run: str) -> dict[str, Any]:
        """Return a run's persisted dimensional report, or {status: "not_run"} if absent."""
        run_dir = _run_dir_404(run)
        report = load_report(run_dir)
        if report is None:
            return {"status": "not_run", "run": run}
        return _with_calibration_trust(report)

    @app.get("/api/analysis/{run}/lane-b")
    def analysis_lane_b(
        run: str, layer: int, folder: str, stage: str = "post_jet"
    ) -> dict[str, Any]:
        """Lane B — CAD-vs-real deviation heatmap for one layer. Compares the run's registered
        science capture of `layer` against that layer in job `folder`'s CAD slice. Non-ok statuses
        (no_capture / no_calibration / no_contour) are honest 200 reports; a bad run (400/404) or
        unknown job folder (404) are errors. NOTE: the two outlines are centroid-aligned, so this
        reports shape+size deviation independent of bed placement; registration scale still wants
        validation on real captures."""
        run_dir = _run_dir_404(run)
        cap = _select_capture(read_manifest(run_dir), layer, stage)
        if cap is None:
            return {"status": "no_capture", "run": run, "layer": layer, "stage": stage}
        registered_rel = str(cap["registered"])
        mm_per_px = _read_mm_per_px(_sidecar_path_for(run_dir, registered_rel))
        if mm_per_px is None:
            return {"status": "no_calibration", "message": "capture has no registered mm_per_px"}
        job = next((j for j in jobs.scan() if j.dir.name == folder), None)
        if job is None:
            raise HTTPException(404, f"no job folder {folder!r}")
        try:
            cad_png, cad_mm_per_px = layer_png_scaled(job, layer)
        except IndexError as exc:
            raise HTTPException(404, str(exc)) from exc
        cap_path = (run_dir / registered_rel).resolve()
        if cap_path.parent != run_dir.resolve() and run_dir.resolve() not in cap_path.parents:
            raise HTTPException(400, "capture path escapes the run directory")
        report = analyze_lane_b_from_pngs(
            cap_path.read_bytes(), cad_png, mm_per_px, cad_mm_per_px
        )
        return {
            "run": run, "layer": layer, "folder": folder,
            "capture_url": _vision_file_url(run, registered_rel),  # to overlay the heatmap on
            **report,
        }

    @app.get("/api/vision/runs/{run}/file")
    def vision_run_file(run: str, path: str) -> FileResponse:
        """Serve one file from a run's vision/ subtree (registered capture image or sidecar
        JSON). Security-critical: `path` is attacker-controlled query input, so the resolved
        real path is checked to still be inside this run's vision/ directory before anything
        is read from disk — this rejects `..` escapes, absolute-path overrides, and symlink
        escapes alike (Path.resolve() follows symlinks to their real target)."""
        run_root = _run_dir_404(run)  # local or a mounted drive
        vision_root = run_root / "vision"
        try:
            vision_root_resolved = vision_root.resolve()
        except OSError as exc:
            raise HTTPException(404, "not found") from exc
        try:
            resolved = (run_root / path).resolve()
        except OSError as exc:
            raise HTTPException(404, "not found") from exc
        if not resolved.is_relative_to(vision_root_resolved):
            raise HTTPException(403, "path escapes the run's vision directory")
        if resolved.suffix.lower() not in VISION_FILE_MEDIA_TYPES:
            raise HTTPException(403, "unsupported file type")
        if not resolved.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(resolved, media_type=VISION_FILE_MEDIA_TYPES[resolved.suffix.lower()])

    @app.get("/api/vision/science/frame.jpg")
    def vision_science_frame() -> Response:
        """One still from the SCIENCE camera as a JPEG, on demand (open -> grab -> close). Used by
        the capture-pose calibration overlay to aim the overhead cam over the bed. 503 when no
        science camera is available."""
        vision = vision_service()
        if vision is None:
            raise HTTPException(503, "no science camera available")
        try:
            frame = vision.grab_once()
        except Exception as exc:  # noqa: BLE001 - a grab failure -> 502, never a 500
            raise HTTPException(502, f"frame grab failed: {exc}") from exc
        return Response(content=encode_jpeg(frame.image), media_type="image/jpeg")

    @app.get("/api/vision/science/stream")
    def vision_science_stream() -> StreamingResponse:
        """Live MJPEG from the SCIENCE camera for the capture-pose alignment overlay. Setup-only: it
        holds the science source open, so it is refused (409) while a print/routine runs (that owns
        the capture source). 503 when no science camera is available."""
        if printer().state in (PrintState.RUNNING, PrintState.PAUSED):
            raise HTTPException(409, "a print is running; the science stream is for setup only")
        vision = vision_service()
        if vision is None:
            raise HTTPException(503, "no science camera available")
        stream = vision.stream_jpeg()
        try:
            first = next(stream)  # eager open so a broken camera -> 503, not a half-open 200
        except StopIteration as exc:
            raise HTTPException(503, "science camera produced no frame") from exc
        except Exception as exc:  # noqa: BLE001 - a failed open -> 503, not a 500
            stream.close()
            raise HTTPException(503, f"science camera unavailable: {exc}") from exc

        def gen() -> Iterator[bytes]:
            try:
                yield first
                yield from stream
            finally:
                stream.close()  # closes the source + releases the lock on client disconnect

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/vision/overview/stream")
    def vision_overview_stream() -> StreamingResponse:
        # The dedicated OVERVIEW camera only — never the science source, which the vision
        # worker owns and is not safe to share (I1). Absent/broken overview camera -> 503.
        # Camera-on-demand: frames() is the on-demand trigger — it opens the device for THIS
        # viewer (releasing it when the last viewer disconnects). It opens eagerly so a broken
        # camera surfaces here as a 503, not a half-open 200.
        streamer = overview_streamer()
        if streamer is None:
            raise HTTPException(503, "no dedicated overview camera available")
        try:
            stream = streamer.frames()
        except Exception as exc:  # noqa: BLE001 - a failed on-demand open -> 503, not a 500
            raise HTTPException(503, f"overview camera unavailable: {exc}") from exc
        return StreamingResponse(
            stream, media_type="multipart/x-mixed-replace; boundary=frame"
        )

    # ---- websocket --------------------------------------------------------------------------
    @app.websocket("/ws/telemetry")
    async def ws_telemetry(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                await ws.send_json(status_payload())
                await asyncio.sleep(0.1)
        except WebSocketDisconnect:
            return

    dist = frontend_dist or _DEFAULT_FRONTEND_DIST
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    return app


__all__ = ["API_VERSION", "create_app", "install_cross_origin_policy"]
