"""The console the operator serves itself at "/" must never be a stale build.

Found 2026-10-21: http://localhost:8020 on the lab Mac served console v0.10.4 (frontend/dist built
2026-09-21, gitignored, never rebuilt by `git pull` + `uv sync`) while the operator was 0.19.0.
The build now stamps dist/version.json; the operator serves the dist only when that stamp matches
its own version, and otherwise answers "/" with a page that says why and points at the current
site console.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from vention_printer_interface import __version__
from vention_printer_interface.api.app import create_app

SITE = "https://mattlmccoy.github.io"


def _dist(tmp_path: Path, stamp: dict | None) -> Path:  # type: ignore[type-arg]
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>LOCAL CONSOLE BUILD</body></html>")
    if stamp is not None:
        (dist / "version.json").write_text(json.dumps(stamp))
    return dist


def _client(tmp_path: Path, dist: Path | None, site: str | None = SITE) -> TestClient:
    return TestClient(create_app(backend="none", experiments_root=tmp_path,
                                 frontend_dist=dist or tmp_path / "no-dist", site_origin=site))


def test_a_matching_build_is_served(tmp_path: Path) -> None:
    with _client(tmp_path, _dist(tmp_path, {"version": __version__, "build": "abc1234"})) as c:
        r = c.get("/")
        assert r.status_code == 200 and "LOCAL CONSOLE BUILD" in r.text


def test_a_stale_build_is_not_served_and_says_why(tmp_path: Path) -> None:
    with _client(tmp_path, _dist(tmp_path, {"version": "0.10.4", "build": "f08c9b8"})) as c:
        r = c.get("/")
        assert r.status_code == 200 and "LOCAL CONSOLE BUILD" not in r.text
        assert "0.10.4" in r.text and __version__ in r.text
        assert f"{SITE}/vention-printer-interface/" in r.text
        assert r.headers["cache-control"] == "no-store"
        assert c.get("/assets/index-old.js").status_code == 404  # none of the stale files either


def test_a_build_without_a_version_stamp_counts_as_stale(tmp_path: Path) -> None:
    with _client(tmp_path, _dist(tmp_path, None)) as c:
        r = c.get("/")
        assert "LOCAL CONSOLE BUILD" not in r.text and "unknown" in r.text


def test_no_build_at_all_points_at_the_site_console(tmp_path: Path) -> None:
    with _client(tmp_path, None) as c:
        r = c.get("/")
        assert r.status_code == 200 and f"{SITE}/vention-printer-interface/" in r.text


def test_the_api_is_unaffected(tmp_path: Path) -> None:
    with _client(tmp_path, _dist(tmp_path, {"version": "0.10.4"})) as c:
        assert c.get("/api/health").json()["version"] == __version__
