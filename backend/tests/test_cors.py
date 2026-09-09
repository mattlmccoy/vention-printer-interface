from pathlib import Path

from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app


def test_cross_origin_write_without_header_is_403(tmp_path: Path) -> None:
    app = create_app(
        backend="none", experiments_root=tmp_path, site_origin="https://mattlmccoy.github.io"
    )
    with TestClient(app) as c:
        r = c.post("/api/arm", headers={"Origin": "https://evil.example", "Host": "localhost:8020"})
        assert r.status_code == 403
        r = c.post(
            "/api/arm",
            headers={
                "Origin": "https://mattlmccoy.github.io",
                "Host": "localhost:8020",
                "X-VPI-Client": "1",
            },
        )
        assert r.status_code == 409  # passed the guard; refused by the controller (no device)
        r = c.get("/api/status", headers={"Origin": "https://evil.example", "Host": "localhost"})
        assert r.status_code == 200  # safe methods are never blocked


def test_html_is_no_store(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    app = create_app(backend="none", experiments_root=tmp_path, frontend_dist=dist)
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
