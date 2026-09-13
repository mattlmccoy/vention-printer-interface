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
import logging
import os
import platform
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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


def unresolved_roles(
    enumerated_devices: list[dict[str, Any]], mapping: dict[str, str]
) -> list[str]:
    """Roles ("overview"/"science") with no CURRENTLY ENUMERATED device confidently mapped.

    A role counts as resolved only when some enumerated device's `stable_id` is a key in
    `mapping` pointing at that role -- deliberately stricter than `resolve_roles`, whose index
    fallback is a best-effort guess for opening a camera, not operator-confirmed identity. This
    is what drives the quick-start wizard: it must appear whenever the operator has not
    explicitly confirmed roles for the devices plugged in right now (new machine, a camera
    swapped, or a mapped stable_id that isn't currently enumerated).
    """
    known_stable_ids = {
        device["stable_id"] for device in enumerated_devices if device.get("stable_id") is not None
    }
    resolved: set[str] = {
        role for stable_id, role in mapping.items() if stable_id in known_stable_ids
    }
    return sorted(role for role in ("overview", "science") if role not in resolved)


def _stable_id_for_index(index: int) -> str:
    """Best-effort per-OS stable identifier for a probed device index.

    Linux exposes `/dev/v4l/by-id/*` symlinks keyed on USB vendor/product/serial, which
    survive re-enumeration/reboot -- resolved here via `pathlib` only (no new dependency).
    macOS/Windows have no equivalent reachable from the standard library (IOKit/WMI would need
    an extra platform SDK dependency this project does not carry), so they fall back to the
    enumeration index -- NOT stable across reboots/USB reorder, which is exactly why the
    quick-start wizard exists: the operator confirms identity once and the confirmed mapping
    (keyed on whatever stable_id this function returns) is what `unresolved_roles` trusts.
    """
    if platform.system() == "Linux":
        video_dev = Path(f"/dev/video{index}")
        by_id_dir = Path("/dev/v4l/by-id")
        try:
            if video_dev.exists() and by_id_dir.is_dir():
                target = video_dev.resolve()
                for entry in sorted(by_id_dir.iterdir()):
                    if entry.resolve() == target:
                        return f"v4l-by-id:{entry.name}"
        except OSError:
            pass  # best-effort: fall through to the index fallback below
    return f"idx:{index}"


def enumerate_devices(max_index: int = 4) -> list[dict[str, Any]]:
    """Best-effort real camera enumerator: probe a small index range with `cv2.VideoCapture`.

    Returns `{"index", "stable_id", "name"}` per device that opens successfully. Verified on
    hardware, NOT exercised by unit tests (tests inject a fake `device_enumerator` into
    `create_app` instead of calling this). Never raises -- a probe failure at one index is
    skipped, not propagated, so a missing/locked camera can never block startup or a
    `GET /api/vision/devices` request.
    """
    import cv2

    backend = default_backend()
    devices: list[dict[str, Any]] = []
    for index in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                continue
            devices.append(
                {"index": index, "stable_id": _stable_id_for_index(index), "name": None}
            )
        except Exception as exc:  # noqa: BLE001 - a probe failure must never crash enumeration
            log.warning("camera probe failed at index %d: %s", index, exc)
        finally:
            if cap is not None:
                cap.release()
    return devices


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
