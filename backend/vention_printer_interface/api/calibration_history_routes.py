"""Science-camera calibration history (Settings -> Calibrations).

Routes:
  GET  /api/vision/calibrations                          -> every calibration, newest first
  GET  /api/vision/calibrations/{version}                -> one: summary, report, validations
  GET  /api/vision/calibrations/{version}/images/{name}.jpg
  POST /api/vision/calibrations/{version}/activate       -> make it the calibration in use

Storage and record shapes: vision/calibration_history.py.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from vention_printer_interface.vision.calibration_history import (
    calibration_detail,
    image_path,
    list_calibrations,
    load_archived,
)
from vention_printer_interface.vision.registration import Calibration, save_calibration


class ActivateBody(BaseModel):
    # The science camera's current photo size, when the console knows it: a calibration only
    # measures photos of the size it was fitted on, so a mismatch is refused (409).
    expect_image_size: list[int] | None = None


def register_calibration_history_routes(
    app: FastAPI,
    *,
    root: Path,
    calibration_path: Path,
    active: Callable[[], Calibration | None],
    on_activated: Callable[[Calibration], None],
    events: Callable[[str, dict[str, Any]], None],
) -> None:
    @app.get("/api/vision/calibrations")
    def calibrations_list() -> list[dict[str, Any]]:
        return list_calibrations(root, active=active())

    @app.get("/api/vision/calibrations/{version}")
    def calibrations_detail(version: str) -> dict[str, Any]:
        d = calibration_detail(root, version, active=active())
        if d is None:
            raise HTTPException(404, f"no calibration {version!r}")
        return d

    @app.get("/api/vision/calibrations/{version}/images/{name}.jpg")
    def calibrations_image(version: str, name: str) -> FileResponse:
        f = image_path(root, version, name)
        if f is None or not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f, media_type="image/jpeg",
                            headers={"Cache-Control": "max-age=86400, immutable"})

    @app.post("/api/vision/calibrations/{version}/activate")
    def calibrations_activate(version: str, body: ActivateBody) -> dict[str, Any]:
        calib = load_archived(root, version)
        if calib is None:
            raise HTTPException(404, f"no archived calibration {version!r}")
        want = body.expect_image_size
        if want is not None and calib.image_size is not None and \
                tuple(int(v) for v in want) != tuple(calib.image_size):
            w, h = calib.image_size
            raise HTTPException(409, (
                f"{version} was fitted on {w}x{h} photos but the science camera takes "
                f"{want[0]}x{want[1]}; set the camera to {w}x{h} first, or it would not "
                "measure anything"))
        save_calibration(calibration_path, calib)
        on_activated(calib)
        events("calibration_activated", {"calibration_version": version})
        return {"active": version}
