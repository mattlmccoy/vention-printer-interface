"""Data-offload core: drive listing, mirror diff, verified/resumable run copy."""

from __future__ import annotations

import os
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


def test_list_drives_excludes_the_boot_volume(tmp_path: Path) -> None:
    vols = tmp_path / "Volumes"
    (vols / "SSD_A").mkdir(parents=True)
    (vols / "SSD_B").mkdir()
    (vols / "note.txt").write_text("not a dir")  # ignored
    # make SSD_A look like the boot volume by matching its st_dev to the "root"
    root_dev = os.stat(vols / "SSD_A").st_dev
    drives = list_drives(volumes_dir=vols, root_dev=root_dev)
    names = {d.name for d in drives}
    # both share the tmpfs st_dev here, so with root_dev set to that, both are excluded;
    # verify the mechanism by excluding none when root_dev is a sentinel
    assert list_drives(volumes_dir=vols, root_dev=-1) and names == set()
    all_drives = list_drives(volumes_dir=vols, root_dev=-1)
    assert {d.name for d in all_drives} == {"SSD_A", "SSD_B"}
    assert all(d.total_bytes > 0 and d.path.endswith(d.name) for d in all_drives)


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
