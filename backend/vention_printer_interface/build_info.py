"""Which commit the operator is running.

The semver in ``__init__.__version__`` is bumped by hand and can lag many merges behind (it sat at
0.10.4 across ~40 merged PRs), so the operator also reports its git short SHA. The status bar shows
it next to the console's build id, which makes every operator update visible even when the version
number is unchanged.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def git_short_sha(
    repo_dir: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    """Short SHA of ``repo_dir``'s checkout, or None when it isn't a git checkout, git is missing,
    or the call fails. Never raises."""
    try:
        proc = run(
            ["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except Exception:  # noqa: BLE001 - build info is best-effort; health must never fail
        return None
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and sha.isalnum() else None


@lru_cache(maxsize=1)
def operator_build() -> str | None:
    """The running operator's commit, resolved once per process (an upgrade restarts it)."""
    return git_short_sha(_PACKAGE_DIR)


__all__ = ["git_short_sha", "operator_build"]

