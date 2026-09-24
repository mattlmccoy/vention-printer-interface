"""Data-offload core: drive listing, mirror diff, verified/resumable run copy."""

from __future__ import annotations

from pathlib import Path

from vention_printer_interface.offload import (
    copy_run,
    file_sha256,
    list_drives,
    mirror_diff,
)


def _write(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_mirror_diff_returns_source_runs_missing_at_dest() -> None:
    assert mirror_diff(["a", "b", "c"], {"b"}) == ["a", "c"]
    assert mirror_diff(["a"], {"a"}) == []
    assert mirror_diff([], set()) == []


def test_file_sha256_matches_content(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    import hashlib
    assert file_sha256(p) == hashlib.sha256(b"hello").hexdigest()


def test_copy_run_copies_verifies_and_is_resumable(tmp_path: Path) -> None:
    src = tmp_path / "runs" / "20260101_run"
    _write(src / "telemetry.csv", b"a,b,c\n1,2,3\n")
    _write(src / "layers.csv", b"x\n")
    _write(src / "vision" / "layer1.png", b"\x89PNG fake")
    dest = tmp_path / "drive" / "20260101_run"

    r1 = copy_run(src, dest)
    assert r1.files_copied == 3 and r1.files_skipped == 0 and r1.verified is True
    assert not r1.errors
    # every file present with identical content (hash) at dest
    for rel in ("telemetry.csv", "layers.csv", "vision/layer1.png"):
        assert file_sha256(dest / rel) == file_sha256(src / rel)

    # re-run: nothing changed -> all skipped (idempotent / resumable)
    r2 = copy_run(src, dest)
    assert r2.files_copied == 0 and r2.files_skipped == 3

    # corrupt a dest file -> only that one is re-copied
    (dest / "layers.csv").write_bytes(b"CORRUPT")
    r3 = copy_run(src, dest)
    assert r3.files_copied == 1 and r3.files_skipped == 2
    assert file_sha256(dest / "layers.csv") == file_sha256(src / "layers.csv")


def test_copy_run_reports_progress(tmp_path: Path) -> None:
    src = tmp_path / "r"
    _write(src / "a.txt", b"a")
    _write(src / "b.txt", b"b")
    seen: list[tuple[int, int]] = []
    copy_run(src, tmp_path / "d", on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (2, 2)  # ends at all files done


def test_list_drives_excludes_readonly_dmgs_and_system_volumes() -> None:
    # mirrors the FLIR storage filter: psutil parts, exclude read-only ("ro") mounts (a mounted DMG
    # like "Kiro CLI"), the boot volume, and anything not under /Volumes on macOS.
    from vention_printer_interface.offload import _Part
    parts = [
        _Part("/dev/disk1s1", "/", "apfs", "rw"),                      # boot, not /Volumes
        _Part("/dev/disk2s1", "/Volumes/Macintosh HD", "apfs", "rw"),  # boot alias -> excluded
        _Part("/dev/disk3s1", "/Volumes/Kiro CLI", "hfs", "ro,nobrowse"),  # read-only DMG -> out
        _Part("/dev/disk4s1", "/Volumes/FieldSSD", "exfat", "rw,nosuid"),  # real drive -> in
    ]
    drives = list_drives(platform="darwin", parts=parts, usage=lambda _m: (2000, 900))
    assert [d.name for d in drives] == ["FieldSSD"]
    assert drives[0].free_bytes == 900 and drives[0].path == "/Volumes/FieldSSD"


def test_list_drives_excludes_hidden_macos_system_volumes() -> None:
    # Captured on the lab Mac 2026-09-23 (psutil disk_partitions(all=False)): the APFS Recovery
    # volume mounts READ-WRITE under /Volumes, so the rw + /Volumes rule offered it as an offload
    # destination. macOS marks it (and DMGs) `dontbrowse`; a real drive has no such flag.
    from vention_printer_interface.offload import _Part
    parts = [
        _Part("/dev/disk3s3", "/Volumes/Recovery", "apfs",
              "rw,local,dovolfs,dontbrowse,journaled,multilabel"),
        _Part("/dev/disk5s1", "/Volumes/Kiro CLI", "hfs",
              "ro,nosuid,local,dovolfs,dontbrowse,ignore-ownership,multilabel"),
        _Part("/dev/disk6s1", "/Volumes/FLIR SSD", "exfat",
              "rw,nosuid,local,ignore-ownership,noatime"),
    ]
    drives = list_drives(platform="darwin", parts=parts, usage=lambda _m: (2000, 900))
    assert [d.name for d in drives] == ["FLIR SSD"]


def test_copy_run_skips_os_junk(tmp_path: Path) -> None:
    src = tmp_path / "r"
    _write(src / "data.csv", b"x")
    _write(src / ".DS_Store", b"junk")
    _write(src / "._data.csv", b"appledouble")
    copy_run(src, tmp_path / "d")
    assert (tmp_path / "d" / "data.csv").exists()
    assert not (tmp_path / "d" / ".DS_Store").exists()
    assert not (tmp_path / "d" / "._data.csv").exists()


def test_move_run_copies_verifies_then_deletes_source(tmp_path: Path) -> None:
    from vention_printer_interface.offload import move_run
    src = tmp_path / "experiments" / "run1"
    _write(src / "telemetry.csv", b"telem")
    _write(src / "vision" / "l.png", b"\x89PNG")
    dest = tmp_path / "drive" / "vpi-runs" / "run1"
    res = move_run(src, dest)
    assert res.verified and not src.exists()          # source gone only after verified copy
    assert (dest / "telemetry.csv").read_bytes() == b"telem"
    assert (dest / "vision" / "l.png").read_bytes() == b"\x89PNG"
    assert not dest.with_name("run1.partial").exists()  # staging cleaned up


def test_offload_job_copies_selected_runs_and_reports(tmp_path: Path) -> None:
    from vention_printer_interface.offload import OffloadJob, offload_plan
    src = tmp_path / "experiments"
    _write(src / "runA" / "t.csv", b"a")
    _write(src / "runB" / "t.csv", b"b")
    dest = tmp_path / "drive"
    job = OffloadJob(src, dest, ["runA", "runB"])
    job._run()  # synchronous for the test
    snap = job.snapshot()
    assert snap["state"] == "done"
    assert snap["progress"]["runs_done"] == 2
    assert snap["files_copied"] == 2
    # landed under the vpi-runs subdir on the drive
    assert (dest / "vpi-runs" / "runA" / "t.csv").read_bytes() == b"a"
    # plan now shows both present
    plan = offload_plan(["runA", "runB"], dest)
    assert plan == [{"run": "runA", "at_dest": True}, {"run": "runB", "at_dest": True}]


def test_offload_plan_flags_missing(tmp_path: Path) -> None:
    from vention_printer_interface.offload import offload_plan
    assert offload_plan(["x", "y"], tmp_path / "empty") == [
        {"run": "x", "at_dest": False}, {"run": "y", "at_dest": False}]
