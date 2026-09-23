"""/api/vision/uvc/* -- read, set and factory-reset a camera's UVC controls from the operator.

Exists for macOS, where the browser exposes almost none of a UVC camera's controls to
getUserMedia. Cameras are addressed by their AVFoundation unique id; ignored cameras are hidden
and refused like unknown ones.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from vention_printer_interface.vision.uvc import (
    UvcError,
    parse_vc_topology,
    read_controls,
    reset_to_defaults,
    set_control,
)
from vention_printer_interface.vision.uvc_backend import UvcBackend
from vention_printer_interface.vision.uvc_macos import UvcTransportError

log = logging.getLogger(__name__)

NO_BACKEND = "operator-side camera controls are only implemented on macOS"


class UvcSetBody(BaseModel):
    key: str
    value: float | bool


def register_uvc_routes(
    app: FastAPI,
    backend: UvcBackend | None,
    ignored: Callable[[], list[str]],
    science_uid: Callable[[], str | None],
) -> None:
    def visible() -> list[dict[str, str]]:
        if backend is None:
            return []
        hidden = set(ignored())
        return [c for c in backend.cameras() if c["unique_id"] not in hidden]

    def run(uid: str, fn: Callable[[Any, Any], Any]) -> Any:
        if backend is None:
            raise HTTPException(503, NO_BACKEND)
        if uid not in {c["unique_id"] for c in visible()}:
            raise HTTPException(404, f"no controllable camera {uid}")
        try:
            with backend.open(uid) as dev:
                topo = parse_vc_topology(dev.config_descriptor())
                return fn(dev, topo)
        except KeyError as exc:
            raise HTTPException(404, f"camera {uid} disconnected") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (UvcError, UvcTransportError) as exc:
            log.warning("UVC request to %s failed: %s", uid, exc)
            raise HTTPException(502, f"the camera refused the request: {exc}") from exc

    @app.get("/api/vision/uvc")
    def uvc_cameras() -> dict[str, Any]:
        sci = science_uid()
        cams = [{**c, "science": c["unique_id"] == sci} for c in visible()]
        return {"available": backend is not None,
                "reason": None if backend is not None else NO_BACKEND, "cameras": cams}

    @app.get("/api/vision/uvc/{uid}/controls")
    def uvc_controls(uid: str) -> dict[str, Any]:
        return {"controls": run(uid, read_controls)}

    @app.put("/api/vision/uvc/{uid}/controls")
    def uvc_set(uid: str, body: UvcSetBody) -> dict[str, Any]:
        def do(dev: Any, topo: Any) -> list[dict[str, Any]]:
            set_control(dev, topo, body.key, body.value)
            return read_controls(dev, topo)

        return {"controls": run(uid, do)}

    @app.post("/api/vision/uvc/{uid}/reset")
    def uvc_reset(uid: str) -> dict[str, Any]:
        def do(dev: Any, topo: Any) -> dict[str, Any]:
            result = reset_to_defaults(dev, topo)
            return {**result, "controls": read_controls(dev, topo)}

        result: dict[str, Any] = run(uid, do)
        return result
