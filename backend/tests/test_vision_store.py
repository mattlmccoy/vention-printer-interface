import hashlib
import json

import numpy as np

from vention_printer_interface.vision.store import (
    append_manifest,
    capture_dir,
    read_manifest,
    write_capture,
)


def test_capture_dir_layout(tmp_path):
    d = capture_dir(tmp_path, 3)
    assert d == tmp_path / "vision" / "layer_0003"


def test_write_capture_lays_out_files(tmp_path):
    raw = np.zeros((8, 8, 3), np.uint8)
    reg = np.zeros((4, 4, 3), np.uint8)
    meta = {"run_id": "r1", "job": {"id": "j1"}}
    paths = write_capture(tmp_path, layer=3, stage="post_jet", raw=raw, registered=reg, meta=meta)

    # Stills are stored as LOSSLESS WebP (much smaller than PNG, pixel-exact for metrology).
    d = capture_dir(tmp_path, 3)
    assert (d / "post_jet.webp").exists()
    assert (d / "post_jet.raw.webp").exists()
    assert paths["registered"].endswith("post_jet.webp")
    assert paths["raw"].endswith("post_jet.raw.webp")
    assert paths["sidecar"].endswith("post_jet.json")


def test_write_capture_is_lossless(tmp_path):
    import cv2

    # A non-trivial image (gradient + noise) so a lossy codec would change pixels.
    rng = np.random.default_rng(0)
    reg = rng.integers(0, 256, size=(64, 96, 3), dtype=np.uint8)
    write_capture(tmp_path, layer=2, stage="post_jet", raw=reg, registered=reg, meta={})
    back = cv2.imread(str(capture_dir(tmp_path, 2) / "post_jet.webp"))
    assert back is not None, "WebP was not written/decoded — is OpenCV built with WebP?"
    assert np.array_equal(back, reg), "WebP capture must be bit-exact (lossless)"


def test_write_capture_sidecar_matches_data_model_shape(tmp_path):
    raw = np.zeros((8, 8, 3), np.uint8)
    reg = np.zeros((4, 4, 3), np.uint8)
    meta = {
        "run_id": "r1",
        "host_timestamp_ns": 111,
        "frame_timestamp_ns": 222,
        "job": {"id": "j1", "name": "n1"},
        "axis_positions_mm": {"build": 0.0, "feed": 0.0},
        "camera": {
            "role": "science",
            "model": "ELP-U3CAM20MP01-IB(5-50B)",
            "asin": "B0GMFN5RTD",
            "device_id": None,
            "device_index": 1,
        },
        "capture": {"requested": {"width": 5120}, "actual": {"width": 5120}},
        "controls": {
            "exposure": None,
            "gain": None,
            "white_balance": None,
            "auto_exposure": None,
            "auto_white_balance": None,
        },
        "lens_notes": "5-50mm varifocal; zoom/focus/iris locked at install",
        "calibration": None,
    }
    d = capture_dir(tmp_path, 3)
    write_capture(tmp_path, layer=3, stage="post_jet", raw=raw, registered=reg, meta=meta)
    sidecar = json.loads((d / "post_jet.json").read_text())

    assert sidecar["run_id"] == "r1"
    assert sidecar["layer"] == 3
    assert sidecar["stage"] == "post_jet"
    assert sidecar["host_timestamp_ns"] == 111
    assert sidecar["frame_timestamp_ns"] == 222
    assert sidecar["job"] == {"id": "j1", "name": "n1"}
    assert sidecar["axis_positions_mm"] == {"build": 0.0, "feed": 0.0}
    assert sidecar["camera"]["role"] == "science"
    assert sidecar["camera"]["device_id"] is None
    assert sidecar["capture"]["requested"] == {"width": 5120}
    assert sidecar["controls"]["exposure"] is None
    assert sidecar["lens_notes"].startswith("5-50mm")
    assert sidecar["calibration"] is None
    assert sidecar["images"] == {"raw": "post_jet.raw.webp", "registered": "post_jet.webp"}
    assert sidecar["registered_space"] is None  # not provided in meta
    expected_checksum = hashlib.sha256((d / "post_jet.webp").read_bytes()).hexdigest()
    assert sidecar["checksum_sha256"] == expected_checksum


def test_write_capture_fills_missing_meta_with_none(tmp_path):
    raw = np.zeros((4, 4, 3), np.uint8)
    reg = np.zeros((4, 4, 3), np.uint8)
    write_capture(tmp_path, layer=1, stage="pre_jet", raw=raw, registered=reg, meta={})
    d = capture_dir(tmp_path, 1)
    sidecar = json.loads((d / "pre_jet.json").read_text())

    assert sidecar["run_id"] is None
    assert sidecar["job"] is None
    assert sidecar["camera"] == {
        "role": None,
        "model": None,
        "asin": None,
        "device_id": None,
        "device_index": None,
    }
    assert sidecar["capture"] == {"requested": None, "actual": None}
    assert sidecar["controls"] == {
        "exposure": None,
        "gain": None,
        "white_balance": None,
        "auto_exposure": None,
        "auto_white_balance": None,
    }
    assert sidecar["calibration"] == {
        "version": None,
        "image_size": None,
        "camera_matrix": None,
        "distortion_model": None,
        "distortion_coeffs": None,
        "bed_homography": None,
        "validation": None,
    }


def test_manifest_round_trip(tmp_path):
    assert read_manifest(tmp_path) == []
    append_manifest(tmp_path, {"layer": 1, "stage": "pre_jet"})
    append_manifest(tmp_path, {"layer": 1, "stage": "post_jet"})
    records = read_manifest(tmp_path)
    assert len(records) == 2
    assert records[0]["stage"] == "pre_jet"
    assert records[1]["stage"] == "post_jet"
