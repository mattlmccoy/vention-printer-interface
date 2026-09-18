"""macOS AVFoundation camera identity — the robust, unattended science-capture path (Phase 2).

Two identical ELP cameras share VID/PID, so a cv2 ``VideoCapture(index)`` opens whichever the OS
enumerated first — the wrong-camera bug. macOS gives each *physical* camera a stable
``spcamera_unique-id`` (an AVFoundation uniqueID) via ``system_profiler SPCameraDataType -json``,
independent of enumeration order. Binding the science role to that unique id lets the SERVER grab
from the correct camera even with no browser tab open (the client-side path only works while a tab
is held open).

This module is the PURE identity layer: parse the profiler output and resolve a unique id to the
current AVFoundation capture index. The actual capture (``AVFoundationFrameSource``) sits in
``frame_source`` and is hardware-gated. The profiler's device order matches AVFoundation's device
order (both are CoreMedia-backed), which is what lets a unique id resolve to a capture index; this
correlation must be confirmed once on the two-ELP rig before the path is trusted for real prints.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AvfCamera:
    index: int  # AVFoundation capture index (position in the profiler's ordered list)
    name: str
    unique_id: str


def parse_camera_uids(profiler_json: str) -> list[AvfCamera]:
    """Parse ``system_profiler SPCameraDataType -json`` into ordered (index, name, unique_id).

    Cameras missing a unique id are skipped (they can't be stably bound). Order is preserved and
    is the AVFoundation capture index. Malformed input yields an empty list rather than raising.
    """
    try:
        data = json.loads(profiler_json)
    except (ValueError, TypeError):
        return []
    entries = data.get("SPCameraDataType") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    cams: list[AvfCamera] = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        uid = e.get("spcamera_unique-id")
        if not isinstance(uid, str) or not uid:
            continue
        name = e.get("_name") if isinstance(e.get("_name"), str) else ""
        cams.append(AvfCamera(index=i, name=name or "", unique_id=uid))
    return cams


def resolve_index_for_uid(cameras: list[AvfCamera], unique_id: str) -> int | None:
    """The current AVFoundation index for ``unique_id``, or None when it isn't present."""
    for cam in cameras:
        if cam.unique_id == unique_id:
            return cam.index
    return None


def list_avf_cameras(timeout_s: float = 5.0) -> list[AvfCamera]:
    """Enumerate the Mac's cameras with stable unique ids (empty on non-macOS or any failure)."""
    try:
        out = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return parse_camera_uids(out.stdout)
