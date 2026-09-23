"""Cross-location run enumeration: runs on the local root + any mounted drive's vpi-runs/ folder,
merged so a run shows up whether it lives on disk or a drive (FLIR-parity)."""

from pathlib import Path

import pytest

from vention_printer_interface.offload import DEST_SUBDIR, Drive
from vention_printer_interface.recording.libraries import (
    merge_runs,
    resolve_run_across,
    restore_source,
    run_roots,
)


def _drive(name: str, path: Path) -> Drive:
    return Drive(name=name, path=str(path), total_bytes=0, free_bytes=0)


def test_run_roots_local_first_plus_mounted_drives_with_vpi_runs(tmp_path: Path) -> None:
    local = tmp_path / "experiments"
    local.mkdir()
    d_with = tmp_path / "SSD"
    (d_with / DEST_SUBDIR).mkdir(parents=True)  # has vpi-runs/ -> included
    d_without = tmp_path / "USB"
    d_without.mkdir()  # no vpi-runs/ -> excluded
    roots = run_roots(local, [_drive("SSD", d_with), _drive("USB", d_without)])
    assert roots[0] == ("local", local)  # local always first
    assert ("SSD", d_with / DEST_SUBDIR) in roots
    assert all(lib != "USB" for lib, _ in roots)  # drive without vpi-runs/ excluded


def test_merge_runs_dedups_by_name_with_locations_local_first(tmp_path: Path) -> None:
    local_runs = [{"run": "B", "name": "beta-local"}, {"run": "A", "name": "alpha"}]
    drive_runs = [{"run": "C", "name": "gamma"}, {"run": "B", "name": "beta-drive"}]
    merged = merge_runs([("local", local_runs), ("SSD", drive_runs)])
    by = {r["run"]: r for r in merged}
    assert [r["run"] for r in merged] == ["A", "B", "C"]  # oldest-first (runs[-1] == newest)
    assert by["A"]["locations"] == ["local"]
    assert by["C"]["locations"] == ["SSD"]
    assert by["B"]["locations"] == ["local", "SSD"]  # present in both
    assert by["B"]["name"] == "beta-local"  # local copy wins the payload (local-first)


def test_resolve_run_across_local_first(tmp_path: Path) -> None:
    local = tmp_path / "exp"
    drive = tmp_path / "SSD" / DEST_SUBDIR
    (local / "R1").mkdir(parents=True)
    (drive / "R1").mkdir(parents=True)  # in both
    (drive / "R2").mkdir(parents=True)  # drive only
    roots = [("local", local), ("SSD", drive)]
    assert resolve_run_across(roots, "R1") == (local / "R1", "local")  # local wins
    assert resolve_run_across(roots, "R2") == (drive / "R2", "SSD")    # falls through to drive
    assert resolve_run_across(roots, "R3") is None                     # nowhere


def test_resolve_run_across_rejects_traversal(tmp_path: Path) -> None:
    roots = [("local", tmp_path / "exp")]
    for bad in ("../evil", "a/b", "", ".", ".."):
        with pytest.raises(ValueError):
            resolve_run_across(roots, bad)


def test_restore_source_returns_the_drive_dir_holding_the_run(tmp_path: Path) -> None:
    local = tmp_path / "exp"
    drive = tmp_path / "SSD" / DEST_SUBDIR
    (drive / "R1").mkdir(parents=True)   # on the drive only -> restorable
    (local / "R2").mkdir(parents=True)   # local only -> not restorable
    roots = [("local", local), ("SSD", drive)]
    assert restore_source(roots, "R1") == drive / "R1"  # the drive copy to pull back
    assert restore_source(roots, "R2") is None          # already local, nothing to restore
    assert restore_source(roots, "R3") is None           # absent everywhere


def test_restore_source_rejects_traversal(tmp_path: Path) -> None:
    roots = [("local", tmp_path / "exp"), ("SSD", tmp_path / "SSD" / DEST_SUBDIR)]
    for bad in ("../evil", "a/b", "", "."):
        with pytest.raises(ValueError):
            restore_source(roots, bad)
