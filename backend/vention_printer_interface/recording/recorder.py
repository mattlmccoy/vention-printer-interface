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


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "run"


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
            (run / "events.json").write_text(json.dumps(self._events, indent=2))
            manifest = {
                "complete": True,
                "sample_count": self._count,
                "duration_s": round(time.time() - self._started, 3),
                "checksums": {
                    n: _sha256(run / n)
                    for n in ("metadata.json", "events.json", "telemetry.csv", "layers.csv")
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
