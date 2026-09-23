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
import re
import subprocess
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
    exposure: float | None = None
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

    Two roles are never assigned the SAME enumerated device (I-2): when both an
    explicit-stable_id match and an index-fallback match land on one device, the explicit
    match wins and the index-fallback role is dropped back to unresolved -- auto-open must
    never open two `VideoCapture`s on one physical camera. See `unresolved_roles` for the
    stricter, operator-confirmation-only notion of "resolved" that drives the quick-start UI.
    """
    specs = {"overview": config.overview, "science": config.science}
    # A built-in (FaceTime) or Continuity (iPhone) camera is never a role candidate — it must not be
    # shown OR auto-assigned. Devices with no `assignable` key (older callers / test fixtures)
    # default to assignable so existing behavior is unchanged.
    candidates = [d for d in enumerated_devices if d.get("assignable", True)]
    by_stable_id = {
        device["stable_id"]: device
        for device in candidates
        if device.get("stable_id") is not None
    }
    by_index = {device["index"]: device for device in candidates}
    # How many enumerated devices share each vid_pid. When ≥2 cameras are the SAME model, an index
    # guess cannot tell them apart, so the unconfirmed index fallback below must refuse to bind one.
    vid_pid_counts: dict[str, int] = {}
    for dev in candidates:
        vp = dev.get("vid_pid")
        if vp:
            vid_pid_counts[vp] = vid_pid_counts.get(vp, 0) + 1

    resolved: dict[str, CameraSpec] = {}
    resolved_explicitly: dict[str, bool] = {}
    device_index_by_role: dict[str, int] = {}
    for role, spec in specs.items():
        device: dict[str, Any] | None = None
        matched_explicitly = False
        for stable_id, mapped_role in mapping.items():
            if mapped_role == role and stable_id in by_stable_id:
                device = by_stable_id[stable_id]
                matched_explicitly = True
                break
        if device is None:
            # Unconfirmed index fallback (best-effort for a fresh single-camera machine). Refuse it
            # when the device at that index is one of ≥2 identical-model cameras: an index guess
            # among identical cameras can silently open the WRONG physical one (2026-09-16 —
            # identical ELP U3 cameras / an iPhone stealing index 0). Leave the role unresolved so
            # the operator confirms it in the wizard instead.
            candidate: dict[str, Any] | None = by_index.get(spec.index)
            if candidate is not None and vid_pid_counts.get(candidate.get("vid_pid") or "", 0) >= 2:
                candidate = None
            device = candidate
        if device is None:
            continue
        resolved[role] = replace(
            spec,
            index=device["index"],
            path=device.get("path", spec.path),
            stable_id=device.get("stable_id", spec.stable_id),
        )
        resolved_explicitly[role] = matched_explicitly
        device_index_by_role[role] = int(device["index"])

    roles_by_device_index: dict[int, list[str]] = {}
    for role, index in device_index_by_role.items():
        roles_by_device_index.setdefault(index, []).append(role)
    for roles in roles_by_device_index.values():
        if len(roles) < 2:
            continue
        explicit_roles = [role for role in roles if resolved_explicitly[role]]
        # Keep every explicitly-mapped role (there can be at most one per device, since a
        # stable_id maps to a single role); with no explicit match at all, keep just the
        # first role so at most one still claims this device.
        keep = set(explicit_roles) if explicit_roles else {roles[0]}
        for role in roles:
            if role not in keep:
                del resolved[role]

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
        device["stable_id"]
        for device in enumerated_devices
        if device.get("stable_id") is not None and device.get("assignable", True)
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


def _parse_macos_cameras(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse `system_profiler SPCameraDataType -json` output into device records.

    Pure (no I/O) so it is unit-testable against captured real output. Each camera becomes
    `{"index", "stable_id", "name", "has_frame": None, "probed": False}` — identity ONLY, no
    frame probe (the camera is never opened, so its light never comes on). `index` is the
    enumeration order (assumed to match AVFoundation's `cv2.VideoCapture` index; the operator
    confirms the role mapping in the quick-start wizard). `stable_id` prefers the USB
    unique/model id (survives reboot/USB reorder) over the bare index.
    """
    cams = data.get("SPCameraDataType") or []
    out: list[dict[str, Any]] = []
    for index, cam in enumerate(cams):
        if not isinstance(cam, dict):
            continue
        name = cam.get("_name")
        uid = cam.get("spcamera_unique-id") or cam.get("spcamera_model-id")
        stable_id = f"macos-uid:{uid}" if uid else f"idx:{index}"
        model_id = cam.get("spcamera_model-id")
        out.append({"index": index, "stable_id": stable_id, "name": name,
                    "vid_pid": _macos_vid_pid(model_id),
                    "assignable": _is_assignable_camera(model_id),
                    "has_frame": None, "probed": False})
    return out


def _macos_vid_pid(model_id: str | None) -> str | None:
    """`VendorID:ProductID` from a macOS UVC model-id, else None. A generic UVC camera reports
    `"UVC Camera VendorID_13028 ProductID_8224"`; built-in (FaceTime) and Continuity (iPhone)
    cameras have no VendorID, so they return None and never trip the identical-model guard. This is
    the signal `resolve_roles` uses to detect two SAME-model cameras and refuse an index guess."""
    if not model_id:
        return None
    m = re.search(r"VendorID_(\d+)\s+ProductID_(\d+)", model_id)
    return f"{m.group(1)}:{m.group(2)}" if m else None


def _is_assignable_camera(model_id: str | None) -> bool:
    """True only for a real external USB camera we can assign to a role. The built-in FaceTime and
    an iPhone Continuity camera must NOT be shown or auto-assigned (operator directive). macOS gives
    a real USB camera a USB `spcamera_model-id` — `"UVC Camera VendorID_… ProductID_…"` or a hex
    `"0x…"`; the built-in has a descriptive name (`"FaceTime HD Camera"`) and a Continuity camera
    has no model-id at all, so both are filtered out here."""
    if not model_id:
        return False
    return model_id.startswith("0x") or "VendorID_" in model_id


# Windows: UVC webcams register under PnP class "Camera" (Win10 1709+) or, on older drivers, "Image"
# — which scanners and printers also use, so those are dropped by name.
_WIN_CAMERA_CLASSES = ("Camera", "Image")
_WIN_NOT_A_CAMERA = re.compile(r"scan|printer|fax|\bmfp\b", re.IGNORECASE)
_WIN_BUILTIN = re.compile(r"integrated|built-?in|internal", re.IGNORECASE)
_WIN_VID_PID = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")
_WIN_CAMERA_QUERY = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'Camera' -or "
    "$_.PNPClass -eq 'Image' } | Select-Object Name,PNPDeviceID,PNPClass,Status | "
    "ConvertTo-Json -Compress"
)


def _windows_vid_pid(pnp_device_id: Any) -> str | None:
    """``VendorID:ProductID`` in DECIMAL from a PnP id like ``USB\\VID_32E4&PID_2020&MI_00\\…`` —
    decimal to match the macOS form (``VendorID_13028``) so the identical-model guard compares the
    same value on either OS. None when there is no USB VID/PID (not a USB camera)."""
    if not isinstance(pnp_device_id, str):
        return None
    m = _WIN_VID_PID.search(pnp_device_id)
    return f"{int(m.group(1), 16)}:{int(m.group(2), 16)}" if m else None


def _parse_windows_cameras(data: Any) -> list[dict[str, Any]]:
    """Parse ``Get-CimInstance Win32_PnPEntity`` JSON (Camera/Image class) into device records.

    Pure (no I/O). Accepts a list or the bare object PowerShell emits for a single match. Identity
    ONLY — no camera is opened (no light, and no fight with a browser holding the camera). The PnP
    instance path is the stable id: it survives reboots and tells two identical ELPs apart. `index`
    is enumeration order, ASSUMED to match DirectShow's `cv2.VideoCapture` index (unverified; the
    operator confirms roles in the quick-start wizard, exactly as on macOS).
    """
    records = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict) or rec.get("PNPClass") not in _WIN_CAMERA_CLASSES:
            continue
        raw_name = rec.get("Name")
        name = raw_name if isinstance(raw_name, str) and raw_name.strip() else None
        if name and _WIN_NOT_A_CAMERA.search(name):
            continue  # an Image-class scanner/printer, not a camera
        index = len(out)
        pnp = rec.get("PNPDeviceID")
        vid_pid = _windows_vid_pid(pnp)
        builtin = bool(name and _WIN_BUILTIN.search(name))
        stable_id = f"win-pnp:{pnp}" if isinstance(pnp, str) and pnp else f"idx:{index}"
        out.append({"index": index,
                    "stable_id": stable_id,
                    "name": name, "vid_pid": vid_pid,
                    "assignable": vid_pid is not None and not builtin,
                    "status": rec.get("Status"),
                    "has_frame": None, "probed": False})
    return out


def _metadata_devices() -> list[dict[str, Any]]:
    """Identify cameras from OS metadata WITHOUT opening them (so no camera activates/lights up).

    macOS: `system_profiler SPCameraDataType -json`. Linux: `/sys/class/video4linux/video*/name`
    plus `/dev/v4l/by-id` for a stable id. Windows: PowerShell `Get-CimInstance Win32_PnPEntity`
    (Camera/Image class) for names + PnP instance ids. Returns [] on any other OS or on failure
    (caller then falls back to the cv2 probe). Never raises.
    """
    system = platform.system()
    try:
        if system == "Windows":
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WIN_CAMERA_QUERY],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no console flash
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return []
            return _parse_windows_cameras(json.loads(proc.stdout))
        if system == "Darwin":
            proc = subprocess.run(
                ["system_profiler", "SPCameraDataType", "-json"],
                capture_output=True, text=True, timeout=8, check=False,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return []
            return _parse_macos_cameras(json.loads(proc.stdout))
        if system == "Linux":
            devs: list[dict[str, Any]] = []
            base = Path("/sys/class/video4linux")
            if base.is_dir():
                for node in sorted(base.iterdir(), key=lambda p: p.name):
                    if not node.name.startswith("video"):
                        continue
                    try:
                        index = int(node.name.removeprefix("video"))
                    except ValueError:
                        continue
                    name = None
                    try:
                        name = (node / "name").read_text(encoding="utf-8").strip() or None
                    except OSError:
                        pass
                    devs.append({"index": index, "stable_id": _stable_id_for_index(index),
                                 "name": name, "has_frame": None, "probed": False})
            return devs
    except Exception as exc:  # noqa: BLE001 - identification must never crash enumeration
        log.warning("metadata camera enumeration failed: %s", exc)
    return []


def enumerate_devices(max_index: int = 4, probe: bool = False) -> list[dict[str, Any]]:
    """Enumerate cameras. By default IDENTIFIES devices from OS metadata WITHOUT opening any
    camera (`_metadata_devices` — no camera light), returning `{"index","stable_id","name",
    "has_frame":None,"probed":False}`. This is what the quick-start/identify step needs: list USB
    cameras by name for role assignment without turning them all on.

    Falls back to a `cv2.VideoCapture` index probe when metadata yields nothing, or when
    `probe=True` (an explicit access/permission check): the probe opens each index and does a
    one-shot `read()`, setting `has_frame` (macOS reports `isOpened()==True` but `read()` fails
    when Privacy & Security hasn't authorized the camera → `has_frame=False`). Never raises.
    """
    if not probe:
        meta = _metadata_devices()
        if meta:
            return meta

    import cv2

    backend = default_backend()
    devices: list[dict[str, Any]] = []
    for index in range(max_index):
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                continue
            has_frame = False
            try:
                ok, frame = cap.read()
                has_frame = bool(ok) and frame is not None
            except Exception as exc:  # noqa: BLE001 - a read failure must never crash enumeration
                log.warning("camera frame probe failed at index %d: %s", index, exc)
            devices.append(
                {
                    "index": index,
                    "stable_id": _stable_id_for_index(index),
                    "name": None,
                    "has_frame": has_frame,
                    "probed": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - a probe failure must never crash enumeration
            log.warning("camera probe failed at index %d: %s", index, exc)
        finally:
            if cap is not None:
                cap.release()
    return devices


def camera_access_state(devices: list[dict[str, Any]]) -> str:
    """Overall camera-permission signal aggregated from enumerated devices' `has_frame` flags.

    - `"no_devices"`: nothing was enumerated at all (nothing plugged in, or the probe found
      nothing).
    - `"denied"`: one or more devices enumerated (opened) but NONE yielded a frame -- the
      macOS "camera plugged in, permission not granted" signature (see `enumerate_devices`). A
      device missing the `has_frame` key entirely (an enumerator not yet upgraded to report it)
      counts as no-frame here too -- unknown must never render as verified-good.
    - `"ok"`: at least one enumerated device yielded a frame.
    """
    if not devices:
        return "no_devices"
    if any(bool(device.get("has_frame")) for device in devices):
        return "ok"
    # Devices were IDENTIFIED from metadata but never opened (no frame probe) -> access is unknown,
    # not denied. Only a real probe (probed=True) that yielded no frame is the "denied" signature.
    if all(device.get("has_frame") is None and not device.get("probed") for device in devices):
        return "unknown"
    return "denied"


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


def save_camera_settings(path: Path, overrides: dict[str, dict[str, Any]]) -> None:
    """Persist per-role `CameraSpec`-field overrides (e.g. width/height/pixel_format/fps/exposure).

    Stored in `CameraSpec`-field form so `CameraConfig.from_dict` can merge them directly on top
    of the finalized ELP-camera defaults the next time a camera config is built.
    """
    Path(path).write_text(json.dumps(overrides, indent=2), encoding="utf-8")


def load_camera_settings(path: Path) -> dict[str, dict[str, Any]]:
    """Load per-role camera-setting overrides, or `{}` when `path` does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    data: dict[str, dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
    return data
