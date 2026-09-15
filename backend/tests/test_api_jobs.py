import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_jobs import make_job
from vention_printer_interface.api.app import choose_jobs_root, create_app

_SHARED = Path("/dropbox/binderjet/code/rfam-web/Hot Folder")
_FALLBACK = Path("/repo/backend/jobs")


def test_env_var_overrides_everything() -> None:
    # The Windows print PC (a standalone clone OUTSIDE Dropbox) sets VPI_JOBS_ROOT so it
    # reads its local Dropbox Hot Folder without a --jobs-root argument.
    p, warn = choose_jobs_root("/win/Dropbox/Hot Folder", _SHARED, shared_exists=False,
                               fallback=_FALLBACK)
    assert p == Path("/win/Dropbox/Hot Folder")
    assert warn is None


def test_shared_used_when_it_exists_here() -> None:
    # On the Mac the code lives INSIDE Dropbox, so the script-relative shared folder is real.
    p, warn = choose_jobs_root(None, _SHARED, shared_exists=True, fallback=_FALLBACK)
    assert p == _SHARED
    assert warn is None


def test_falls_back_and_warns_when_shared_missing() -> None:
    # Regression: on the Windows clone parents[5] resolved to C:\Users\code\rfam-web\Hot Folder,
    # which does not exist. Must NOT silently return that bogus path — fall back and warn loudly.
    p, warn = choose_jobs_root(None, Path("C:/Users/code/rfam-web/Hot Folder"),
                               shared_exists=False, fallback=_FALLBACK)
    assert p == _FALLBACK
    assert warn is not None
    assert "VPI_JOBS_ROOT" in warn and "--jobs-root" in warn


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    make_job(tmp_path / "jobs", "20260414_171155_8MM-ROD-CLAMPS-03MM-TOL", 4)
    app = create_app(
        backend="none",
        experiments_root=tmp_path / "exp",
        poll_interval_s=0.05,
        jobs_roots=[tmp_path / "jobs"],
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
    )
    with TestClient(app) as c:
        yield c


def test_splash_preview_endpoint(client: TestClient, tmp_path: Path) -> None:
    from PIL import Image
    folder = "20260414_171155_8MM-ROD-CLAMPS-03MM-TOL"
    job_dir = tmp_path / "jobs" / folder
    # No splash yet -> 404, and the listing reports has_preview False.
    assert client.get(f"/api/jobs/by-folder/{folder}/preview.png").status_code == 404
    assert all(j["has_preview"] is False for j in client.get("/api/jobs").json()["jobs"])
    # Drop in the slicer splash (a real captured naming convention) -> served as PNG.
    Image.new("RGB", (64, 48), (10, 20, 30)).save(job_dir / "8MM-ROD-CLAMPS-03MM-TOL_preview.bmp")
    r = client.get(f"/api/jobs/by-folder/{folder}/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert any(j["has_preview"] for j in client.get("/api/jobs").json()["jobs"])


def test_list_select_and_preview(client: TestClient) -> None:
    jobs = client.get("/api/jobs").json()["jobs"]
    assert (
        len(jobs) == 1
        and jobs[0]["name"] == "8MM-ROD-CLAMPS-03MM-TOL"
        and jobs[0]["layer_count"] == 4
    )
    assert client.get("/api/status").json()["job"] is None
    r = client.post("/api/jobs/select", json={"path": jobs[0]["path"]})
    assert r.status_code == 200
    job = client.get("/api/status").json()["job"]
    assert job["layer_count"] == 4 and job["layer_height_mm"] == 0.1 and job["complete"] is True
    print_settings = client.get("/api/print-settings").json()["plan"]
    # Selecting a job sets ONLY the layer count; the layer thickness keeps its (default/selected)
    # standard value rather than being forced to the slicer-derived height.
    assert (
        print_settings["printing"]["n_layers"] == 4
        and print_settings["printing"]["layer_thickness_mm"] == 2.0
    )
    png = client.get("/api/jobs/current/layers/2.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.get("/api/jobs/current/layers/9.png").status_code == 404
    assert client.post("/api/jobs/clear").status_code == 200
    assert client.get("/api/status").json()["job"] is None


def test_job_layer_by_folder_serves_any_job_without_selecting(client: TestClient) -> None:
    """The Runs/Analysis stills compare needs a specific job's layer (incl. archived jobs) even
    when it isn't the currently-selected job."""
    folder = "20260414_171155_8MM-ROD-CLAMPS-03MM-TOL"
    png = client.get(f"/api/jobs/by-folder/{folder}/layers/2.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.get("/api/jobs/by-folder/does-not-exist/layers/1.png").status_code == 404
    assert client.get(f"/api/jobs/by-folder/{folder}/layers/999.png").status_code == 404


def test_select_rejects_paths_outside_roots(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/api/jobs/select", json={"path": str(tmp_path / "exp")}).status_code == 400
    assert client.post("/api/jobs/select", json={"path": "/etc"}).status_code == 400


def test_status_job_tracks_current_layer_during_print(client: TestClient) -> None:
    jobs = client.get("/api/jobs").json()["jobs"]
    client.post("/api/jobs/select", json={"path": jobs[0]["path"]})
    client.put(
        "/api/print-settings",
        json={
            "thin_precoat": {"n_layers": 0},
            "postcoat": {"n_layers": 0},
            "feed_end_mm": 10,
            "recoater_end_mm": 30,
            "heater_end_mm": 20,
            "printhead_end_mm": 30,
            "printing": {
                "part_speed": 20,
                "feed_speed": 20,
                "recoater_speed": 300,
                "printhead_speed": 300,
                "recoater_accel": 2000,
                "printhead_accel": 2000,
                "part_accel": 100,
                "feed_accel": 100,
            },
            "settle_s": 0.05,
            "feed_fast_speed": 20,
            "feed_fast_accel": 100,
        },
    )
    client.post("/api/connect", json={"backend": "simulated"})
    for _ in range(100):
        if client.get("/api/status").json()["controller"]["telemetry"]:
            break
        time.sleep(0.02)
    client.post("/api/arm")
    client.post("/api/primed/capture")  # a print now requires a captured primed bed
    assert client.post("/api/print/start", json={"dry_run": True}).status_code == 200
    seen = set()
    for _ in range(600):
        s = client.get("/api/status").json()
        seen.add(s["job"]["current_layer"])
        if s["print"]["state"] == "done":
            break
        time.sleep(0.05)
    assert 4 in seen and s["print"]["state"] == "done"
