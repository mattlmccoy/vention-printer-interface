"""The operator reports which commit it is running, so an update is visible even while the
semver is unchanged (it sat at 0.10.4 across ~40 merged PRs)."""

import subprocess
from pathlib import Path

from vention_printer_interface.build_info import git_short_sha


def test_short_sha_from_git() -> None:
    def ok(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="66b787c\n")

    assert git_short_sha(Path("."), run=ok) == "66b787c"


def test_none_when_not_a_git_checkout_or_git_missing() -> None:
    def fail(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=128, stdout="")

    def boom(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        raise OSError("git not installed")

    assert git_short_sha(Path("."), run=fail) is None
    assert git_short_sha(Path("."), run=boom) is None


def test_health_reports_build(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    with TestClient(create_app(backend="none", experiments_root=tmp_path)) as c:
        body = c.get("/api/health").json()
    assert "build" in body
    assert body["build"] is None or (isinstance(body["build"], str) and body["build"].isalnum())
