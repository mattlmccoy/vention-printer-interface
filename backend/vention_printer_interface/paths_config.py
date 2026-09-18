"""Install-INDEPENDENT resolution of the jobs + experiments (runs) roots.

The recurring "wrong jobs/runs directory" bug: the operator resolved these paths relative to its
install location — a script-relative Hot Folder guess and ``CWD/experiments`` — so a reinstall or a
fresh clone to a new directory (e.g. the update flow cloning to ``$HOME/vention-printer-interface``)
silently pointed them at empty local folders, losing sight of the real data.

The durable fix, here:
  * a config file at a FIXED user-home path (``~/.config/vention-printer-interface/paths.json``)
    that EVERY clone reads regardless of where it lives, so a reinstall can't move the data out from
    under the operator, and
  * pure resolvers that report their SOURCE and whether they fell back to an install-local default,
    so a fallback is surfaced loudly (health payload + UI banner) instead of failing silently.

Priority for each root: explicit ``--flag`` (cli) > ``VPI_*`` env > persistent config > a
best-effort default (script-relative Hot Folder for jobs / ``CWD/experiments`` for runs). Only that
last default sets ``is_fallback``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "vention-printer-interface"


def config_path() -> Path:
    """The fixed, install-independent config location (honors ``XDG_CONFIG_HOME``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME / "paths.json"


@dataclass(frozen=True)
class PathsConfig:
    jobs_root: Path | None = None
    experiments_root: Path | None = None


def load_persistent_paths(path: Path | None = None) -> PathsConfig:
    """Read the persistent paths config; an absent/malformed file yields empty (both None)."""
    p = path or config_path()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return PathsConfig()
    if not isinstance(data, dict):
        return PathsConfig()
    jr = data.get("jobs_root")
    er = data.get("experiments_root")
    return PathsConfig(
        jobs_root=Path(jr) if isinstance(jr, str) and jr.strip() else None,
        experiments_root=Path(er) if isinstance(er, str) and er.strip() else None,
    )


def save_persistent_paths(cfg: PathsConfig, path: Path | None = None) -> Path:
    """Write the persistent paths config (creating the directory). Returns the file path."""
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "jobs_root": str(cfg.jobs_root) if cfg.jobs_root else None,
                "experiments_root": str(cfg.experiments_root) if cfg.experiments_root else None,
            },
            indent=2,
        )
    )
    return p


@dataclass(frozen=True)
class ResolvedRoot:
    path: Path
    source: str  # "cli" | "env" | "config" | "shared" | "fallback"
    is_fallback: bool


def resolve_jobs_root(
    *,
    cli: str | os.PathLike[str] | None,
    env: str | None,
    config: Path | None,
    shared: Path,
    shared_exists: bool,
    fallback: Path,
) -> ResolvedRoot:
    """Pick the sliced-jobs folder, reporting its source. Only the install-local ``fallback`` is
    flagged as a fallback — everything else is an operator-intended location."""
    if cli:
        return ResolvedRoot(Path(cli), "cli", False)
    if env:
        return ResolvedRoot(Path(env), "env", False)
    if config is not None:
        return ResolvedRoot(Path(config), "config", False)
    if shared_exists:
        return ResolvedRoot(Path(shared), "shared", False)
    return ResolvedRoot(Path(fallback), "fallback", True)


def resolve_experiments_root(
    *,
    cli: str | os.PathLike[str] | None,
    env: str | None,
    config: Path | None,
    default: Path,
) -> ResolvedRoot:
    """Pick the experiments (runs) folder, reporting its source. The install-local ``default``
    (``CWD/experiments``) is the only fallback."""
    if cli:
        return ResolvedRoot(Path(cli), "cli", False)
    if env:
        return ResolvedRoot(Path(env), "env", False)
    if config is not None:
        return ResolvedRoot(Path(config), "config", False)
    return ResolvedRoot(Path(default), "fallback", True)
