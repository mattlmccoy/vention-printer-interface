"""A calibration only holds at the image size it was fitted on — never apply it to another size.

Found 2026-10-20 (code trace): on the Windows PC (lightweight camera mode) the Calibrate/Validate
photos come from the <=1920x1080 stream + takePhoto, while print stills are raw full-resolution
frames (e.g. 5120x3840). register_frame applied K/dist/H to every frame regardless of size, so
print stills would have been measured with a calibration fitted at another resolution — and the
Validate step, sharing the calibration photo path, would still have passed (a false green).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tests.test_api_vision import (
    _SESSION_CHARUCO,
    _CheckerSource,
    _render_checker_validate,
    _save_checker_calib,
    _validate_app,
    _warped_charuco_frames,
)
from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.capture import store_uploaded
from vention_printer_interface.vision.registration import (
    Calibration,
    calibration_size_mismatch,
    register_frame,
)


def _calib(size: tuple[int, int] | None) -> Calibration:
    return Calibration(
        H=np.eye(3), mm_per_px=1.0, bed_extent_mm=(0.0, 0.0, 40.0, 30.0), version="cal-size-test",
        reprojection_error=0.0, camera_matrix=np.array([[50.0, 0, 20], [0, 50.0, 15], [0, 0, 1]]),
        dist_coeffs=np.zeros(5), distortion_model="opencv-5", image_size=size,
    )


def _usable(h: int, w: int) -> np.ndarray:
    return np.random.default_rng(0).integers(0, 255, (h, w, 3), dtype=np.uint8)


# ---- the rule --------------------------------------------------------------------------------
def test_matching_size_or_unknown_size_is_not_a_mismatch() -> None:
    assert calibration_size_mismatch(_usable(30, 40), _calib((40, 30))) is None
    assert calibration_size_mismatch(_usable(30, 40), _calib(None)) is None  # legacy calibration


def test_a_different_size_is_a_mismatch_naming_both_sizes() -> None:
    reason = calibration_size_mismatch(_usable(60, 80), _calib((40, 30)))
    assert reason is not None
    assert "80x60" in reason and "40x30" in reason


def test_register_frame_refuses_to_measure_a_frame_of_another_size() -> None:
    img = _usable(60, 80)
    registered, space = register_frame(img, _calib((40, 30)))
    assert space is None  # no bed-plane mm claimed
    assert registered is img


def test_register_frame_still_registers_the_calibrated_size() -> None:
    _, space = register_frame(_usable(30, 40), _calib((40, 30)))
    assert space is not None


# ---- the sidecar tells the truth -------------------------------------------------------------
def _sidecar(run: Path, layer: int) -> dict:
    return json.loads((run / "vision" / f"layer_{layer:04d}" / "post_jet.json").read_text())


def test_a_mismatched_still_is_stored_raw_with_the_reason_in_its_sidecar(tmp_path: Path) -> None:
    store_uploaded(_usable(60, 80), run_dir=tmp_path, calibration=_calib((40, 30)),
                   layer=1, stage="post_jet")
    cal = _sidecar(tmp_path, 1)["calibration"]
    assert cal["applied"] is False
    assert "80x60" in cal["skipped_reason"]
    assert cal["image_size"] == [40, 30]
    assert _sidecar(tmp_path, 1)["registered_space"] is None


def test_a_matching_still_records_the_calibration_as_applied(tmp_path: Path) -> None:
    store_uploaded(_usable(30, 40), run_dir=tmp_path, calibration=_calib((40, 30)),
                   layer=2, stage="post_jet")
    cal = _sidecar(tmp_path, 2)["calibration"]
    assert cal["applied"] is True and cal["skipped_reason"] is None
    assert cal["image_size"] == [40, 30]


# ---- calibration session: one image size per session -----------------------------------------
def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf.tobytes())


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    return create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05,
                      print_min_wait_s=0.1, print_step_timeout_s=5.0)


def test_a_calibration_photo_of_another_size_is_refused(tmp_path: Path) -> None:
    frames = _warped_charuco_frames(2)
    with TestClient(_app(tmp_path)) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        assert c.post("/api/vision/calibrate/capture-upload",
                      content=_png(frames[0])).json()["captured"] is True
        bigger = cv2.resize(frames[1], None, fx=1.5, fy=1.5)
        r = c.post("/api/vision/calibrate/capture-upload", content=_png(bigger)).json()
        assert r["captured"] is False
        assert "size" in r["reason"]
        session = c.get("/api/vision/calibrate/session").json()
        assert session["n_views"] == 1
        h, w = frames[0].shape[:2]
        assert session["image_size"] == [w, h]


def test_finalize_reports_the_image_size_it_was_fitted_on(tmp_path: Path) -> None:
    frames = _warped_charuco_frames(8)
    with TestClient(_app(tmp_path)) as c:
        c.post("/api/vision/calibrate/session", json={"spec": _SESSION_CHARUCO})
        for f in frames:
            c.post("/api/vision/calibrate/capture-upload", content=_png(f))
        r = c.post("/api/vision/calibrate/finalize", json={
            "mm_per_px": 0.5, "bed_extent_mm": [0, 0, 200, 200], "use_last_capture_as_bed": True})
        assert r.status_code == 200, r.text
        h, w = frames[0].shape[:2]
        assert r.json()["image_size"] == [w, h]


# ---- validation must not pass on a photo the calibration doesn't fit --------------------------
_SCALE_Q = {"cols": 6, "rows": 4, "square_size_mm": 20.0, "certified_mm": 20.0}


def test_validation_refuses_a_photo_of_another_size(tmp_path: Path) -> None:
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.0)
    with TestClient(_validate_app(tmp_path, _CheckerSource())) as c:
        bigger = cv2.resize(_render_checker_validate(), None, fx=2.0, fy=2.0)
        r = c.post("/api/vision/validate/scale-upload", params=_SCALE_Q, content=_png(bigger))
        assert r.status_code == 400
        assert "720x560" in r.json()["detail"] and "360x280" in r.json()["detail"]


def test_validation_of_the_calibrated_size_still_scores(tmp_path: Path) -> None:
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.0)
    with TestClient(_validate_app(tmp_path, _CheckerSource())) as c:
        r = c.post("/api/vision/validate/scale-upload", params=_SCALE_Q,
                   content=_png(_render_checker_validate()))
        assert r.status_code == 200, r.text
        assert r.json()["image_size"] == [360, 280]


# ---- status shows which size the loaded calibration is for ------------------------------------
def test_status_reports_the_calibration_image_size(tmp_path: Path) -> None:
    _save_checker_calib(tmp_path / ".vision_calibration.json", k_scale=1.0)
    with TestClient(_validate_app(tmp_path, _CheckerSource())) as c:
        assert c.get("/api/vision/status").json()["calibration_image_size"] == [360, 280]


@pytest.mark.parametrize("size", [None])
def test_status_reports_no_size_without_a_calibration(tmp_path: Path, size: None) -> None:
    with TestClient(_app(tmp_path)) as c:
        assert c.get("/api/vision/status").json()["calibration_image_size"] is size
