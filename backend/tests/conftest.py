"""Test configuration: hardware tests are skipped unless --hardware is passed."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path_factory: pytest.TempPathFactory,
                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Point XDG_CONFIG_HOME at a throwaway dir for every test, so the persistent paths/timing
    config (``~/.config/vention-printer-interface/*.json``) can never leak a developer's or the
    operator's real settings into a test (e.g. a Print-pacing value written from the live UI). A
    test that needs its own config still overrides this via its own monkeypatch.setenv."""
    cfg = tmp_path_factory.mktemp("xdg_config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(Path(cfg)))
    # Never enumerate the developer's real mounted drives during a test — run listings/resolution
    # must see only the test's own experiments root (the cross-drive union is unit-tested directly).
    monkeypatch.setenv("VPI_DISABLE_DRIVE_SCAN", "1")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run tests that need a reachable MachineMotion controller",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs --hardware and a reachable controller")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
