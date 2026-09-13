"""Camera configuration, per-OS capture backend, and role identity.

Both finalized cameras (see the spec's "Cameras (finalized 2026-09-13)" section) are ELP
modules on the same Onsemi AR2020 sensor, so they enumerate with near-identical names.
Index/name alone is therefore not a trustworthy role signal (overview vs science) once a
reboot or USB re-enumeration reorders devices -- `resolve_roles` prefers a persisted
`stable_id` (USB path/serial) mapping and only falls back to configured index when no
enumerated device's `stable_id` is known.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# Finalized 2026-09-13 (spec "Cameras (finalized 2026-09-13)").
_OVERVIEW_DEFAULTS: dict[str, Any] = {
    "role": "overview",
    "model": "ELP-U3CAM20MP01-KV100",
    "asin": "B0GMFM4CJV",
    "index": 0,
    "width": 1920,
    "height": 1080,
    "pixel_format": "MJPG",
    "fps": 30.0,
}
_SCIENCE_DEFAULTS: dict[str, Any] = {
    "role": "science",
    "model": "ELP-U3CAM20MP01-IB(5-50B)",
    "asin": "B0GMFN5RTD",
    "index": 1,
    "width": 5120,
    "height": 3840,
    "pixel_format": "YUY2",
    "fps": 7.5,
}


def default_backend() -> int:
    """Map the host OS to its OpenCV capture backend, falling back to `cv2.CAP_ANY`."""
    import cv2

    system = platform.system()
    backend_by_os: dict[str, int] = {
        "Darwin": int(cv2.CAP_AVFOUNDATION),
        "Linux": int(cv2.CAP_V4L2),
        "Windows": int(cv2.CAP_DSHOW),
    }
    return backend_by_os.get(system, int(cv2.CAP_ANY))


@dataclass
class CameraSpec:
    role: str
    model: str
    asin: str
    index: int = 0
    path: str | None = None
    stable_id: str | None = None
    width: int | None = None
    height: int | None = None
    pixel_format: str | None = None
    fps: float | None = None
    backend: int | None = None

    def effective_backend(self) -> int:
        """The backend to open this camera with: explicit `backend`, else the OS default."""
        return self.backend if self.backend is not None else default_backend()


@dataclass
class CameraConfig:
    overview: CameraSpec
    science: CameraSpec

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None = None) -> CameraConfig:
        """Build a `CameraConfig` from `{"overview": {...}, "science": {...}}` overrides.

        Any field omitted from an override dict keeps the finalized ELP-camera default.
        """
        d = d or {}
        overview = CameraSpec(**{**_OVERVIEW_DEFAULTS, **d.get("overview", {})})
        science = CameraSpec(**{**_SCIENCE_DEFAULTS, **d.get("science", {})})
        return cls(overview=overview, science=science)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> CameraConfig:
        """Build a `CameraConfig` from `VPI_VISION_<ROLE>_<FIELD>` environment variables."""
        source = env if env is not None else os.environ
        overrides: dict[str, dict[str, Any]] = {}
        for role in ("overview", "science"):
            prefix = f"VPI_VISION_{role.upper()}_"
            role_overrides: dict[str, Any] = {}
            if f"{prefix}INDEX" in source:
                role_overrides["index"] = int(source[f"{prefix}INDEX"])
            if f"{prefix}PATH" in source:
                role_overrides["path"] = source[f"{prefix}PATH"]
            if f"{prefix}STABLE_ID" in source:
                role_overrides["stable_id"] = source[f"{prefix}STABLE_ID"]
            if role_overrides:
                overrides[role] = role_overrides
        return cls.from_dict(overrides)


def resolve_roles(
    enumerated_devices: list[dict[str, Any]],
    mapping: dict[str, str],
    config: CameraConfig,
) -> dict[str, CameraSpec]:
    """Assign the overview/science `CameraSpec`s to currently enumerated devices.

    For each role, a device whose `stable_id` is mapped (in `mapping`) to that role wins.
    Only when no enumerated device's `stable_id` appears in `mapping` for a role does that
    role fall back to whichever enumerated device has the spec's configured `index`.
    """
    specs = {"overview": config.overview, "science": config.science}
    by_stable_id = {
        device["stable_id"]: device
        for device in enumerated_devices
        if device.get("stable_id") is not None
    }
    by_index = {device["index"]: device for device in enumerated_devices}

    resolved: dict[str, CameraSpec] = {}
    for role, spec in specs.items():
        device = None
        for stable_id, mapped_role in mapping.items():
            if mapped_role == role and stable_id in by_stable_id:
                device = by_stable_id[stable_id]
                break
        if device is None:
            device = by_index.get(spec.index)
        if device is None:
            continue
        resolved[role] = replace(
            spec,
            index=device["index"],
            path=device.get("path", spec.path),
            stable_id=device.get("stable_id", spec.stable_id),
        )
    return resolved


def save_role_map(path: Path, mapping: dict[str, str]) -> None:
    """Persist a `stable_id -> role` mapping as JSON."""
    Path(path).write_text(json.dumps(mapping, indent=2), encoding="utf-8")


def load_role_map(path: Path) -> dict[str, str]:
    """Load a `stable_id -> role` mapping, or `{}` when `path` does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    data: dict[str, str] = json.loads(p.read_text(encoding="utf-8"))
    return data
