"""Persisted backlash-calibration history.

Backlash cal results used to live only in memory, so a restart lost them and you couldn't review a
sweep after the fact. Each completed cal is now written as one JSON record under
``<experiments_root>/.calibrations/`` — survives restarts, listable, and re-plottable/exportable.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def save_backlash(hist_dir: Path | str, result: dict[str, Any]) -> str:
    """Write one completed cal (a ``BacklashResult`` as a dict) as ``backlash_a{axis}_{ts}.json``.
    Returns the record id (filename stem). A same-second second save gets a ``-N`` suffix so it
    never overwrites the first."""
    d = Path(hist_dir)
    d.mkdir(parents=True, exist_ok=True)
    axis = int(result.get("axis", 0))
    stem = f"backlash_a{axis}_{time.strftime('%Y%m%d_%H%M%S')}"
    rid, n = stem, 1
    while (d / f"{rid}.json").exists():
        n += 1
        rid = f"{stem}-{n}"
    record = {
        "id": rid,
        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "axis": axis,
        "recommended_mm": result.get("recommended_mm"),
        "positions": result.get("positions", []),
    }
    (d / f"{rid}.json").write_text(json.dumps(record, indent=2))
    return rid


def list_backlash(hist_dir: Path | str) -> list[dict[str, Any]]:
    """Saved-cal summaries, newest first: id, saved_utc, axis, recommended_mm, n_positions."""
    d = Path(hist_dir)
    try:
        files = sorted(d.glob("backlash_*.json"), key=lambda p: p.name, reverse=True)
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for f in files:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        out.append({
            "id": r.get("id", f.stem), "saved_utc": r.get("saved_utc"), "axis": r.get("axis"),
            "recommended_mm": r.get("recommended_mm"), "n_positions": len(r.get("positions", [])),
        })
    return out


def load_backlash(hist_dir: Path | str, rec_id: str) -> dict[str, Any] | None:
    """Full record for ``rec_id`` or ``None``; ``rec_id`` must be a bare stem (no traversal)."""
    if "/" in rec_id or "\\" in rec_id or ".." in rec_id:
        return None
    try:
        return json.loads((Path(hist_dir) / f"{rec_id}.json").read_text())  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None
