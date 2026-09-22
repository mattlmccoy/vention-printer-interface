"""API tests for /api/plots/* seaborn exports (skipped without the `plots` extra).

GET endpoints render server-side data (live backlash session, a run's layer_accuracy.csv);
POST endpoints render client-held data (validation residuals, piston-sweep rows).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")  # endpoints 503 without the extra; skip the whole file in lean CI

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vention_printer_interface.api.app import create_app  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\n"


class _FakeRoutine:
    """Stands in for a BacklashRoutine: exposes just the snapshot() the plot endpoint reads."""

    def __init__(self, snap: dict) -> None:
        self._snap = snap

    def snapshot(self) -> dict:
        return self._snap


@pytest.fixture
def app_and_client(tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient]]:
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield app, c


def test_backlash_plot_404_when_no_session(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    r = client.get("/api/plots/backlash.png")
    assert r.status_code == 404


def test_backlash_plot_from_completed_session(app_and_client: tuple[FastAPI, TestClient]) -> None:
    app, client = app_and_client
    app.state.backlash_routine = _FakeRoutine({
        "state": "done",
        "result": {
            "axis": 1, "recommended_mm": 0.1,
            "positions": [
                {"ref_mm": 15.0, "reps_mm": [-0.1, -0.1, 0.0], "backlash_median_mm": -0.1},
                {"ref_mm": 30.0, "reps_mm": [0.0, -0.1, -0.1], "backlash_median_mm": -0.1},
            ],
        },
        "partial_positions": [],
    })
    r = client.get("/api/plots/backlash.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == _PNG
    assert "attachment" in r.headers.get("content-disposition", "")


def test_backlash_plot_pdf(app_and_client: tuple[FastAPI, TestClient]) -> None:
    app, client = app_and_client
    app.state.backlash_routine = _FakeRoutine({
        "state": "running", "result": None,
        "partial_positions": [
            {"ref_mm": 15.0, "reps_mm": [-0.1, 0.0], "backlash_median_mm": -0.05},
        ],
    })
    r = client.get("/api/plots/backlash.pdf")
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


def test_backlash_plot_bad_format(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    r = client.get("/api/plots/backlash.svg")
    assert r.status_code == 400


def _write_run_csv(root: Path, run: str) -> None:
    d = root / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "layer_accuracy.csv").write_text(
        "layer,phase,commanded_mm,actual_mm,deviation_mm,commanded_cum_mm,actual_cum_mm\n"
        "1,thin_precoat,0.6,0.6,0.0,0.6,0.6\n"
        "2,printing,0.2,0.2,0.0,0.8,0.8\n"
        "3,printing,0.2,0.3,0.1,1.0,1.1\n"
    )


def test_layer_accuracy_plot(app_and_client: tuple[FastAPI, TestClient], tmp_path: Path) -> None:
    app, client = app_and_client
    _write_run_csv(tmp_path, "20260101_000000_run")
    r = client.get("/api/plots/layer-accuracy/20260101_000000_run.png")
    assert r.status_code == 200
    assert r.content[:8] == _PNG


def test_layer_accuracy_plot_404_missing_run(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    r = client.get("/api/plots/layer-accuracy/nope.png")
    assert r.status_code in (400, 404)


def test_validation_plot_post(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    r = client.post(
        "/api/plots/validation.png",
        json={"residuals_mm": [0.01, 0.03, 0.008, 0.045, 0.02], "target_mm": 0.05},
    )
    assert r.status_code == 200
    assert r.content[:8] == _PNG


def test_sweep_plot_post(app_and_client: tuple[FastAPI, TestClient]) -> None:
    _, client = app_and_client
    rows = [
        {"commanded_mm": 10.0, "deviation_mm": 0.0, "direction": "down"},
        {"commanded_mm": 11.0, "deviation_mm": 0.0, "direction": "down"},
        {"commanded_mm": 11.0, "deviation_mm": -0.1, "direction": "up"},
    ]
    r = client.post("/api/plots/sweep.png", json={"rows": rows})
    assert r.status_code == 200
    assert r.content[:8] == _PNG


def test_plot_503_when_extra_missing(
    app_and_client: tuple[FastAPI, TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from vention_printer_interface.analysis import plotting

    monkeypatch.setattr(plotting, "plots_available", lambda: False)
    _, client = app_and_client
    r = client.post("/api/plots/validation.png", json={"residuals_mm": [0.01], "target_mm": 0.05})
    assert r.status_code == 503
