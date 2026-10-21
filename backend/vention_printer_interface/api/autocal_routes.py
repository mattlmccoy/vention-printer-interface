"""Automatic science-camera calibration session (spec 2026-10-20-auto-calibration-design.md).

The browser drives motion and capture, exactly like the camera-centre sweep: it moves the recoater
to each planned position, waits for it to settle, takes the still through the print capture path and
uploads it here with the recoater position read back from telemetry. This module holds the session,
detects the ChArUco corners on each uploaded still (one photo size per session), solves and judges
the calibration, and saves it only when the run passed.

Routes:
  GET  /api/vision/autocal/window    -> remembered safety window (default 0–523 mm)
  POST /api/vision/autocal/session   -> plan the sweep (refused when the capture pose is outside)
  POST /api/vision/autocal/sample    -> add one still (raw image body, ?recoater_mm=)
  GET  /api/vision/autocal/session   -> plan + samples + corner coverage
  POST /api/vision/autocal/solve     -> solve + verdict (kept pending in the session)
  POST /api/vision/autocal/selfcheck -> score the pending solve on a photo of the MOVED board
  POST /api/vision/autocal/save      -> persist a PASSING, SELF-CHECKED result
  POST /api/vision/autocal/cancel
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from vention_printer_interface.vision.autocal_plan import plan_sweep
from vention_printer_interface.vision.autocal_solve import (
    MAX_REPROJ_MM,
    MIN_CORNERS,
    AutocalView,
    judge,
    solve_autocal,
    to_calibration,
)
from vention_printer_interface.vision.board_gen import (
    BoardSpecError,
    validate_charuco_spec,
    with_auto_dict,
)
from vention_printer_interface.vision.charuco_points import detect_board_points
from vention_printer_interface.vision.charuco_selfcheck import score_self_check
from vention_printer_interface.vision.coverage import corner_cells
from vention_printer_interface.vision.registration import (
    BoardSpec,
    Calibration,
    apply_homography,
    save_calibration,
    undistort_points,
)

DEFAULT_WINDOW = (0.0, 523.0)  # Matt, 2026-10-20: 523 mm is the farthest safe extent (blade)
PLANE_NOTE = "board top surface, assumed print plane"
# Every sweep position (incl. the capture pose) is approached going DOWN in mm. Prints reach the
# capture pose from above for pre_jet and from below for post_jet, so recoater backlash can offset
# post_jet stills; recorded so it can be checked once backlash on axis 4 is measured.
APPROACH_NOTE = "from above (descending mm)"


class AutocalBoard(BaseModel):
    kind: Literal["charuco"] = "charuco"
    squares_x: int
    squares_y: int
    square_length_mm: float
    marker_length_mm: float
    aruco_dict: str | None = None


class AutocalSessionBody(BaseModel):
    spec: AutocalBoard
    window_min_mm: float
    window_max_mm: float
    step_mm: float = 5.0
    max_offset_mm: float = 70.0
    placement: Literal["substrate", "cylinder"]
    board_thickness_mm: float = 3.175


def _window_path(root: Path) -> Path:
    return Path(root) / ".autocal.json"


def load_window(root: Path) -> tuple[float, float]:
    try:
        raw = json.loads(_window_path(root).read_text(encoding="utf-8"))
        lo, hi = float(raw["min_mm"]), float(raw["max_mm"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_WINDOW
    return (lo, hi) if math.isfinite(lo) and math.isfinite(hi) else DEFAULT_WINDOW


def _finite(d: dict[str, Any]) -> dict[str, Any]:
    """JSON has no NaN: an unmeasured value (no point pairs, an empty group) reports null."""
    def clean(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        return v
    return {k: clean(v) for k, v in d.items()}


def _sweep_path(root: Path) -> Path:
    return Path(root) / ".autocal_last_sweep.json"


async def _session_photo(request: Request, s: dict[str, Any]) -> tuple[np.ndarray, tuple[int, int]]:
    """Decode the uploaded still; refuse a photo of another size than this run's (409)."""
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty image body")
    import cv2

    image = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "could not decode uploaded image")
    size = (int(image.shape[1]), int(image.shape[0]))
    if s["image_size"] is not None and tuple(s["image_size"]) != size:
        # A resolution change FAILS the run: a calibration only holds at one photo size, and a
        # quiet "board not found" would let a sweep finish on the old size and pass.
        first = s["image_size"]
        raise HTTPException(409, (
            f"photo size {size[0]}x{size[1]} differs from this run's {first[0]}x{first[1]}; "
            "keep the science camera at one resolution and start again"))
    return image, size


def register_autocal_routes(
    app: FastAPI,
    *,
    root: Path,
    capture_pose: Callable[[], float],
    calibration_path: Path,
    on_saved: Callable[[Calibration], None],
    events: Callable[[str, dict[str, Any]], None],
) -> None:
    state: dict[str, Any] = {"session": None}

    def session() -> dict[str, Any]:
        s = state["session"]
        if s is None:
            raise HTTPException(409, "no automatic calibration in progress; start one first")
        return s  # type: ignore[no-any-return]

    def summary(s: dict[str, Any]) -> dict[str, Any]:
        usable = [x for x in s["samples"] if x["usable"]]
        size = s["image_size"]
        cells = (corner_cells([x["image_points"] for x in usable], size) if size else
                 [[False] * 3 for _ in range(3)])
        return {
            "active": True,
            "poses": s["plan"].poses,
            "pre_approach_mm": s["plan"].pre_approach_mm,
            "capture_mm": s["plan"].capture_mm,
            "window": {"min_mm": s["window"][0], "max_mm": s["window"][1]},
            "placement": s["placement"],
            "board_thickness_mm": s["board_thickness_mm"],
            "image_size": list(size) if size else None,
            "samples": [{"recoater_mm": x["recoater_mm"], "usable": x["usable"],
                         "corners": x["corners"]} for x in s["samples"]],
            "coverage_cells": cells,
        }

    @app.get("/api/vision/autocal/window")
    def autocal_window() -> dict[str, float]:
        lo, hi = load_window(root)
        return {"min_mm": lo, "max_mm": hi}

    @app.post("/api/vision/autocal/session")
    def autocal_start(body: AutocalSessionBody) -> dict[str, Any]:
        spec = BoardSpec(kind="charuco", squares_x=body.spec.squares_x,
                         squares_y=body.spec.squares_y,
                         square_length_mm=body.spec.square_length_mm,
                         marker_length_mm=body.spec.marker_length_mm,
                         aruco_dict=body.spec.aruco_dict or "DICT_4X4_50")
        try:
            if body.spec.aruco_dict is None:
                spec = with_auto_dict(spec)
            validate_charuco_spec(spec)
        except BoardSpecError as exc:
            raise HTTPException(400, f"invalid board: {exc}") from exc
        capture = float(capture_pose())
        if not capture > 0:
            raise HTTPException(400, "no capture pose saved yet (Settings → Capture pose)")
        if not (math.isfinite(body.board_thickness_mm) and body.board_thickness_mm >= 0):
            raise HTTPException(400, "board thickness must be a number ≥ 0 mm")
        try:
            plan = plan_sweep(capture, body.window_min_mm, body.window_max_mm,
                              step_mm=body.step_mm, max_offset_mm=body.max_offset_mm)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        window = (float(body.window_min_mm), float(body.window_max_mm))
        _window_path(root).write_text(
            json.dumps({"min_mm": window[0], "max_mm": window[1]}), encoding="utf-8")
        state["session"] = {
            "spec": spec, "plan": plan, "window": window, "placement": body.placement,
            "board_thickness_mm": float(body.board_thickness_mm), "samples": [],
            "image_size": None, "result": None, "verdict": None, "self_check": None,
        }
        events("autocal_start", {"poses": plan.poses, "window": list(window)})
        return summary(state["session"])

    @app.get("/api/vision/autocal/session")
    def autocal_status() -> dict[str, Any]:
        s = state["session"]
        return summary(s) if s is not None else {"active": False}

    @app.post("/api/vision/autocal/sample")
    async def autocal_sample(request: Request, recoater_mm: float = Query(...)) -> dict[str, Any]:
        s = session()
        if not math.isfinite(recoater_mm):
            raise HTTPException(400, "recoater position must be a finite number (is it homed?)")
        image, size = await _session_photo(request, s)
        # Every identified point: chessboard corners AND marker corners (the whole board).
        det = detect_board_points(image, s["spec"])
        pts = (np.zeros((0, 2)) if det is None
               else np.asarray(det.image_points, float).reshape(-1, 2))
        n_chess = 0 if det is None else int((det.kinds == "corner").sum())
        usable = det is not None and len(pts) >= MIN_CORNERS
        s["image_size"] = s["image_size"] or size
        s["samples"].append({
            "recoater_mm": float(recoater_mm), "usable": usable, "corners": int(len(pts)),
            "image_points": pts,
            "object_points": None if det is None else np.asarray(det.object_points, float),
            "ids": None if det is None or det.ids is None else np.asarray(det.ids),
        })
        # A new photo invalidates any earlier solve and its self-check.
        s["result"] = s["verdict"] = s["self_check"] = None
        return {
            "usable": usable, "corners": int(len(pts)), "image_size": list(size),
            "chessboard_corners": n_chess, "marker_points": int(len(pts)) - n_chess,
            "corners_px": pts.tolist(), "reason": None if usable else (
                f"board not found or fewer than {MIN_CORNERS} corners"),
            "coverage_cells": summary(s)["coverage_cells"],
        }

    @app.post("/api/vision/autocal/solve")
    def autocal_solve() -> dict[str, Any]:
        s = session()
        views = [AutocalView(x["recoater_mm"], x["image_points"], x["object_points"], x["ids"])
                 for x in s["samples"] if x["usable"]]
        if s["image_size"] is None:
            raise HTTPException(400, "no photos yet")
        try:
            res = solve_autocal(views, capture_recoater_mm=s["plan"].capture_mm,
                                image_size=s["image_size"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        passed, reasons = judge(res)
        s["result"], s["verdict"], s["self_check"] = res, (passed, reasons), None
        out = _finite({
            "passed": passed, "reasons": reasons,
            "reprojection_rms_px": res.reprojection_rms_px, "shift_rms_mm": res.shift_rms_mm,
            "shift_worst_mm": res.shift_worst_mm, "scale_ratio": res.scale_ratio,
            "n_views": res.n_views, "image_size": list(res.image_size),
            "bed_extent_mm": list(res.bed_extent_mm), "mm_per_px": res.mm_per_px,
            "valid_region_mm": [list(p) for p in res.valid_region_mm],
            "placement": s["placement"], "board_thickness_mm": s["board_thickness_mm"],
            "plane_note": PLANE_NOTE,
            "reprojection_rms_mm": res.reprojection_rms_mm, "px_mm": res.px_mm,
            "reprojection_limit_mm": MAX_REPROJ_MM, "residuals": res.residuals,
        })
        # Keep the sweep's points on disk so a failed run can be diagnosed (and re-solved) without
        # repeating the motion; one file, overwritten by the next solve.
        try:
            _sweep_path(root).write_text(json.dumps({
                "saved_at": datetime.now(UTC).isoformat(), "image_size": list(s["image_size"]),
                "capture_mm": s["plan"].capture_mm, "board": dataclasses.asdict(s["spec"]),
                "views": [{"recoater_mm": x["recoater_mm"],
                           "image_points": np.asarray(x["image_points"]).tolist(),
                           "object_points": np.asarray(x["object_points"]).tolist(),
                           "ids": np.asarray(x["ids"]).ravel().tolist()}
                          for x in s["samples"] if x["usable"]],
                "result": out,
            }), encoding="utf-8")
        except OSError:
            pass  # diagnosis only: never fail a solve because the file could not be written
        return out

    @app.post("/api/vision/autocal/selfcheck")
    async def autocal_selfcheck(request: Request) -> dict[str, Any]:
        """Score the PENDING solve on a photo of the board after it was moved or rotated.

        Any recoater position works: pairwise distances are unchanged by a camera translation
        parallel to the plane, and the calibrated area is an area of the photo (the hull of where
        sweep points were seen), so no move back to the capture pose is needed.
        """
        s = session()
        res = s["result"]
        if res is None or not s["verdict"] or not s["verdict"][0]:
            raise HTTPException(409, "solve a passing run before the self-check")
        image, _size = await _session_photo(request, s)
        det = detect_board_points(image, s["spec"])
        views = [] if det is None else [det]

        def to_bed(px: np.ndarray) -> np.ndarray:
            return apply_homography(res.H, undistort_points(px, res.camera_matrix,
                                                            res.dist_coeffs))

        sweep = [x["image_points"] for x in s["samples"] if x["usable"]]
        sc = score_self_check(views, to_bed, res.valid_region_mm, sweep)
        s["self_check"] = sc
        events("autocal_selfcheck", {"passed": sc.passed, "rms_mm": sc.rms_mm,
                                     "n_used": sc.n_used})
        out = sc.to_dict()
        out["corners_px"] = [] if det is None else np.asarray(det.image_points).tolist()
        return _finite(out)

    @app.post("/api/vision/autocal/save")
    def autocal_save() -> dict[str, Any]:
        s = session()
        if s["result"] is None or not s["verdict"] or not s["verdict"][0]:
            raise HTTPException(409, "only a passing run can be saved; solve one first")
        if s["self_check"] is None or not s["self_check"].passed:
            raise HTTPException(409, (
                "run the self-check first: move or rotate the board, take a self-check photo, "
                "and save once it passes"))
        res = s["result"]
        version = datetime.now(UTC).strftime("cal-%Y%m%dT%H%M%SZ")
        provenance = {
            "method": "auto-sweep", "placement": s["placement"],
            "board_thickness_mm": s["board_thickness_mm"], "plane_note": PLANE_NOTE,
            "capture_recoater_mm": s["plan"].capture_mm, "approach": APPROACH_NOTE,
            "window": {"min_mm": s["window"][0], "max_mm": s["window"][1]},
            "board": dataclasses.asdict(s["spec"]), "scale_ratio": res.scale_ratio,
            "shift_rms_mm": res.shift_rms_mm, "shift_worst_mm": res.shift_worst_mm,
            "reprojection_rms_px": res.reprojection_rms_px, "n_views": res.n_views,
            "reprojection_rms_mm": res.reprojection_rms_mm, "px_mm": res.px_mm,
            "valid_region_mm": [list(p) for p in res.valid_region_mm],
            "self_check": _finite(s["self_check"].to_dict()),
        }
        calib = to_calibration(res, version=version, provenance=provenance)
        save_calibration(calibration_path, calib)
        on_saved(calib)
        events("autocal_saved", {"calibration_version": version})
        return {"calibration_version": version}

    @app.post("/api/vision/autocal/cancel")
    def autocal_cancel() -> dict[str, Any]:
        state["session"] = None
        return {"active": False}
