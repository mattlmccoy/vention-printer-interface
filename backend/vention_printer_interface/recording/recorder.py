"""Run recorder (spec §4). Mirrors the FLIR/T&C integrity model.

experiments/<YYYYMMDD_HHMMSS>_<slug>/ : metadata.json at start; telemetry.csv streamed and
flushed per row; events.json + manifest.json (sha256 checksums, complete=true) ONLY on clean
stop. A missing manifest.json marks a crashed or incomplete run.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vention_printer_interface import __version__

FORMAT_VERSION = 1
TELEMETRY_FIELDS = [
    "host_timestamp_ns",
    "controller_state",
    "armed",
    "pos_1",
    "pos_2",
    "pos_3",
    "pos_4",
    "complete_1",
    "complete_2",
    "complete_3",
    "complete_4",
    "estop_triggered",
    "drives_ready",
    "health_ok",
    "heater_on",
    "heater_on_s",
]
LAYER_FIELDS = ["host_timestamp_ns", "layer", "phase", "part_height_mm", "elapsed_s"]

# Axes match telemetry.csv's pos_1..pos_4 naming (spec §4 drive order).
MOTION_AXES = (1, 2, 3, 4)
MOTION_PROFILE_FIELDS = (
    ["host_timestamp_ns"]
    + [f"pos_{a}" for a in MOTION_AXES]
    + [f"vel_{a}" for a in MOTION_AXES]
    + [f"accel_{a}" for a in MOTION_AXES]
)


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "run"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def motion_profile_rows(
    telemetry_rows: list[dict[str, Any]],
) -> list[list[Any]]:
    """Derive per-axis pos/vel/accel rows from streamed telemetry rows.

    Velocity is the finite difference Δposition/Δt (mm/s) using the row ``host_timestamp_ns``
    timestamps; acceleration is Δvelocity/Δt. The first telemetry row is dropped (a finite
    difference needs a prior row), so N telemetry rows yield N-1 motion rows. A cell is left
    blank (``None``) when it cannot be computed (missing position, non-increasing timestamps,
    or no prior velocity for acceleration) -- unknown must never render as a real 0.0.
    """
    out: list[list[Any]] = []
    prev_ts: float | None = None
    prev_pos: dict[int, float | None] = dict.fromkeys(MOTION_AXES, None)
    prev_vel: dict[int, float | None] = dict.fromkeys(MOTION_AXES, None)
    for row in telemetry_rows:
        ts = _to_float(row.get("host_timestamp_ns"))
        pos = {a: _to_float(row.get(f"pos_{a}")) for a in MOTION_AXES}
        if prev_ts is None or ts is None:
            prev_ts, prev_pos = ts, pos
            continue
        dt = (ts - prev_ts) / 1e9
        vel: dict[int, float | None] = {}
        accel: dict[int, float | None] = {}
        for a in MOTION_AXES:
            p, pp = pos[a], prev_pos[a]
            vel[a] = (p - pp) / dt if dt > 0 and p is not None and pp is not None else None
            pv = prev_vel[a]
            v = vel[a]
            accel[a] = (v - pv) / dt if dt > 0 and v is not None and pv is not None else None
        out.append(
            [row.get("host_timestamp_ns")]
            + [pos[a] for a in MOTION_AXES]
            + [vel[a] for a in MOTION_AXES]
            + [accel[a] for a in MOTION_AXES]
        )
        prev_ts, prev_pos, prev_vel = ts, pos, vel
    return out


def _write_motion_profiles(run: Path) -> None:
    """Read the just-closed telemetry.csv and write the derived motion_profiles.csv beside it."""
    telemetry = run / "telemetry.csv"
    rows: list[dict[str, Any]] = []
    if telemetry.exists():
        with telemetry.open(newline="") as f:
            rows = list(csv.DictReader(f))
    with (run / "motion_profiles.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(MOTION_PROFILE_FIELDS)
        for row in motion_profile_rows(rows):
            writer.writerow(["" if v is None else v for v in row])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.active: Path | None = None
        self._csv: Any = None
        self._file: Any = None
        self._layers_csv: Any = None
        self._layers_file: Any = None
        self._events: list[dict[str, Any]] = []
        self._count = 0
        self._started = 0.0
        self._lock = threading.Lock()

    def start(self, name: str, *, notes: str = "", metadata: dict[str, Any] | None = None) -> Path:
        with self._lock:
            if self.active is not None:
                raise RuntimeError("already recording")
            self.root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            base = f"{stamp}_{_slug(name)}"
            run, n = self.root / base, 2
            while run.exists():
                run, n = self.root / f"{base}_{n}", n + 1
            run.mkdir()
            meta = {
                "format_version": FORMAT_VERSION,
                "started_utc": datetime.now(UTC).isoformat(),
                "experiment": {"name": name, "notes": notes, **(metadata or {})},
                "software": {
                    "name": "vention-printer-interface",
                    "version": __version__,
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
            }
            (run / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
            self._file = (run / "telemetry.csv").open("w", newline="")
            self._csv = csv.writer(self._file)
            self._csv.writerow(TELEMETRY_FIELDS)
            self._file.flush()
            self._layers_file = (run / "layers.csv").open("w", newline="")
            self._layers_csv = csv.writer(self._layers_file)
            self._layers_csv.writerow(LAYER_FIELDS)
            self._layers_file.flush()
            self._events, self._count, self._started = [], 0, time.time()
            self.active = run
        self.event("recording_started", {"name": name})
        return run

    @property
    def current_run_dir(self) -> Path | None:
        """The active run directory (already created in ``start()``), or ``None`` when idle.

        Lets co-located artifacts (e.g. vision captures) write under the same run without
        duplicating the run-naming/collision logic in ``start()``.
        """
        return self.active

    def record(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            if self.active is None or not snapshot.get("telemetry"):
                return
            t = snapshot["telemetry"]
            pos, comp = t["positions"], t["motion_complete"]
            self._csv.writerow(
                [
                    t["host_timestamp_ns"],
                    snapshot["state"],
                    snapshot["armed"],
                    pos.get("1"),
                    pos.get("2"),
                    pos.get("3"),
                    pos.get("4"),
                    comp.get("1"),
                    comp.get("2"),
                    comp.get("3"),
                    comp.get("4"),
                    t["estop_triggered"],
                    t["drives_ready"],
                    t["health_ok"],
                    t["heater_on"],
                    snapshot.get("heater", {}).get("on_s", 0),
                ]
            )
            self._file.flush()
            self._count += 1

    def record_layer(self, data: dict[str, Any]) -> None:
        with self._lock:
            if self.active is None:
                return
            self._layers_csv.writerow(
                [
                    time.time_ns(),
                    data.get("layer"),
                    data.get("phase"),
                    data.get("part_height_mm"),
                    data.get("elapsed_s"),
                ]
            )
            self._layers_file.flush()

    def event(self, label: str, data: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self.active is None:
                return
            self._events.append(
                {"host_timestamp_ns": time.time_ns(), "label": label, "data": data or {}}
            )

    def stop(self) -> Path | None:
        self.event("recording_stopped", {})
        with self._lock:
            run = self.active
            if run is None:
                return None
            self._file.close()
            self._layers_file.close()
            # Derive motion_profiles.csv from the streamed telemetry now that it is flushed/closed.
            _write_motion_profiles(run)
            (run / "events.json").write_text(json.dumps(self._events, indent=2))
            manifest = {
                "complete": True,
                "sample_count": self._count,
                "duration_s": round(time.time() - self._started, 3),
                "checksums": {
                    n: _sha256(run / n)
                    for n in (
                        "metadata.json",
                        "events.json",
                        "telemetry.csv",
                        "layers.csv",
                        "motion_profiles.csv",
                    )
                },
            }
            (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
            self.active, self._csv, self._file = None, None, None
            self._layers_csv, self._layers_file = None, None
            return run

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        out = []
        dirs = sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))
        for d in dirs:
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            out.append(
                {"run": d.name, "complete": (d / "manifest.json").exists(), "size_bytes": size}
            )
        return out
