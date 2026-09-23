"""Capture storage layout: per-layer directories, lossless WebP + JSON sidecar, run manifest.

Layout under a run's base directory:
    vision/layer_0003/post_jet.webp       # registered (bed-plane) image, lossless WebP
    vision/layer_0003/post_jet.raw.webp   # original unwarped decoded frame, lossless WebP
    vision/layer_0003/post_jet.json       # sidecar metadata (data-model shape below)
    vision/manifest.json                  # append-only list of capture records
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# The sidecar's fixed shape (spec "Data model"). Every leaf defaults to None so a
# caller can supply any subset of `meta` without inventing values for the rest.
_SIDECAR_TEMPLATE: dict[str, Any] = {
    "run_id": None,
    "layer": None,
    "cad_layer": None,
    "stage": None,
    "host_timestamp_ns": None,
    "frame_timestamp_ns": None,
    "stale": None,
    "job": None,
    "axis_positions_mm": None,
    "camera": {
        "role": None,
        "model": None,
        "asin": None,
        "device_id": None,
        "device_index": None,
    },
    "capture": {
        "requested": None,
        "actual": None,
    },
    "controls": {
        "exposure": None,
        "gain": None,
        "white_balance": None,
        "auto_exposure": None,
        "auto_white_balance": None,
    },
    "lens_notes": None,
    "calibration": {
        "version": None,
        "image_size": None,
        "camera_matrix": None,
        "distortion_model": None,
        "distortion_coeffs": None,
        "bed_homography": None,
        "validation": None,
    },
    "images": None,
    "registered_space": None,
    "source": None,  # "server" (cv2 grab) or "client" (browser upload)
    "checksum_sha256": None,
}


def _deep_merge(template: Any, overrides: Any) -> Any:
    """Merge `overrides` onto `template`; missing keys keep the template's (None) default."""
    if not isinstance(template, dict) or not isinstance(overrides, dict):
        return overrides
    merged = dict(template)
    for key, default in template.items():
        if key in overrides:
            merged[key] = _deep_merge(default, overrides[key])
    return merged


def capture_dir(base: Path, layer: int) -> Path:
    """The directory a given layer's captures live under, relative to run `base`."""
    return Path(base) / "vision" / f"layer_{layer:04d}"


def write_capture(
    base: Path,
    layer: int,
    stage: str,
    raw: Any,
    registered: Any,
    meta: dict[str, Any],
) -> dict[str, str]:
    """Write raw + registered images and a data-model-shaped JSON sidecar for one capture.

    `meta` may supply any subset of the sidecar fields; anything missing is filled with
    None rather than invented. `layer`, `stage`, `images`, and `checksum_sha256` are
    always the authoritative, computed values regardless of what `meta` contains.
    """
    import cv2
    import numpy as np

    d = capture_dir(base, layer)
    d.mkdir(parents=True, exist_ok=True)

    # LOSSLESS WebP: pixel-exact (safe for metrology) but far smaller than PNG. In OpenCV a
    # WEBP_QUALITY above 100 selects lossless mode. Per-layer x 3 stages x (raw+registered) x hi-res
    # fills disk fast, so this matters a lot.
    raw_path = d / f"{stage}.raw.webp"
    registered_path = d / f"{stage}.webp"
    sidecar_path = d / f"{stage}.json"

    webp_lossless = [cv2.IMWRITE_WEBP_QUALITY, 101]
    if not cv2.imwrite(str(raw_path), raw, webp_lossless):
        raise RuntimeError(f"failed to write {raw_path} (is OpenCV built with WebP?)")

    # `registered` is a bed-plane warp of `raw`. With no science-cam calibration, register_frame is
    # a passthrough, so registered == raw and writing it again just doubles storage (~36% of all
    # run bytes). Only write a separate registered image when it genuinely differs; otherwise skip
    # it and point `images.registered` at the raw file (same pixels, half the disk).
    distinct = registered is not None and not (
        registered is raw or np.array_equal(np.asarray(raw), np.asarray(registered))
    )
    if distinct:
        if not cv2.imwrite(str(registered_path), registered, webp_lossless):
            raise RuntimeError(f"failed to write {registered_path} (is OpenCV built with WebP?)")
        stored_registered = registered_path
    else:
        registered_path.unlink(missing_ok=True)  # drop any stale duplicate from an earlier write
        stored_registered = raw_path

    checksum = hashlib.sha256(stored_registered.read_bytes()).hexdigest()

    sidecar = _deep_merge(_SIDECAR_TEMPLATE, meta)
    sidecar["layer"] = layer
    sidecar["stage"] = stage
    sidecar["images"] = {"raw": raw_path.name, "registered": stored_registered.name}
    sidecar["checksum_sha256"] = checksum

    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {
        "raw": str(raw_path),
        "registered": str(stored_registered),
        "sidecar": str(sidecar_path),
    }


def write_overview_frame(base: Path, image: Any, quality: int = 70) -> Path:
    """Append one overview timelapse frame to ``<run>/overview/<NNNNNN>.webp`` (time-ordered by a
    zero-padded sequence). Overview frames feed a visual whole-print timelapse, not metrology, so a
    space-saving WebP quality is used (not the lossless 101 of science stills). q70 is tuned
    below the former q85: overview was ~27% of run storage and playback tolerates it."""
    import cv2

    d = Path(base) / "overview"
    d.mkdir(parents=True, exist_ok=True)
    seq = sum(1 for p in d.iterdir() if p.suffix.lower() == ".webp")
    path = d / f"{seq:06d}.webp"
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_WEBP_QUALITY, quality]):
        raise RuntimeError(f"failed to write {path} (is OpenCV built with WebP?)")
    return path


def _manifest_path(base: Path) -> Path:
    return Path(base) / "vision" / "manifest.json"


def read_manifest(base: Path) -> list[dict[str, Any]]:
    """Read the run's capture manifest, or an empty list when none has been written yet."""
    p = _manifest_path(base)
    if not p.exists():
        return []
    records: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
    return records


def append_manifest(base: Path, record: dict[str, Any]) -> None:
    """Append one capture record to the run's manifest."""
    p = _manifest_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    records = read_manifest(base)
    records.append(record)
    p.write_text(json.dumps(records, indent=2), encoding="utf-8")
