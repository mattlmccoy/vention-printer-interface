"""Assemble a run's per-layer science stills into an animated-GIF timelapse (#4).

The registered per-layer stills recorded during a print (``vision/manifest.json`` ->
``vision/layer_XXXX/<stage>.webp``) are ordered by layer for one stage and encoded as a looping
GIF. GIF plays inline in any ``<img>`` with no codec dependency — deliberately chosen over MP4 so
it works regardless of the OpenCV/ffmpeg build the operator happens to have.
"""

from __future__ import annotations

import io
from pathlib import Path

from vention_printer_interface.vision.store import read_manifest

CAPTURE_STAGES = ("pre_jet", "post_jet", "post_heat")


def timelapse_frames(base: Path, stage: str) -> list[Path]:
    """Registered still paths for ``stage`` in this run, ordered by absolute layer_no."""
    records = [
        r for r in read_manifest(base)
        if r.get("stage") == stage and r.get("registered")
    ]
    records.sort(key=lambda r: int(r.get("layer") or 0))
    frames: list[Path] = []
    for r in records:
        p = Path(base) / str(r["registered"])
        if p.is_file():
            frames.append(p)
    return frames


def best_stage(base: Path) -> str | None:
    """The stage with the most recorded frames (post_heat preferred), or None if there are none."""
    counts = {s: len(timelapse_frames(base, s)) for s in CAPTURE_STAGES}
    present = [s for s in ("post_heat", "post_jet", "pre_jet") if counts.get(s, 0) > 0]
    if not present:
        return None
    return max(present, key=lambda s: counts[s])


def build_timelapse_gif(base: Path, stage: str, fps: float = 6.0) -> bytes | None:
    """Encode the run's ``stage`` stills into a looping GIF. None when there are no frames."""
    from PIL import Image

    frames = timelapse_frames(base, stage)
    if not frames:
        return None
    imgs: list[Image.Image] = []
    size: tuple[int, int] | None = None
    for p in frames:
        im = Image.open(p).convert("RGB")
        if size is None:
            size = im.size
        elif im.size != size:
            im = im.resize(size)
        imgs.append(im)
    duration_ms = max(1, round(1000.0 / max(fps, 0.1)))
    buf = io.BytesIO()
    imgs[0].save(
        buf, format="GIF", save_all=True, append_images=imgs[1:],
        duration=duration_ms, loop=0, disposal=2,
    )
    return buf.getvalue()
