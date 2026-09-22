"""API tests for /api/config/timing (live-tunable + persisted print pacing)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # isolate the persisted config
    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.2,
                     print_min_wait_s=0.25, print_poll_interval_s=0.2)
    with TestClient(app) as c:
        yield c


def test_get_reports_current_and_defaults(client: TestClient) -> None:
    r = client.get("/api/config/timing").json()
    assert r["print_min_wait_s"] == 0.25
    assert r["print_poll_interval_s"] == 0.2
    assert r["defaults"] == {"print_min_wait_s": 0.25, "print_poll_interval_s": 0.2}


def test_put_applies_live_and_persists(client: TestClient, tmp_path: Path) -> None:
    r = client.put("/api/config/timing",
                   json={"print_min_wait_s": 0.12, "print_poll_interval_s": 0.08},
                   headers={"X-VPI-Client": "1"})
    assert r.status_code == 200
    assert r.json()["print_min_wait_s"] == 0.12
    assert r.json()["print_poll_interval_s"] == 0.08
    # reflected on a fresh GET (live)
    assert client.get("/api/config/timing").json()["print_min_wait_s"] == 0.12
    # persisted to the isolated config dir
    assert (tmp_path / "cfg" / "vention-printer-interface" / "timing.json").exists()


def test_put_partial_only_changes_one(client: TestClient) -> None:
    client.put("/api/config/timing", json={"print_min_wait_s": 0.1},
               headers={"X-VPI-Client": "1"})
    r = client.get("/api/config/timing").json()
    assert r["print_min_wait_s"] == 0.1
    assert r["print_poll_interval_s"] == 0.2  # unchanged


def test_put_out_of_range_is_400(client: TestClient) -> None:
    assert client.put("/api/config/timing", json={"print_poll_interval_s": 0.001},
                      headers={"X-VPI-Client": "1"}).status_code == 400
    assert client.put("/api/config/timing", json={"print_min_wait_s": 99},
                      headers={"X-VPI-Client": "1"}).status_code == 400
