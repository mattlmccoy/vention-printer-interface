"""In-process axis settle: wait until an axis reports motion complete AND holds position.

The pure helpers (``settle_update`` / ``settle_ready``) are ported verbatim from the validated
offline ``scripts/piston_sweep.py`` so the operator's in-process settle behaves identically to the
sweep tooling. ``settle`` polls a snapshot-reader (the controller ``snapshot()`` in production, a
scripted sequence in tests) and is fully injectable (clock + sleep) so it is unit-tested without
hardware
or real time.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

READOUT_MM = 0.1  # MM2 build/feed piston position readout quantum: positions land on a 0.1 mm grid


def settle_update(
    window: list[float], pos: float, *, complete: bool, tol: float = READOUT_MM, need: int = 3
) -> tuple[list[float], float | None]:
    """Fold one telemetry sample into the settle window and decide if the axis is at rest. Settled
    once motion is complete AND the last ``need`` positions span no more than ``tol`` (one encoder
    count), so a position that flickers by a single 0.1 mm count at rest still latches. While motion
    is incomplete the window resets, so a pre-completion reading can't count."""
    if not complete:
        return [], None
    window = (window + [pos])[-need:]
    if len(window) >= need and (max(window) - min(window)) <= tol + 1e-9:
        return window, window[-1]
    return window, None


def settle_ready(saw_incomplete: bool, elapsed_s: float, start_grace_s: float) -> bool:
    """Whether settle may start ACCEPTING a completed+stable reading. Guards the MM2 race where
    motion_complete is still True from the PREVIOUS move for a few polls after a new move is issued
    (accepting then would return the stale pre-move position). Ready once the move registered
    (motion_complete went False) OR the start grace elapsed (a no-op move already at target never
    goes incomplete, so don't wait forever)."""
    return saw_incomplete or elapsed_s >= start_grace_s


def settle(
    read_sample: Callable[[], dict[str, Any]],
    axis: int,
    *,
    poll_s: float = 0.05,
    stable_needed: int = 3,
    timeout_s: float = 30.0,
    tol: float = READOUT_MM,
    start_grace_s: float = 0.4,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Poll ``read_sample`` (a controller snapshot dict) until ``axis`` is complete and at rest;
    return the settled position. Waits for the move to REGISTER before accepting, so a stale
    'still complete from the last move' reading can't return the pre-move position. Raises
    ``TimeoutError`` if the axis never settles within ``timeout_s``."""
    window: list[float] = []
    saw_incomplete = False
    complete_ever = False
    seen: list[float] = []
    key = str(axis)
    t0 = now()
    while now() - t0 < timeout_s:
        tel = (read_sample().get("telemetry") or {})
        complete = bool((tel.get("motion_complete") or {}).get(key))
        pos = (tel.get("positions") or {}).get(key)
        complete_ever = complete_ever or complete
        if not complete:
            saw_incomplete = True
        ready = settle_ready(saw_incomplete, now() - t0, start_grace_s)
        if ready and pos is not None:
            seen = (seen + [float(pos)])[-8:]
            window, settled = settle_update(
                window, float(pos), complete=complete, tol=tol, need=stable_needed
            )
            if settled is not None:
                return settled
        elif pos is not None:
            window = []  # move not registered yet — drop pre-move samples (no false "stable")
        sleep(poll_s)
    raise TimeoutError(
        f"axis {axis} did not settle within {timeout_s}s "
        f"(motion_complete seen: {complete_ever}; last positions: {seen})"
    )
