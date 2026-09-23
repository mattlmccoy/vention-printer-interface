"""API tests for /api/offload/* (verified copy of runs to a picked drive)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


def _run(root: Path, name: str) -> None:
    d = root / name
    (d / "vision").mkdir(parents=True, exist_ok=True)
    (d / "telemetry.csv").write_text("t\n1\n")
    (d / "vision" / "l1.png").write_bytes(b"\x89PNG fake")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    exp = tmp_path / "experiments"
    exp.mkdir()
    _run(exp, "20260101_000000_a")
    _run(exp, "20260102_000000_b")
    app = create_app(backend="none", experiments_root=exp, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield c, tmp_path


def _wait_done(client: TestClient, timeout: float = 5.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        snap = client.get("/api/offload/job").json()
        if snap["state"] != "running":
            return snap
        time.sleep(0.05)
    raise AssertionError("offload did not finish in time")


def test_drives_endpoint_shape(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    r = client.get("/api/offload/drives")
    assert r.status_code == 200
    assert isinstance(r.json()["drives"], list)  # real /Volumes; shape only


def test_plan_flags_runs_then_copy_marks_them_present(env: tuple[TestClient, Path]) -> None:
    client, tmp = env
    drive = tmp / "DRIVE"
    drive.mkdir()
    plan = client.get(f"/api/offload/plan?dest={drive}").json()["plan"]
    assert {p["run"]: p["at_dest"] for p in plan} == {
        "20260102_000000_b": False, "20260101_000000_a": False}

    r = client.post("/api/offload/start", json={"dest": str(drive)},
                    headers={"X-VPI-Client": "1"})
    assert r.status_code == 200
    snap = _wait_done(client)
    assert snap["state"] == "done"
    assert snap["files_copied"] == 4  # 2 files x 2 runs
    # landed under vpi-runs, verified content
    assert (drive / "vpi-runs" / "20260101_000000_a" / "telemetry.csv").read_text() == "t\n1\n"
    # plan now shows both present
    plan2 = client.get(f"/api/offload/plan?dest={drive}").json()["plan"]
    assert all(p["at_dest"] for p in plan2)


def test_start_rejects_bad_dest(env: tuple[TestClient, Path]) -> None:
    client, tmp = env
    r = client.post("/api/offload/start", json={"dest": str(tmp / "nope")},
                    headers={"X-VPI-Client": "1"})
    assert r.status_code == 400


def test_start_with_no_missing_runs_is_400(env: tuple[TestClient, Path]) -> None:
    client, tmp = env
    drive = tmp / "DRIVE2"
    drive.mkdir()
    _wait_done(client) if False else None
    client.post("/api/offload/start", json={"dest": str(drive)}, headers={"X-VPI-Client": "1"})
    _wait_done(client)
    # second all-missing start now finds nothing to copy
    r = client.post("/api/offload/start", json={"dest": str(drive)}, headers={"X-VPI-Client": "1"})
    assert r.status_code == 400


def test_move_deletes_local_source_after_verified_copy(env: tuple[TestClient, Path]) -> None:
    client, tmp = env
    exp = tmp / "experiments"
    drive = tmp / "DRIVE_MOVE"
    drive.mkdir()
    r = client.post("/api/offload/start", json={"dest": str(drive), "move": True},
                    headers={"X-VPI-Client": "1"})
    assert r.status_code == 200
    assert r.json()["mode"] == "move"
    snap = _wait_done(client)
    assert snap["state"] == "done"
    # copied to the drive AND removed locally
    assert (drive / "vpi-runs" / "20260101_000000_a" / "telemetry.csv").exists()
    assert not (exp / "20260101_000000_a").exists()
    assert not (exp / "20260102_000000_b").exists()


def test_restore_moves_a_drive_run_back_to_local(
    env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, tmp = env
    exp = tmp / "experiments"
    drive = tmp / "SSD"
    dr = drive / "vpi-runs" / "20260909_000000_z"  # a run that lives ONLY on the drive
    dr.mkdir(parents=True)
    (dr / "telemetry.csv").write_text("t\n9\n")
    monkeypatch.setenv("VPI_FAKE_DRIVES", str(drive))
    # it appears in the browser tagged to the drive...
    z = next(r for r in client.get("/api/recordings").json()["runs"] if r["run"].endswith("_z"))
    assert z["locations"] == ["SSD"]
    # ...and restore pulls it back to local and removes the drive copy
    r = client.post("/api/recordings/20260909_000000_z/restore")
    assert r.status_code == 200 and r.json()["restored"] is True
    assert (exp / "20260909_000000_z" / "telemetry.csv").read_text() == "t\n9\n"
    assert not dr.exists()  # moved, not copied


def test_restore_guards_local_only_and_missing_and_bad(
    env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, tmp = env
    drive = tmp / "SSD"
    (drive / "vpi-runs").mkdir(parents=True)
    monkeypatch.setenv("VPI_FAKE_DRIVES", str(drive))
    # a local-only run is not on a drive -> 404
    assert client.post("/api/recordings/20260101_000000_a/restore").status_code == 404
    # a run that exists nowhere -> 404
    assert client.post("/api/recordings/20261212_000000_none/restore").status_code == 404
    # a run present on BOTH local and drive can't overwrite local -> 409
    (drive / "vpi-runs" / "20260101_000000_a").mkdir()
    assert client.post("/api/recordings/20260101_000000_a/restore").status_code == 409


def test_reveal_works_for_a_run_on_a_drive(
    env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # "reveal on disk: 400 bad run" for offloaded runs: reveal must resolve across mounted drives.
    import vention_printer_interface.api.app as appmod

    client, tmp = env
    drive = tmp / "SSD"
    dr = drive / "vpi-runs" / "20260909_000000_z"
    dr.mkdir(parents=True)
    (dr / "metadata.json").write_text("{}")
    monkeypatch.setenv("VPI_FAKE_DRIVES", str(drive))
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(appmod.subprocess, "run", lambda *a, **k: calls.append(a))
    r = client.post("/api/recordings/20260909_000000_z/reveal")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == str((dr / "metadata.json").resolve())  # on the drive, not local
    assert body["revealed"] is True and calls
