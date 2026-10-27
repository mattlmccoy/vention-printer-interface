"""Calibration history routes (api/calibration_history_routes.py): every saved calibration is
archived with its report and photos, listed, viewable, and can be made active again.

Runs use the real-detection autocal harness of tests/test_api_autocal.py (cv2-rendered board)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_api_autocal import _app, _moved_photo, _solved
from vention_printer_interface.vision.calibration_history import archive_calibration
from vention_printer_interface.vision.registration import load_calibration


def _saved_run(c: TestClient, app) -> str:  # type: ignore[no-untyped-def]
    _solved(c, app)
    assert c.post("/api/vision/autocal/selfcheck", content=_moved_photo()).json()["passed"]
    r = c.post("/api/vision/autocal/save")
    assert r.status_code == 200, r.text
    return str(r.json()["calibration_version"])


def test_saving_a_run_archives_it_with_its_report_and_photos(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        v = _saved_run(c, app)
        folder = tmp_path / "vision_calibrations" / v
        assert (folder / "calibration.json").is_file()
        assert json.loads((folder / "report.json").read_text())["point_method"] == "all"
        for name in ("capture", "raw", "corrected", "residuals"):
            assert (folder / f"{name}.jpg").read_bytes()[:2] == b"\xff\xd8", name


def test_list_and_detail_show_the_saved_run(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        v = _saved_run(c, app)
        rows = c.get("/api/vision/calibrations").json()
        assert [r["version"] for r in rows] == [v] and rows[0]["active"] and rows[0]["archived"]
        assert rows[0]["validation"]["status"] == "none"
        d = c.get(f"/api/vision/calibrations/{v}").json()
        assert d["images"] == ["capture", "raw", "corrected", "residuals"]
        assert d["report"]["passed"] is True and d["validations"] == []


def test_image_route_serves_jpeg_and_refuses_unknown_names(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        v = _saved_run(c, app)
        r = c.get(f"/api/vision/calibrations/{v}/images/residuals.jpg")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert c.get(f"/api/vision/calibrations/{v}/images/evil.jpg").status_code == 404
        assert c.get("/api/vision/calibrations/cal-19990101T000000Z").status_code == 404
        assert c.get("/api/vision/calibrations/..%2Fetc").status_code == 404


def test_activate_restores_an_older_calibration(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        v = _saved_run(c, app)
        cur = load_calibration(tmp_path / ".vision_calibration.json")
        assert cur is not None
        older = dataclasses.replace(cur, version="cal-20200101T000000Z")
        archive_calibration(tmp_path, older)
        r = c.post("/api/vision/calibrations/cal-20200101T000000Z/activate",
                   json={"expect_image_size": list(cur.image_size or ())})
        assert r.status_code == 200, r.text
        assert c.get("/api/vision/status").json()["calibration"] == "cal-20200101T000000Z"
        back = load_calibration(tmp_path / ".vision_calibration.json")
        assert back is not None and back.version == "cal-20200101T000000Z"
        rows = {x["version"]: x["active"] for x in c.get("/api/vision/calibrations").json()}
        assert rows == {v: False, "cal-20200101T000000Z": True}


def test_activate_refuses_another_photo_size(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        v = _saved_run(c, app)
        r = c.post(f"/api/vision/calibrations/{v}/activate", json={"expect_image_size": [1, 1]})
        assert r.status_code == 409 and "1x1" in r.json()["detail"]
        assert c.post("/api/vision/calibrations/cal-19990101T000000Z/activate",
                      json={}).status_code == 404


def test_startup_backfills_the_calibration_in_use(tmp_path: Path) -> None:
    # Real 2026-10-26 files: the calibration in use predates the history.
    import shutil
    import time

    fix = Path(__file__).parent / "fixtures" / "calibration_history"
    shutil.copy(fix / "vision_calibration_20261026.json", tmp_path / ".vision_calibration.json")
    shutil.copy(fix / "autocal_last_sweep_20261026.json", tmp_path / ".autocal_last_sweep.json")
    app = _app(tmp_path)
    with TestClient(app) as c:
        deadline = time.monotonic() + 10
        rows: list = []
        while time.monotonic() < deadline:
            rows = c.get("/api/vision/calibrations").json()
            if rows and rows[0]["archived"]:
                break
            time.sleep(0.05)
        assert rows[0]["version"] == "cal-20261026T192538Z" and rows[0]["archived"]
        d = c.get("/api/vision/calibrations/cal-20261026T192538Z").json()
        assert d["report"]["n_views"] == 14
