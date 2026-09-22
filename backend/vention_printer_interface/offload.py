"""Robust data offload — copy run directories to an external drive, FLIR-style.

The operator records runs to the internal experiments root; this copies them to a picked mounted
drive with integrity you can trust: each file is hashed after copy and only renamed into place once
verified, and a re-run skips files already present with a matching hash (so a yanked cable just
resumes cleanly next time). Pure/IO helpers; the API wraps them in a background job + endpoints.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20  # 1 MiB


@dataclass(frozen=True)
class Drive:
    name: str
    path: str
    total_bytes: int
    free_bytes: int


@dataclass
class CopyResult:
    files_copied: int = 0
    files_skipped: int = 0
    bytes_copied: int = 0
    files_total: int = 0
    verified: bool = True
    errors: list[str] = field(default_factory=list)


def file_sha256(path: Path, chunk: int = _CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def mirror_diff(source_runs: list[str], dest_runs: Iterable[str]) -> list[str]:
    """Source run names not yet present at the destination (order preserved)."""
    dest = set(dest_runs)
    return [r for r in source_runs if r not in dest]


def list_drives(volumes_dir: Path = Path("/Volumes"), root_dev: int | None = None) -> list[Drive]:
    """Mounted volumes suitable as an offload destination — every directory under ``volumes_dir``
    except the boot volume (whose device id matches ``root_dev``; defaults to ``/``'s). Sorted by
    name. Free/total come from ``shutil.disk_usage``; an unreadable volume is skipped."""
    if root_dev is None:
        root_dev = os.stat("/").st_dev
    drives: list[Drive] = []
    try:
        entries = sorted(volumes_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for vol in entries:
        try:
            if not vol.is_dir() or vol.is_symlink() or os.stat(vol).st_dev == root_dev:
                continue
            usage = shutil.disk_usage(vol)
        except OSError:
            continue
        drives.append(Drive(vol.name, str(vol), usage.total, usage.free))
    return drives


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def copy_run(
    src_run_dir: Path,
    dest_run_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> CopyResult:
    """Copy ``src_run_dir`` -> ``dest_run_dir`` with per-file hash verification and resume.

    For each source file: if the destination already has it with a matching SHA-256, skip; else copy
    to a ``.part`` temp, verify its hash equals the source, then atomically rename into place. A
    mismatch or IO error is recorded in ``errors`` and flips ``verified`` False (the file is left as
    its verified-good previous copy, if any, never a half-written one)."""
    files = _files_under(src_run_dir)
    res = CopyResult(files_total=len(files))
    for i, src in enumerate(files, start=1):
        rel = src.relative_to(src_run_dir)
        dest = dest_run_dir / rel
        try:
            src_hash = file_sha256(src)
            if dest.is_file() and dest.stat().st_size == src.stat().st_size \
                    and file_sha256(dest) == src_hash:
                res.files_skipped += 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".part")
                shutil.copy2(src, tmp)
                if file_sha256(tmp) != src_hash:
                    tmp.unlink(missing_ok=True)
                    raise OSError(f"hash mismatch after copy: {rel}")
                os.replace(tmp, dest)  # atomic
                res.files_copied += 1
                res.bytes_copied += src.stat().st_size
        except OSError as exc:
            res.verified = False
            res.errors.append(str(exc))
        if on_progress is not None:
            on_progress(i, len(files))
    return res


# Runs are copied under this subdir on the destination drive, so the drive root stays tidy and a
# mirror can tell "ours" from the operator's other files.
DEST_SUBDIR = "vpi-runs"


class OffloadJob:
    """Background copy of several runs to a destination drive, with a pollable snapshot. One at a
    time; cancel is checked between runs and files (a partial file is never left mid-write)."""

    def __init__(self, source_root: Path, dest_root: Path, run_names: list[str]) -> None:
        self._source_root = source_root
        self._dest_runs = Path(dest_root) / DEST_SUBDIR
        self._runs = list(run_names)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._state = "running" if run_names else "done"
        self._done = 0
        self._current = ""
        self._file_done = 0
        self._file_total = 0
        self._copied = 0
        self._skipped = 0
        self._errors: list[str] = []

    def start_thread(self) -> None:
        threading.Thread(target=self._run, name="offload", daemon=True).start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        for name in self._runs:
            if self._cancel.is_set():
                break
            with self._lock:
                self._current, self._file_done, self._file_total = name, 0, 0

            def _prog(done: int, total: int) -> None:
                with self._lock:
                    self._file_done, self._file_total = done, total

            try:
                r = copy_run(self._source_root / name, self._dest_runs / name, on_progress=_prog)
            except OSError as exc:  # pragma: no cover - copy_run swallows per-file; belt + braces
                r = CopyResult(verified=False, errors=[f"{name}: {exc}"])
            with self._lock:
                self._done += 1
                self._copied += r.files_copied
                self._skipped += r.files_skipped
                self._errors += [f"{name}: {e}" for e in r.errors]
        with self._lock:
            if self._state == "running":
                self._state = "cancelled" if self._cancel.is_set() else \
                    ("error" if self._errors else "done")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "dest": str(self._dest_runs),
                "progress": {"runs_done": self._done, "runs_total": len(self._runs),
                             "current": self._current,
                             "file_done": self._file_done, "file_total": self._file_total},
                "files_copied": self._copied,
                "files_skipped": self._skipped,
                "errors": list(self._errors),
            }


def offload_plan(source_runs: list[str], dest_root: Path) -> list[dict[str, Any]]:
    """Per-run offload status against a destination: whether each source run is already present in
    the drive's ``vpi-runs`` folder. (Presence only — the copy still hash-verifies each file.)"""
    present: set[str] = set()
    dest_runs = Path(dest_root) / DEST_SUBDIR
    try:
        present = {p.name for p in dest_runs.iterdir() if p.is_dir()}
    except OSError:
        present = set()
    return [{"run": r, "at_dest": r in present} for r in source_runs]


def _job_dict(job: OffloadJob | None) -> dict[str, Any]:
    return job.snapshot() if job is not None else {"state": "idle"}


# asdict re-export so the API can serialize Drive without importing dataclasses
def drive_dict(d: Drive) -> dict[str, Any]:
    return asdict(d)
