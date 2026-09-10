"""FastAPI app (spec §5). GET /api/status and /ws/telemetry are the same payload.

Cross-origin policy is copied from FLIR/T&C: cross-origin state-changing /api/ requests must carry
``X-VPI-Client: 1``; CORS allows the hosted-site origin plus localhost.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vention_printer_interface import __version__
from vention_printer_interface.control.controller import Controller
from vention_printer_interface.control.events import EventLog
from vention_printer_interface.control.limits_store import load_limits, save_limits
from vention_printer_interface.control.macros import MACROS, macro_steps
from vention_printer_interface.control.priming import PrimingSettings, compile_priming
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
from vention_printer_interface.control.safety import HARD_BOUNDS, SafetyLimits
from vention_printer_interface.device import create_transport, registered_transports
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.jobs.store import JobInfo, JobStore, layer_png, load_job
from vention_printer_interface.protocol import routes as r
from vention_printer_interface.recording.recorder import Recorder

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


class JobSelectBody(BaseModel):
    path: str


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
    app.state.controller.attach_device(device, backend=backend)
    app.state.backend = backend
    app.state.axis_motion = _fresh_axis_motion()


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
) -> FastAPI:
    root = experiments_root or Path.cwd() / "experiments"
    jobs = JobStore(jobs_roots or [root.parent / "jobs"])

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

        # Order matters: the print controller ticks first so the recorder logs it.
        controller.add_listener(printer.tick)
        controller.add_listener(on_controller_state)
        controller.add_listener(recorder.record)
        app.state.events = events
        app.state.controller, app.state.recorder, app.state.printer = controller, recorder, printer
        app.state.print_settings = load_print_settings(root, controller.limits)
        app.state.priming = load_priming(root, controller.limits)
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
        return {
            "plan": plan.to_dict(),
            "validation": plan.validate(ctrl().limits),
            "n_steps": len(compile_print(plan)),
            "estimated_duration_s": estimate_duration_s(plan, print_min_wait_s),
            "total_layers": plan.total_layers,
            "total_thickness_mm": plan.total_thickness_mm,
            "bounds": HARD_BOUNDS,
            "limits": ctrl().limits.to_dict(),
        }

    def priming_payload() -> dict[str, Any]:
        s: PrimingSettings = app.state.priming
        steps = compile_priming(s, ctrl().limits)
        cycles = sum(1 for st in steps if st.kind == "mark" and st.label == "layer_start")
        return {
            "settings": s.to_dict(),
            "validation": s.validate(ctrl().limits),
            "n_steps": len(steps),
            "n_cycles": cycles,
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
        guarded(printer().start_macro, "priming", compile_priming(settings, ctrl().limits))
        return printer().snapshot()

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
