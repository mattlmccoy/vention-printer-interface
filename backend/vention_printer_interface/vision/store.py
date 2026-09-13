"""Capture storage layout: per-layer directories, PNG + JSON sidecar, run manifest.

Layout under a run's base directory:
    vision/layer_0003/post_jet.png        # registered (bed-plane) image
    vision/layer_0003/post_jet.raw.png    # original unwarped decoded frame
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
    "stage": None,
    "host_timestamp_ns": None,
    "frame_timestamp_ns": None,
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

    d = capture_dir(base, layer)
    d.mkdir(parents=True, exist_ok=True)

    raw_path = d / f"{stage}.raw.png"
    registered_path = d / f"{stage}.png"
    sidecar_path = d / f"{stage}.json"

    cv2.imwrite(str(raw_path), raw)
    cv2.imwrite(str(registered_path), registered)

    checksum = hashlib.sha256(registered_path.read_bytes()).hexdigest()

    sidecar = _deep_merge(_SIDECAR_TEMPLATE, meta)
    sidecar["layer"] = layer
    sidecar["stage"] = stage
    sidecar["images"] = {"raw": raw_path.name, "registered": registered_path.name}
    sidecar["checksum_sha256"] = checksum

    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {
        "raw": str(raw_path),
        "registered": str(registered_path),
        "sidecar": str(sidecar_path),
    }


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
