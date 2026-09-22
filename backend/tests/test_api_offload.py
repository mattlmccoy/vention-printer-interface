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
