"""The operator's camera ignore list (Settings -> Camera inventory), as pure logic.

The list is keyed by macOS AVFoundation unique ids (``spcamera_unique-id``), which only the SERVER
can see. The browser pickers know a random per-origin ``deviceId`` plus a label, so the one field
both sides share is the camera's NAME. This module stores each ignored camera's name beside its id
and decides which names are safe to hand to the browser: a name is withheld when another camera
that is NOT ignored carries it (two identical ELPs share a label, so hiding by name would hide
both). Server-side filtering uses the ids directly (``drop_ignored_devices``).

File format (``<experiments root>/.vision_ignored_cameras.json``)::

    {"unique_ids": [...], "cameras": {"<uid>": {"name": "...", "shared_name": false}}}

``unique_ids`` stays at the top level so an older operator build still reads the list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vention_printer_interface.vision.avfoundation import AvfCamera

_MACOS_UID_PREFIX = "macos-uid:"


@dataclass(frozen=True)
class IgnoredCamera:
    unique_id: str
    name: str | None  # None until the camera has been seen enumerated once
    shared_name: bool  # another camera had the same name when this name was recorded


def load_ignored(path: Path) -> list[IgnoredCamera]:
    """Read the ignore file; missing/corrupt -> []. Accepts the legacy ids-only format."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    uids = data.get("unique_ids")
    if not isinstance(uids, list):
        return []
    raw_meta = data.get("cameras")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    out: list[IgnoredCamera] = []
    for uid in dict.fromkeys(u for u in uids if isinstance(u, str) and u):
        m: Any = meta.get(uid) if isinstance(meta.get(uid), dict) else {}
        name = m.get("name") if isinstance(m.get("name"), str) and m.get("name") else None
        out.append(IgnoredCamera(uid, name, bool(m.get("shared_name", False))))
    return out


def save_ignored(path: Path, entries: list[IgnoredCamera]) -> None:
    cameras = {
        e.unique_id: {"name": e.name, "shared_name": e.shared_name} for e in entries
    }
    payload = {"unique_ids": [e.unique_id for e in entries], "cameras": cameras}
    path.write_text(json.dumps(payload))


def with_names(
    uids: list[str], cams: list[AvfCamera], previous: list[IgnoredCamera]
) -> list[IgnoredCamera]:
    """One entry per id, named from the current enumeration when the camera is plugged in (and
    flagged ``shared_name`` when ≥2 enumerated cameras carry that name); otherwise the previously
    stored record is kept, so an unplugged camera stays hidden by its last known name."""
    by_uid = {c.unique_id: c for c in cams}
    prev = {e.unique_id: e for e in previous}
    name_counts: dict[str, int] = {}
    for c in cams:
        key = c.name.strip().lower()
        if key:
            name_counts[key] = name_counts.get(key, 0) + 1
    out: list[IgnoredCamera] = []
    for uid in dict.fromkeys(u for u in uids if u):
        cam = by_uid.get(uid)
        if cam is not None and cam.name.strip():
            shared = name_counts.get(cam.name.strip().lower(), 0) >= 2
            out.append(IgnoredCamera(uid, cam.name.strip(), shared))
        else:
            out.append(prev.get(uid, IgnoredCamera(uid, None, False)))
    return out


def exposed_names(entries: list[IgnoredCamera], cams: list[AvfCamera]) -> list[str]:
    """Names the browser may hide by label. Withheld: unnamed entries, names recorded as shared,
    and any name a currently enumerated NON-ignored camera also carries."""
    ignored = {e.unique_id for e in entries}
    kept_names = {c.name.strip().lower() for c in cams if c.unique_id not in ignored}
    out: list[str] = []
    for e in entries:
        if not e.name or e.shared_name or e.name.strip().lower() in kept_names:
            continue
        if e.name not in out:
            out.append(e.name)
    return out


def uid_of_stable_id(stable_id: str | None) -> str | None:
    """The macOS unique id inside a ``macos-uid:<uid>`` stable id (``cameras.py``), else None."""
    if isinstance(stable_id, str) and stable_id.startswith(_MACOS_UID_PREFIX):
        return stable_id[len(_MACOS_UID_PREFIX):] or None
    return None


def drop_ignored_devices(
    devices: list[dict[str, Any]], uids: list[str]
) -> list[dict[str, Any]]:
    """``enumerate_devices`` records minus the ignored cameras (matched by macOS unique id)."""
    ignored = set(uids)
    return [d for d in devices if uid_of_stable_id(d.get("stable_id")) not in ignored]
