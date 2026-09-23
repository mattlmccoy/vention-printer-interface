"""Is the most recent science capture settled -- may the print leave the capture pose?

The print used to dwell a fixed capture_hold_s at the pose with no acknowledgement. When the
browser opens the science camera on demand at full resolution (the Windows lightweight camera mode,
~1-3 s) that can end before the still is taken, so the carriage would move mid-capture. The print
now also waits (step "await_capture") until the operator has STORED that capture, up to a timeout.
"""

from __future__ import annotations

from typing import Any

# Longest the print holds for one still before continuing and recording a miss.
CAPTURE_TIMEOUT_S = 10.0


def capture_settled(
    request: dict[str, Any] | None, done_seq: int, *, consumer_alive: bool
) -> bool:
    """True when there is nothing to wait for: no capture requested, this capture is already
    stored (or definitively failed), or nobody is able to take it (no live browser capture
    client and no operator camera) -- a print without cameras must never be held."""
    if request is None:
        return True
    if done_seq >= int(request.get("seq", 0)):
        return True
    return not consumer_alive
