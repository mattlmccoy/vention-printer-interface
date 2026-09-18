"""Capture event contract: the labels VisionService listens for on EventLog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CAPTURE_LABELS: tuple[str, ...] = ("capture:pre_jet", "capture:post_jet", "capture:post_heat")


def label_to_stage(label: str) -> str | None:
    """Return the stage name (e.g. "post_jet") for a capture label, else None."""
    if label not in CAPTURE_LABELS:
        return None
    return label.split("capture:", 1)[1]


@dataclass(frozen=True)
class CaptureRequest:
    """A single stage-capture request, queued by the non-blocking EventLog sink."""

    layer: int
    stage: str
    host_timestamp_ns: int
    axis_positions_mm: dict[str, float] = field(default_factory=dict)
    job: dict[str, Any] = field(default_factory=dict)
    # The 1-based PRINTING layer index (excludes precoats), for the CAD-slice lookup + layer labels;
    # None for a non-printing capture. The `layer` above is the absolute layer_no.
    print_layer: int | None = None
