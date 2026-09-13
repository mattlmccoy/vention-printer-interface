"""FastAPI app (spec §5). GET /api/status and /ws/telemetry are the same payload.

Cross-origin policy is copied from FLIR/T&C: cross-origin state-changing /api/ requests must carry
``X-VPI-Client: 1``; CORS allows the hosted-site origin plus localhost.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import platform
import socket
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vention_printer_interface import __version__
from vention_printer_interface.control.controller import REFERENCE_MATCH_TOL_MM, Controller
from vention_printer_interface.control.events import EventLog
from vention_printer_interface.control.heater_model import exposure
from vention_printer_interface.control.limits_store import load_limits, save_limits
from vention_printer_interface.control.macros import MACROS, macro_steps
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
from vention_printer_interface.device import create_transport, registered_transports
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.jobs.store import JobInfo, JobStore, layer_png, load_job
from vention_printer_interface.protocol import routes as r
from vention_printer_interface.recording.recorder import Recorder
from vention_printer_interface.vision.cameras import CameraConfig
from vention_printer_interface.vision.capture import VisionService
from vention_printer_interface.vision.frame_source import FrameSource, UvcFrameSource
from vention_printer_interface.vision.overview import encode_jpeg, mjpeg_chunk
from vention_printer_interface.vision.registration import (
    Calibration,
    compute_homography,
    load_calibration,
    reprojection_error,
    save_calibration,
)
from vention_printer_interface.vision.store import read_manifest

log = logging.getLogger(__name__)

API_VERSION = "0.1"
LOCAL_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
CLIENT_HEADER = "x-vpi-client"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
RUN_FILES = frozenset(
    {"telemetry.csv", "events.json", "metadata.json", "manifest.json", "layers.csv"}
)
_DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"
DEFAULT_HEATER_IO: tuple[int, int] = (1, 0)  # UNVERIFIED: identify during commissioning


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


class PrintStartBody(BaseModel):
    dry_run: bool = False
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


class VisionCalibrateBody(BaseModel):
    image_points: list[tuple[float, float]]
    world_points_mm: list[tuple[float, float]]
    mm_per_px: float
    bed_extent_mm: tuple[float, float, float, float]


def _tcp_open(ip: str, port: int, timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout_s):
            return True
    except OSError:
        return False


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


def create_app(
    *,
    backend: str = "none",
    ip: str | None = None,
    poll_interval_s: float = 0.2,
    experiments_root: Path | None = None,
    limits: SafetyLimits | None = None,
    frontend_dist: Path | None = None,
    site_origin: str | None = None,
    heater_io: tuple[int, int] | None = None,
    print_min_wait_s: float = 0.5,
    print_step_timeout_s: float = 120.0,
    jobs_roots: list[Path] | None = None,
    vision_source: FrameSource | None = None,
) -> FastAPI:
    root = experiments_root or Path.cwd() / "experiments"
    jobs = JobStore(jobs_roots or [root.parent / "jobs"])
    camera_config = CameraConfig.from_env()
    vision_calibration_path = root / ".vision_calibration.json"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        controller = Controller(poll_interval_s=poll_interval_s, limits=limits or load_limits(root))
        recorder = Recorder(root)
        printer = PrintController(
            controller, min_wait_s=print_min_wait_s, step_timeout_s=print_step_timeout_s
        )
        app.state.auto_log = True
        app.state.auto_run_open = False
        events = EventLog()
        events.add_sink(recorder.event)  # every event also lands in the durable run record

        # Vision: a science-camera capture worker fed by capture:* marks off the same EventLog.
        # Guard hardware: an absent/broken camera must never block or crash app startup.
        science = camera_config.science
        source = vision_source or UvcFrameSource(
            science.index, science.width, science.height, science.effective_backend()
        )
        vision_svc = VisionService(
            source=source,
            run_dir_provider=lambda: recorder.current_run_dir,
            calibration=load_calibration(vision_calibration_path),
            camera_role="science",
        )
        try:
            vision_svc.start()
            events.add_sink(vision_svc.on_event)
            app.state.vision = vision_svc
        except Exception as exc:  # noqa: BLE001 - a missing/broken camera must not block startup
            log.warning("vision service start failed (%s); serving without capture", exc)
            app.state.vision = None
        app.state.vision_source = source

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
        app.state.reference_restored = False
        app.state.job = None
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

    def vision_src() -> FrameSource:
        return app.state.vision_source  # type: ignore[no-any-return]

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
        }

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
            name = body.name or ("dry-run" if body.dry_run else "print")
            rec().start(
                name,
                notes=body.notes,
                metadata={
                    "backend": app.state.backend,
                    "device": ctrl().snapshot()["device"],
                    "limits": ctrl().limits.to_dict(),
                    "print_settings": plan.to_dict(),
                    "dry_run": body.dry_run,
                },
            )
            app.state.auto_run_open = True
            opened = True
        try:
            guarded(printer().start, plan, body.dry_run, body.single_step)
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

    @app.get("/api/recordings")
    def recordings() -> dict[str, Any]:
        return {"runs": rec().list_runs()}

    @app.get("/api/recordings/{run}/{name}")
    def recording_file(run: str, name: str) -> FileResponse:
        if name not in RUN_FILES:
            raise HTTPException(404, "unknown file")
        target = (root / run / name).resolve()
        if target.parent.parent != root.resolve() or not target.exists():
            raise HTTPException(400, "bad run")
        return FileResponse(target)

    # ---- vision (overview + science cameras) -------------------------------------------------
    @app.get("/api/vision/status")
    def vision_status() -> dict[str, Any]:
        vision = vision_service()
        if vision is None:
            return {"cameras": [], "calibration": None, "queue": {"drops": 0}, "active": False}
        calib: Calibration | None = vision._calibration  # noqa: SLF001 - hot-swap contract
        return {
            "cameras": [camera_config.science.role],
            "calibration": calib.version if calib is not None else None,
            "queue": {"drops": vision.drops},
            "active": True,
        }

    @app.get("/api/vision/cameras")
    def vision_cameras() -> dict[str, Any]:
        return {
            "overview": dataclasses.asdict(camera_config.overview),
            "science": dataclasses.asdict(camera_config.science),
        }

    @app.post("/api/vision/calibrate")
    def vision_calibrate(body: VisionCalibrateBody) -> dict[str, Any]:
        image_pts = np.asarray(body.image_points, dtype=float)
        world_pts = np.asarray(body.world_points_mm, dtype=float)
        h_matrix = compute_homography(image_pts, world_pts)
        err = reprojection_error(h_matrix, image_pts, world_pts)
        version = datetime.now(UTC).strftime("cal-%Y%m%dT%H%M%SZ")
        calib = Calibration(
            H=h_matrix,
            mm_per_px=body.mm_per_px,
            bed_extent_mm=body.bed_extent_mm,
            version=version,
            reprojection_error=err,
        )
        save_calibration(vision_calibration_path, calib)
        vision = vision_service()
        if vision is not None:
            vision._calibration = calib  # noqa: SLF001 - hot-swap the running service's calibration
        return {"reprojection_error": err, "calibration_version": version}

    @app.get("/api/vision/captures")
    def vision_captures(run: str) -> list[dict[str, Any]]:
        target = (root / run).resolve()
        if target.parent != root.resolve():
            raise HTTPException(400, "bad run")
        return read_manifest(target)

    @app.get("/api/vision/overview/stream")
    def vision_overview_stream() -> StreamingResponse:
        source = vision_src()

        def gen() -> Iterator[bytes]:
            while True:
                frame = source.grab()
                yield mjpeg_chunk(encode_jpeg(frame.image))

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

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
