"""Install-independent, UI-tunable print-timing knobs.

``print_min_wait_s`` (per-step floor) and ``print_poll_interval_s`` (controller poll during a print)
govern how tightly the choreography paces between moves. They were CLI/plist-only, so tuning them
meant editing launchd and reloading. This persists them at a fixed user-home path (like
``paths_config``) so the Settings UI can change them live and have it survive restarts. When set,
the persisted value OVERRIDES the CLI/plist default (the UI is the source of truth for these).

Bounds are sanity floors/ceilings only — an out-of-range value is dropped (treated as unset) rather
than trusted, so a corrupt file can never brick print pacing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "vention-printer-interface"
_MIN_WAIT_RANGE = (0.0, 5.0)      # seconds; 0 = no floor, 5 s is already very slow
_POLL_RANGE = (0.02, 1.0)         # seconds; below 20 ms hammers the controller


def timing_config_path() -> Path:
    """Fixed, install-independent config location (honors ``XDG_CONFIG_HOME``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME / "timing.json"


@dataclass(frozen=True)
class TimingConfig:
    print_min_wait_s: float | None = None
    print_poll_interval_s: float | None = None


def _in_range(v: object, lo: float, hi: float) -> float | None:
    return float(v) if isinstance(v, int | float) and lo <= float(v) <= hi else None


def load_timing(path: Path | None = None) -> TimingConfig:
    """Read the persistent timing config; absent/malformed/out-of-range yields unset fields."""
    p = path or timing_config_path()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return TimingConfig()
    if not isinstance(data, dict):
        return TimingConfig()
    return TimingConfig(
        print_min_wait_s=_in_range(data.get("print_min_wait_s"), *_MIN_WAIT_RANGE),
        print_poll_interval_s=_in_range(data.get("print_poll_interval_s"), *_POLL_RANGE),
    )


def save_timing(cfg: TimingConfig, path: Path | None = None) -> Path:
    """Write the persistent timing config (creating the directory). Returns the file path."""
    p = path or timing_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"print_min_wait_s": cfg.print_min_wait_s,
            "print_poll_interval_s": cfg.print_poll_interval_s}
    p.write_text(json.dumps({k: v for k, v in body.items() if v is not None}, indent=2))
    return p
