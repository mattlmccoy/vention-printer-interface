"""Install-independent jobs/experiments root resolution (the recurring wrong-directory fix)."""

from pathlib import Path

from vention_printer_interface.paths_config import (
    PathsConfig,
    config_path,
    load_persistent_paths,
    resolve_experiments_root,
    resolve_jobs_root,
    save_persistent_paths,
)


def test_persistent_paths_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "paths.json"
    save_persistent_paths(PathsConfig(jobs_root=Path("/hot"), experiments_root=Path("/runs")), p)
    got = load_persistent_paths(p)
    assert got.jobs_root == Path("/hot")
    assert got.experiments_root == Path("/runs")


def test_load_absent_or_malformed_is_empty(tmp_path: Path) -> None:
    assert load_persistent_paths(tmp_path / "nope.json") == PathsConfig()
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert load_persistent_paths(bad) == PathsConfig()


def test_config_path_honors_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "vention-printer-interface" / "paths.json"


def test_jobs_root_priority_cli_env_config_shared_fallback(tmp_path: Path) -> None:
    shared, fb = tmp_path / "shared", tmp_path / "backend" / "jobs"
    # cli wins over everything, and is never a fallback
    r = resolve_jobs_root(cli="/cli", env="/env", config=Path("/cfg"), shared=shared,
                          shared_exists=True, fallback=fb)
    assert (r.path, r.source, r.is_fallback) == (Path("/cli"), "cli", False)
    # env next
    r = resolve_jobs_root(cli=None, env="/env", config=Path("/cfg"), shared=shared,
                          shared_exists=True, fallback=fb)
    assert (r.source, r.path) == ("env", Path("/env"))
    # then the persistent config (the durable fix — survives reinstalls)
    r = resolve_jobs_root(cli=None, env=None, config=Path("/cfg"), shared=shared,
                          shared_exists=True, fallback=fb)
    assert (r.source, r.path) == ("config", Path("/cfg"))
    # then the script-relative shared Hot Folder, only when it exists
    r = resolve_jobs_root(cli=None, env=None, config=None, shared=shared,
                          shared_exists=True, fallback=fb)
    assert (r.source, r.is_fallback) == ("shared", False)


def test_jobs_root_fallback_is_flagged_loudly(tmp_path: Path) -> None:
    fb = tmp_path / "backend" / "jobs"
    r = resolve_jobs_root(cli=None, env=None, config=None, shared=tmp_path / "shared",
                          shared_exists=False, fallback=fb)
    assert (r.path, r.source, r.is_fallback) == (fb, "fallback", True)


def test_experiments_root_priority_and_fallback(tmp_path: Path) -> None:
    default = tmp_path / "cwd" / "experiments"
    r = resolve_experiments_root
    assert r(cli="/c", env="/e", config=Path("/g"), default=default).source == "cli"
    assert r(cli=None, env="/e", config=Path("/g"), default=default).source == "env"
    assert r(cli=None, env=None, config=Path("/g"), default=default).source == "config"
    fb = r(cli=None, env=None, config=None, default=default)
    assert (fb.path, fb.is_fallback) == (default, True)


def test_health_surfaces_paths_and_flags_fallback(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))  # isolate the persistent config
    monkeypatch.delenv("VPI_JOBS_ROOT", raising=False)
    monkeypatch.delenv("VPI_EXPERIMENTS_ROOT", raising=False)
    app = create_app(backend="none", experiments_root=tmp_path / "runs", poll_interval_s=0.05)
    with TestClient(app) as c:
        paths = c.get("/api/health").json()["paths"]
        # experiments came from the explicit arg (cli) -> not a fallback; jobs has no config here so
        # it falls back on CI/dev-without-Dropbox and is flagged loudly.
        assert paths["experiments_root"] == str(tmp_path / "runs")
        assert paths["experiments_root_is_fallback"] is False
        assert "jobs_root_is_fallback" in paths


def test_put_config_paths_persists_and_repoints_jobs_live(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app
    from vention_printer_interface.paths_config import config_path, load_persistent_paths

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    hot = tmp_path / "hotfolder"
    hot.mkdir()
    app = create_app(backend="none", experiments_root=tmp_path / "runs", poll_interval_s=0.05)
    with TestClient(app) as c:
        r = c.put("/api/config/paths", json={"jobs_root": str(hot)})
        assert r.status_code == 200
        assert r.json()["jobs_root"] == str(hot)
        assert r.json()["jobs_root_is_fallback"] is False
        # persisted to the install-independent config, and the live JobStore was re-pointed
        assert load_persistent_paths(config_path()).jobs_root == hot
        assert app.state.jobs.roots == [hot]
        # a non-existent dir is rejected
        bad = c.put("/api/config/paths", json={"jobs_root": str(tmp_path / "nope")})
        assert bad.status_code == 400
        # setting a different experiments root asks for a restart
        (tmp_path / "runs2").mkdir()
        er = c.put("/api/config/paths", json={"experiments_root": str(tmp_path / "runs2")})
        assert er.json()["restart_required"] is True
