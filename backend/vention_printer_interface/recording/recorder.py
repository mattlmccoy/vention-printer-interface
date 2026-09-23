"""Run recorder (spec §4). Mirrors the FLIR/T&C integrity model.

experiments/<YYYYMMDD_HHMMSS>_<slug>/ : metadata.json at start; telemetry.csv streamed and
flushed per row; events.json + manifest.json (sha256 checksums, complete=true) ONLY on clean
stop. A missing manifest.json marks a crashed or incomplete run.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import platform
import re
import statistics
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vention_printer_interface import __version__

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
TELEMETRY_FIELDS = [
    "host_timestamp_ns",
    "controller_state",
    "armed",
    "pos_1",
    "pos_2",
    "pos_3",
    "pos_4",
    "vspeed_1",
    "vspeed_2",
    "vspeed_3",
    "vspeed_4",
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

    Velocity prefers the controller's NATIVE measured speed (``vspeed_<axis>``, mm/s) when present;
    otherwise it falls back to the finite difference Δposition/Δt. Acceleration is always
    Δvelocity/Δt. The first telemetry row is dropped (a finite difference needs a prior row), so N
    telemetry rows yield N-1 motion rows. A cell is left blank (``None``) when it cannot be computed
    (missing data, non-increasing timestamps, no prior velocity) -- unknown never renders as 0.0.
    """
    out: list[list[Any]] = []
    prev_ts: float | None = None
    prev_pos: dict[int, float | None] = dict.fromkeys(MOTION_AXES, None)
    prev_vel: dict[int, float | None] = dict.fromkeys(MOTION_AXES, None)
    for row in telemetry_rows:
        ts = _to_float(row.get("host_timestamp_ns"))
        pos = {a: _to_float(row.get(f"pos_{a}")) for a in MOTION_AXES}
        native = {a: _to_float(row.get(f"vspeed_{a}")) for a in MOTION_AXES}
        if prev_ts is None or ts is None:
            prev_ts, prev_pos = ts, pos
            continue
        dt = (ts - prev_ts) / 1e9
        vel: dict[int, float | None] = {}
        accel: dict[int, float | None] = {}
        for a in MOTION_AXES:
            p, pp = pos[a], prev_pos[a]
            derived = (p - pp) / dt if dt > 0 and p is not None and pp is not None else None
            vel[a] = native[a] if native[a] is not None else derived  # native speed wins
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


LAYER_ACCURACY_FIELDS = [
    "layer",
    "phase",
    "commanded_mm",
    "actual_mm",
    "deviation_mm",
    "commanded_cum_mm",
    "actual_cum_mm",
]
# Phases where the build piston actually drops one layer (so accuracy is meaningful). Postcoat and
# setup hold the part fixed. Mirrors control.print_settings._PART_DROP_PHASES without importing it.
_PART_DROP_PHASES = ("thin_precoat", "printing")


def layer_accuracy_rows(
    telemetry_rows: list[dict[str, Any]],
    layer_rows: list[dict[str, Any]],
    part_axis: int = 1,
    layer_start_ts: dict[int, float] | None = None,
    jumped: bool = False,
) -> list[dict[str, Any]]:
    """Per-layer build-piston height accuracy: commanded layer thickness vs the ACTUAL settled
    build-piston displacement.

    Commanded comes from consecutive ``layers.csv`` ``part_height_mm`` deltas. Actual comes from the
    build-piston position (``pos_<part_axis>`` in telemetry): the piston descends (position rises)
    as the part grows, so its displacement from the first (primed) sample tracks the commanded
    cumulative height. For each layer we take the LAST telemetry sample within that layer's window
    (``[layer_ts, next_layer_ts)``) as the settled position. ``actual_mm``/``deviation_mm`` are
    ``None`` when no telemetry falls in a layer's window -- unknown must never render as a real 0.
    """
    samples = sorted(
        (
            (ts, pos)
            for row in telemetry_rows
            if (ts := _to_float(row.get("host_timestamp_ns"))) is not None
            and (pos := _to_float(row.get(f"pos_{part_axis}"))) is not None
        ),
        key=lambda x: x[0],
    )
    baseline = samples[0][1] if samples else None
    base_ts = samples[0][0] if samples else None  # print start, before layer 1's drop
    ordered = sorted(layer_rows, key=lambda r: _to_float(r.get("host_timestamp_ns")) or 0.0)
    # layers.csv timestamps are the layer_COMPLETED events (app.py records on "layer_completed"),
    # so a layer's settled build position is the LAST telemetry sample at/just before its own
    # completion — in (previous completion, this completion]. This attributes the right height to
    # each layer (no off-by-one) and excludes the finish move, which runs AFTER the last completion.
    completions = [_to_float(r.get("host_timestamp_ns")) for r in ordered]

    def _int(v: Any) -> int | None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def settled_pos(i: int) -> float | None:
        # Preferred: the piston position at the NEXT layer's start — a consistent settled phase
        # (piston at rest, before that layer's drop), unaffected by this run's pre-heater drop/raise
        # swing that makes the layer_completed instant a moving target. Falls back to the completion
        # window when no next-start timestamp is available (e.g. the last layer, or no events).
        if layer_start_ts and i + 1 < len(ordered):
            nxt = layer_start_ts.get(_int(ordered[i + 1].get("layer")))  # type: ignore[arg-type]
            if nxt is not None:
                before = [p for ts, p in samples if ts <= nxt]
                if before:
                    return before[-1]
        hi = completions[i]
        lo = completions[i - 1] if i > 0 else base_ts
        if hi is None:
            return None
        window = [p for ts, p in samples if (lo is None or ts > lo) and ts <= hi]
        return window[-1] if window else None

    out: list[dict[str, Any]] = []
    prev_cmd_cum = 0.0
    prev_actual_cum: float | None = 0.0  # baseline maps to cumulative 0
    for i, row in enumerate(ordered):
        cmd_cum = _to_float(row.get("part_height_mm"))
        pos = settled_pos(i)
        actual_cum = (pos - baseline) if (pos is not None and baseline is not None) else None
        cmd = (cmd_cum - prev_cmd_cum) if cmd_cum is not None else None
        actual = (
            (actual_cum - prev_actual_cum)
            if (actual_cum is not None and prev_actual_cum is not None)
            else None
        )
        dev = (actual - cmd) if (actual is not None and cmd is not None) else None
        if jumped and i == 0:
            # Jumped-to first layer: no recorded prior layer to difference against, so the per-layer
            # increment is UNKNOWN — never the (prev_cum=0) false delta. Cumulative is kept, and
            # later layers difference against this row normally.
            cmd = actual = dev = None
        out.append(
            {
                "layer": row.get("layer"),
                "phase": row.get("phase"),
                "commanded_mm": cmd,
                "actual_mm": actual,
                "deviation_mm": dev,
                "commanded_cum_mm": cmd_cum,
                "actual_cum_mm": actual_cum,
            }
        )
        if cmd_cum is not None:
            prev_cmd_cum = cmd_cum
        if actual_cum is not None:
            prev_actual_cum = actual_cum
    return out


def layer_accuracy_summary(
    rows: list[dict[str, Any]], phases: tuple[str, ...] = _PART_DROP_PHASES
) -> dict[str, Any]:
    """Deviation statistics over part-drop layers with a known deviation (build-piston accuracy)."""
    devs = [
        r["deviation_mm"]
        for r in rows
        if r.get("phase") in phases and r.get("deviation_mm") is not None
    ]
    if not devs:
        return {"n": 0, "mean_abs_dev_mm": None, "max_abs_dev_mm": None, "std_dev_mm": None}
    abs_devs = [abs(d) for d in devs]
    return {
        "n": len(devs),
        "mean_abs_dev_mm": statistics.fmean(abs_devs),
        "max_abs_dev_mm": max(abs_devs),
        "std_dev_mm": statistics.pstdev(devs) if len(devs) > 1 else 0.0,
    }


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _layer_start_timestamps(run: Path) -> dict[int, float]:
    """Map layer number -> its layer_started host timestamp, from events.json. Used to sample each
    layer's SETTLED build-piston height at a consistent phase (the next layer's start)."""
    out: dict[int, float] = {}
    try:
        events = json.loads((run / "events.json").read_text())
    except (OSError, ValueError):
        return out
    for e in events if isinstance(events, list) else []:
        if e.get("label") == "layer_started":
            layer = e.get("data", {}).get("layer")
            ts = e.get("host_timestamp_ns")
            if isinstance(layer, int) and ts is not None:
                out[layer] = float(ts)
    return out


def _run_was_jumped(run: Path) -> bool:
    """True if a timeline seek/jump happened during this run (a "print_seeked" event). A jumped run
    starts mid-print, so its first executed layer's per-layer accuracy has no valid baseline."""
    try:
        events = json.loads((run / "events.json").read_text())
    except (OSError, ValueError):
        return False
    return any(e.get("label") == "print_seeked" for e in events if isinstance(events, list))


def _write_layer_accuracy(run: Path) -> None:
    """Write layer_accuracy.csv from the just-closed telemetry.csv + layers.csv (build-piston)."""
    rows = layer_accuracy_rows(
        _read_csv_rows(run / "telemetry.csv"),
        _read_csv_rows(run / "layers.csv"),
        layer_start_ts=_layer_start_timestamps(run),
        jumped=_run_was_jumped(run),
    )
    with (run / "layer_accuracy.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(LAYER_ACCURACY_FIELDS)
        for r in rows:
            writer.writerow(["" if r[k] is None else r[k] for k in LAYER_ACCURACY_FIELDS])


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


def _event_labels(run: Path) -> list[str]:
    """All event labels from a run's events.json, in order; ``[]`` when missing/unreadable."""
    try:
        events = json.loads((run / "events.json").read_text())
    except (OSError, ValueError):
        return []
    return [e.get("label", "") for e in events if isinstance(e, dict)] if isinstance(events, list) \
        else []


# Fault signals rank above every other outcome: a print fault, a controller fault, or an e-stop
# means the run ended in an emergency condition regardless of what abort was emitted in its wake.
_FAULT_LABELS = frozenset({"print_fault", "fault", "estop"})


def derive_run_status(labels: list[str], *, complete: bool, active: bool = False) -> str:
    """Outcome of a run from its event labels (verified against real events.json, data-contract §1).

    Returns one of: ``fault`` (danger), ``finished`` (clean print_done), ``aborted`` (operator
    abort), ``running`` (the live still-recording run), ``incomplete`` (a print began but recorded
    no terminal outcome, or the recording never closed cleanly), ``recorded`` (a telemetry-only
    session with no print). ``incomplete`` and ``recorded`` are deliberately NOT healthy-green so an
    unknown/absent outcome never reads as success (data-contract §5)."""
    s = set(labels)
    if s & _FAULT_LABELS:
        return "fault"
    if "print_done" in s:
        return "finished"
    if "print_aborted" in s:
        return "aborted"
    if active and not complete:
        return "running"
    if "print_started" in s or not complete:
        return "incomplete"
    return "recorded"


def _read_run_meta(run: Path) -> dict[str, Any]:
    """Best-effort read of a run's metadata.json; ``{}`` when missing or unreadable."""
    try:
        loaded = json.loads((run / "metadata.json").read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _layer_count(run: Path) -> int | None:
    """Recorded layer rows (layers.csv rows minus the header), or ``None`` when unreadable.

    A missing/empty file (no header) yields ``None`` -- unknown, never a false ``0``.
    """
    try:
        with (run / "layers.csv").open(newline="") as f:
            rows = sum(1 for _ in csv.reader(f))
    except OSError:
        return None
    return rows - 1 if rows else None


def _telemetry_duration_s(run: Path) -> float | None:
    """(last - first) ``host_timestamp_ns`` / 1e9 from telemetry.csv, or ``None`` when < 2 rows."""
    try:
        with (run / "telemetry.csv").open(newline="") as f:
            stamps = [
                t for row in csv.DictReader(f) if (t := _to_float(row.get("host_timestamp_ns")))
                is not None
            ]
    except OSError:
        return None
    if len(stamps) < 2:
        return None
    return round((stamps[-1] - stamps[0]) / 1e9, 3)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def summarize_run(d: Path, active: Path | None = None) -> dict[str, Any]:
    """Runs-browser summary for one run directory (size, status, layer/capture counts, job link).
    ``active`` is the currently-recording directory, if any (only it can be status "recording")."""
    # One walk for both the byte size and the vision-capture count (a run is "analyzable"
    # in the Analysis tab only if it has captured images under vision/).
    size = 0
    captures = 0
    for f in d.rglob("*"):
        if not f.is_file():
            continue
        size += f.stat().st_size
        # One capture == one stage. Count each stage's PRIMARY image once: the always-present
        # ``<stage>.raw.webp`` (or an old ``.png``). The registered ``<stage>.webp`` is a derived
        # copy — often deduped away entirely — so it must not add to the count.
        if f.relative_to(d).parts[0] == "vision" and (
            f.name.endswith(".raw.webp") or f.suffix == ".png"
        ):
            captures += 1
    meta = _read_run_meta(d)
    raw_experiment = meta.get("experiment")
    experiment: dict[str, Any] = raw_experiment if isinstance(raw_experiment, dict) else {}
    complete = (d / "manifest.json").exists()
    return {
        "run": d.name,
        "complete": complete,
        "status": derive_run_status(
            _event_labels(d), complete=complete, active=(d == active)
        ),
        "size_bytes": size,
        "name": experiment.get("name", ""),
        "notes": experiment.get("notes", ""),
        "started_at": meta.get("started_utc"),
        "layer_count": _layer_count(d),
        "duration_s": _telemetry_duration_s(d),
        "capture_count": captures,
        # Job link (recorded going forward): lets a Runs card show that job's preview.
        # None for manual prints and every pre-existing run (data-contract: no link).
        "job_folder": experiment.get("job_folder"),
        "job_name": experiment.get("job_name"),
    }


def list_runs_in(root: Path, active: Path | None = None) -> list[dict[str, Any]]:
    """Runs-browser summaries for every run directory directly under ``root`` (newest first)."""
    if not root.exists():
        return []
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    return [summarize_run(d, active=active) for d in dirs]


class Recorder:
    def __init__(
        self,
        root: Path,
        on_active_change: Callable[[bool], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root
        # Fired True when a run starts recording and False when it stops -- lets the controller poll
        # telemetry faster during a run (finer motion profiles) without the recorder knowing it.
        self._on_active_change = on_active_change
        # Source of the run's start instant (timestamp for the dir name and started_utc).
        # Injectable so tests can pin it: the dir name is second-resolution, so the _N collision
        # suffix only appears when two runs share a second -- with the live clock that made
        # same-second-collision assertions flaky. Defaults to the live UTC clock.
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self.active: Path | None = None
        self._csv: Any = None
        self._file: Any = None
        self._layers_csv: Any = None
        self._layers_file: Any = None
        self._events: list[dict[str, Any]] = []
        self._count = 0
        self._started = 0.0
        self._lock = threading.Lock()

    def _signal_active(self, active: bool) -> None:
        if self._on_active_change is None:
            return
        try:
            self._on_active_change(active)
        except Exception as exc:  # noqa: BLE001 - a poll-rate hint must never break recording
            log.warning("recorder on_active_change hook failed: %s", exc)

    def start(self, name: str, *, notes: str = "", metadata: dict[str, Any] | None = None) -> Path:
        with self._lock:
            if self.active is not None:
                raise RuntimeError("already recording")
            self.root.mkdir(parents=True, exist_ok=True)
            now = self._clock()
            stamp = now.strftime("%Y%m%d_%H%M%S")
            base = f"{stamp}_{_slug(name)}"
            run, n = self.root / base, 2
            while run.exists():
                run, n = self.root / f"{base}_{n}", n + 1
            run.mkdir()
            meta = {
                "format_version": FORMAT_VERSION,
                "started_utc": now.isoformat(),
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
        self._signal_active(True)
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
            # Native measured speed (mm/s) per axis; blank when the controller didn't report it.
            vspeed = t.get("actual_speed") or {}
            self._csv.writerow(
                [
                    t["host_timestamp_ns"],
                    snapshot["state"],
                    snapshot["armed"],
                    pos.get("1"),
                    pos.get("2"),
                    pos.get("3"),
                    pos.get("4"),
                    vspeed.get("1", ""),
                    vspeed.get("2", ""),
                    vspeed.get("3", ""),
                    vspeed.get("4", ""),
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
            # Derive motion_profiles.csv + layer_accuracy.csv from the streamed telemetry now that
            # it is flushed/closed (finite-diff profiles + per-layer build-piston accuracy).
            _write_motion_profiles(run)
            _write_layer_accuracy(run)
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
                        "layer_accuracy.csv",
                    )
                },
            }
            (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
            self.active, self._csv, self._file = None, None, None
            self._layers_csv, self._layers_file = None, None
        self._signal_active(False)
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        return list_runs_in(self.root, active=self.active)
