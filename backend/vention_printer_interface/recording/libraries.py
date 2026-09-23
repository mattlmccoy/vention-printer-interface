"""Cross-location run enumeration.

Runs live under the local experiments root and, once offloaded, under any mounted drive's
``vpi-runs/`` folder. These pure helpers union the two so the Runs browser shows a run whether it
sits on disk or a drive (mirrors the FLIR ``library`` model), and resolve a run to whichever
location holds it — local first. No registration: every mounted drive that has a ``vpi-runs/`` is
scanned, so plugging a drive in makes its runs appear and unplugging drops them off.
"""

from pathlib import Path
from typing import Any

from vention_printer_interface.offload import DEST_SUBDIR, Drive

LOCAL = "local"


def run_roots(local_root: Path, drives: list[Drive]) -> list[tuple[str, Path]]:
    """``(library, root)`` pairs to enumerate runs in: always local first, then each mounted drive
    that actually has a ``vpi-runs/`` folder (labelled by the drive's name)."""
    roots: list[tuple[str, Path]] = [(LOCAL, Path(local_root))]
    for d in drives:
        vpi = Path(d.path) / DEST_SUBDIR
        if vpi.is_dir():
            roots.append((d.name, vpi))
    return roots


def merge_runs(labeled: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Union per-root run summaries into one list, deduped by run name. The FIRST library that has a
    run supplies its payload (callers pass local first, so the local copy wins), and every library
    the run appears in is recorded on ``locations``. Sorted OLDEST-first by the timestamped name,
    matching the single-root ``list_runs`` contract callers rely on (``runs[-1]`` is the newest)."""
    merged: dict[str, dict[str, Any]] = {}
    for library, runs in labeled:
        for run in runs:
            name = str(run.get("run", ""))
            existing = merged.get(name)
            if existing is None:
                merged[name] = {**run, "locations": [library]}
            elif library not in existing["locations"]:
                existing["locations"].append(library)
    return sorted(merged.values(), key=lambda r: str(r.get("run", "")))


def _safe_run_name(run: str) -> str:
    """Reject names that could escape a root (traversal / separators / empty). Returns the name."""
    if not run or run in (".", "..") or "/" in run or "\\" in run:
        raise ValueError(f"bad run name: {run!r}")
    return run


def resolve_run_across(
    roots: list[tuple[str, Path]], run: str
) -> tuple[Path, str] | None:
    """Resolve ``run`` to ``(directory, library)`` in the first root (local-first) that holds it, or
    ``None`` when no root does. Raises ``ValueError`` for a traversing / malformed run name."""
    name = _safe_run_name(run)
    for library, root in roots:
        d = (Path(root) / name).resolve()
        if d.parent != Path(root).resolve():  # traversal guard (defence in depth)
            continue
        if d.is_dir():
            return d, library
    return None


def restore_source(roots: list[tuple[str, Path]], run: str) -> Path | None:
    """The drive directory holding ``run`` (first non-local library), for a restore-to-local move,
    or ``None`` when the run is local-only or absent (nothing to restore). Raises ``ValueError`` for
    a traversing / malformed run name."""
    name = _safe_run_name(run)
    for library, root in roots:
        if library == LOCAL:
            continue
        d = (Path(root) / name).resolve()
        if d.parent == Path(root).resolve() and d.is_dir():
            return d
    return None
