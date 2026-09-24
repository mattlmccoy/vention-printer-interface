"""Robust data offload — copy run directories to an external drive, FLIR-style.

The operator records runs to the internal experiments root; this copies them to a picked mounted
drive with integrity you can trust: each file is hashed after copy and only renamed into place once
verified, and a re-run skips files already present with a matching hash (so a yanked cable just
resumes cleanly next time). Pure/IO helpers; the API wraps them in a background job + endpoints.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psutil

_CHUNK = 1 << 20  # 1 MiB

# OS bookkeeping files that are not run data — never copied/verified/counted, so they can't fail an
# integrity check or clutter an exFAT drive. (Mirrors the FLIR storage filter.)
_JUNK_NAMES = frozenset({".DS_Store", ".Spotlight-V100", ".Trashes", ".fseventsd",
                         "System Volume Information"})


def _is_os_junk(name: str) -> bool:
    return name.startswith("._") or name in _JUNK_NAMES  # ._ = macOS AppleDouble


@dataclass(frozen=True)
class Drive:
    name: str
    path: str
    total_bytes: int
    free_bytes: int


@dataclass(frozen=True)
class _Part:
    """The subset of a psutil disk partition this module needs (also lets tests inject samples)."""

    device: str
    mountpoint: str
    fstype: str
    opts: str


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


def _live_parts() -> list[_Part]:
    return [
        _Part(p.device, p.mountpoint, p.fstype, p.opts)
        for p in psutil.disk_partitions(all=False)
    ]


def _is_external(platform: str, p: _Part) -> bool:
    """A real, WRITABLE, user-mountable offload target — not a system volume or read-only DMG.
    Mirrors the FLIR storage filter. The ``ro`` mount flag is what excludes a mounted disk image
    (e.g. an app installer showing 0 bytes free)."""
    opts = p.opts.split(",")
    if "ro" in opts:
        return False  # read-only mounts (mounted DMGs, read-only NTFS) are never targets
    if "dontbrowse" in opts:
        return False  # macOS hidden system volume (APFS Recovery mounts rw under /Volumes)
    if platform == "darwin":
        return p.mountpoint.startswith("/Volumes/") and Path(p.mountpoint).name != "Macintosh HD"
    if platform == "linux":
        return any(p.mountpoint.startswith(pre) for pre in ("/media/", "/run/media/", "/mnt/"))
    if platform.startswith("win"):
        drive = p.mountpoint.rstrip("\\/").upper()
        return ("removable" in p.opts) or (drive not in ("", "C:") and p.fstype != "")
    return False


def list_drives(
    platform: str = sys.platform,
    parts: list[_Part] | None = None,
    usage: Callable[[str], tuple[int, int]] | None = None,
) -> list[Drive]:
    """User-selectable external drives for offload, filtered from every mounted volume via psutil —
    excludes read-only mounts (mounted DMGs like "Kiro CLI"), the boot volume, and non-user mounts.
    ``parts``/``usage`` default to the live system; tests inject captured samples."""
    parts = _live_parts() if parts is None else parts
    _usage = usage or (lambda m: (shutil.disk_usage(m).total, shutil.disk_usage(m).free))
    drives: list[Drive] = []
    for p in parts:
        if not _is_external(platform, p):
            continue
        try:
            total, free = _usage(p.mountpoint)
        except OSError:
            continue  # a volume that vanished between listing and stat
        drives.append(Drive(Path(p.mountpoint).name or p.device, p.mountpoint, total, free))
    return sorted(drives, key=lambda d: d.name)


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not _is_os_junk(p.name))


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


def _remove_tree(path: Path) -> None:
    """Delete a run folder robustly on exFAT / removable drives (mirrors FLIR). ``shutil.rmtree``
    races on exFAT — AppleDouble ``._`` sidecars vanish mid-walk raising ENOENT — so we ignore
    already-gone entries and retry, then remove the sibling ``._<name>`` AppleDouble file."""

    def _onexc(_f: Any, _p: Any, exc: BaseException) -> None:
        if not isinstance(exc, FileNotFoundError):
            raise exc

    for _ in range(3):
        if not path.exists():
            break
        shutil.rmtree(path, onexc=_onexc)
    with contextlib.suppress(FileNotFoundError):
        (path.parent / f"._{path.name}").unlink()
    if path.exists():
        raise OSError(f"could not fully remove {path}")


def move_run(
    src_run_dir: Path,
    dest_run_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> CopyResult:
    """MOVE a run to the drive to free local space: copy -> verify -> rename -> delete source.

    The source is deleted ONLY after the copy is hash-verified and atomically renamed into place, so
    a failure or a drive disconnect mid-copy never leaves the run missing from both places (mirrors
    FLIR ``move_experiment``). Copies to a ``.partial`` staging dir first; on any error it's cleaned
    up and the source is left intact."""
    src, final = Path(src_run_dir), Path(dest_run_dir)
    partial = final.with_name(final.name + ".partial")
    with contextlib.suppress(OSError):
        _remove_tree(partial)  # clear any leftover half-copy from an interrupted move
    try:
        res = copy_run(src, partial, on_progress=on_progress)  # per-file hash-verified
        if not res.verified:
            with contextlib.suppress(OSError):
                _remove_tree(partial)
            return res  # verification failed -> leave the source untouched
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            _remove_tree(final)  # os.replace can't rename onto a non-empty dir
        os.replace(partial, final)  # atomic on the target filesystem
    except BaseException:
        with contextlib.suppress(OSError):
            _remove_tree(partial)
        raise
    _remove_tree(src)  # the only deletion of the source, after verify + rename
    return res


# Runs are copied under this subdir on the destination drive, so the drive root stays tidy and a
# mirror can tell "ours" from the operator's other files.
DEST_SUBDIR = "vpi-runs"


class OffloadJob:
    """Background copy of several runs to a destination drive, with a pollable snapshot. One at a
    time; cancel is checked between runs and files (a partial file is never left mid-write)."""

    def __init__(self, source_root: Path, dest_root: Path, run_names: list[str],
                 mode: str = "copy") -> None:
        self._source_root = source_root
        self._dest_runs = Path(dest_root) / DEST_SUBDIR
        self._runs = list(run_names)
        self._mode = "move" if mode == "move" else "copy"
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

            fn = move_run if self._mode == "move" else copy_run
            try:
                r = fn(self._source_root / name, self._dest_runs / name, on_progress=_prog)
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
                "mode": self._mode,
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
