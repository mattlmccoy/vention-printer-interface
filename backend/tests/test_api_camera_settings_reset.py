"""DELETE /api/vision/settings/{role}: drop a role's saved capture overrides (resolution / fps /
format / exposure) so it returns to the built-in defaults -- the server half of "reset camera
settings to default"."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=tmp_path, uvc_backend=None)
    with TestClient(app) as c:
        yield c


def test_reset_role_returns_to_defaults_and_leaves_the_other(client: TestClient) -> None:
    defaults = client.get("/api/vision/settings").json()
    client.put("/api/vision/settings", json={
        "science": {"resolution": [1920, 1080], "fps": 5, "format": "MJPG", "exposure": 300},
        "overview": {"fps": 10},
    })
    changed = client.get("/api/vision/settings").json()
    assert changed["science"] != defaults["science"]
    r = client.delete("/api/vision/settings/science")
    assert r.status_code == 200
    assert r.json()["science"] == defaults["science"]
    assert r.json()["overview"] == changed["overview"]  # untouched
    # persisted: a fresh read agrees
    assert client.get("/api/vision/settings").json()["science"] == defaults["science"]


def test_reset_unknown_role_is_400(client: TestClient) -> None:
    assert client.delete("/api/vision/settings/thermal").status_code == 400
