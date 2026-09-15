"""API tests for /api/analysis/{run}/dimensional (Lane A, Task 4).

Uses FastAPI's TestClient with a real recorded-run dir (dot fixture + sidecar + manifest)
built under the app's experiments_root.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import cv2
import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app

FX = Path(__file__).parent.parent / "analysis" / "fixtures" / "first-good-test"
FIXTURE_PX_PER_MM = 125.98425196850394
FIXTURE_MM_PER_PX = 1.0 / FIXTURE_PX_PER_MM


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    exp = tmp_path / "exp"
    exp.mkdir(parents=True)
    app = create_app(
        backend="none",
        experiments_root=exp,
        poll_interval_s=0.05,
        print_min_wait_s=0.1,
        print_step_timeout_s=5.0,
    )
    with TestClient(app) as c:
        yield c, exp


def _make_run(exp: Path, name: str, *, with_capture: bool = True) -> Path:
    run = exp / name
    if not with_capture:
        run.mkdir(parents=True)
        return run
    d = run / "vision" / "layer_0001"
    d.mkdir(parents=True)
    dot = cv2.imread(str(FX / "dot_roi.png"))
    cv2.imwrite(str(d / "post_jet.png"), dot)
    sidecar = {
        "layer": 1,
        "stage": "post_jet",
        "registered_space": {"mm_per_px": FIXTURE_MM_PER_PX},
    }
    (d / "post_jet.json").write_text(json.dumps(sidecar), encoding="utf-8")
    manifest = [
        {
            "run_id": name,
            "layer": 1,
            "stage": "post_jet",
            "registered": "vision/layer_0001/post_jet.png",
        }
    ]
    (run / "vision" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run


def test_get_before_run_is_not_run(env: tuple[TestClient, Path]) -> None:
    client, exp = env
    _make_run(exp, "run_a")
    resp = client.get("/api/analysis/run_a/dimensional")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_run"


def test_post_then_get_ok(env: tuple[TestClient, Path]) -> None:
    client, exp = env
    run = _make_run(exp, "run_b")
    w = cv2.imread(str(FX / "dot_roi.png")).shape[1]
    h = cv2.imread(str(FX / "dot_roi.png")).shape[0]

    post = client.post(
        "/api/analysis/run_b/dimensional",
        json={"stage": "post_jet", "rois": {"dot": [0, 0, w, h]}},
    )
    assert post.status_code == 200
    body = post.json()
    assert body["status"] == "ok"
    assert body["features"]["dot"]["num_blobs"] == 25.0
    assert body["compensation"]["scale_x"] > 1.0

    # Persisted + served by GET.
    assert (run / "analysis" / "dimensional.json").exists()
    get = client.get("/api/analysis/run_b/dimensional")
    assert get.status_code == 200
    assert get.json()["status"] == "ok"


def test_post_without_body_uses_defaults(env: tuple[TestClient, Path]) -> None:
    client, exp = env
    # No capture -> honest no_capture report, still 200 (a report, not an error).
    _make_run(exp, "run_c", with_capture=False)
    resp = client.post("/api/analysis/run_c/dimensional")
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_capture"


def test_post_with_circle_uses_circle_source(env: tuple[TestClient, Path]) -> None:
    # A marked outer circle supplies px_per_mm + ROIs on its own (roi_source == "circle").
    # Radius is chosen from the fixture calibration so 2R/100 == FIXTURE_PX_PER_MM.
    client, exp = env
    _make_run(exp, "run_circle")
    img = cv2.imread(str(FX / "dot_roi.png"))
    h, w = img.shape[0], img.shape[1]
    radius_px = FIXTURE_PX_PER_MM * 100.0 / 2.0

    resp = client.post(
        "/api/analysis/run_circle/dimensional",
        json={
            "stage": "post_jet",
            "circle": {"cx_px": w / 2.0, "cy_px": h / 2.0, "radius_px": radius_px},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["roi_source"] == "circle"
    assert body["px_per_mm"] == 2.0 * radius_px / 100.0


def test_traversal_run_name_never_succeeds(env: tuple[TestClient, Path]) -> None:
    # The {run} path segment cannot carry raw slashes, so an encoded traversal is
    # normalized/rejected by the router or the shared run-path guard. Either way it must
    # never return a 2xx (the security-relevant property). The exact 400 of the guard is
    # covered by the shared _resolve_run_dir tests.
    client, _exp = env
    for path in (
        "/api/analysis/..%2f..%2fetc/dimensional",
        "/api/analysis/..%2fescape/dimensional",
    ):
        assert client.post(path).status_code >= 400
        assert client.get(path).status_code >= 400


def test_unknown_run_is_404(env: tuple[TestClient, Path]) -> None:
    client, _exp = env
    assert client.post("/api/analysis/does_not_exist/dimensional").status_code == 404
    assert client.get("/api/analysis/does_not_exist/dimensional").status_code == 404
