"""API tests for /api/motion/backlash/history (persisted cal review)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.control.backlash_history import save_backlash


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    # seed two saved cals under the experiments root's .calibrations dir
    hist = tmp_path / ".calibrations"
    save_backlash(hist, {"axis": 1, "recommended_mm": 0.1,
                         "positions": [{"ref_mm": 15.0, "reps_mm": [-0.1]}]})
    save_backlash(hist, {"axis": 2, "recommended_mm": 2.0, "positions": []})
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        yield c


def test_history_lists_saved_cals(client: TestClient) -> None:
    cals = client.get("/api/motion/backlash/history").json()["calibrations"]
    assert len(cals) == 2
    assert {c["axis"] for c in cals} == {1, 2}
    rid = next(c["id"] for c in cals if c["axis"] == 1)
    full = client.get(f"/api/motion/backlash/history/{rid}").json()
    assert full["recommended_mm"] == 0.1 and full["positions"][0]["ref_mm"] == 15.0


def test_history_unknown_id_404(client: TestClient) -> None:
    assert client.get("/api/motion/backlash/history/nope").status_code == 404
