"""Assemble a run's recorded stills into an animated-GIF timelapse (#4).

Two sources:
  * SCIENCE — the per-layer registered stills (``vision/manifest.json`` -> ``vision/layer_XXXX/
    <stage>.webp``), ordered by layer for one stage. The metrology timelapse.
  * OVERVIEW — time-ordered wide-view frames grabbed on a timer during the recording
    (``overview/NNNNNN.webp``), for a whole-print timelapse of the streaming overview camera.

GIF plays inline in any ``<img>`` with no codec dependency — deliberately chosen over MP4 so it
works regardless of the OpenCV/ffmpeg build the operator happens to have.
"""

from __future__ import annotations

import io
from pathlib import Path

from vention_printer_interface.vision.store import read_manifest

CAPTURE_STAGES = ("pre_jet", "post_jet", "post_heat")
_FRAME_EXTS = (".webp", ".png", ".jpg", ".jpeg")


def _encode_gif(
    frames: list[Path], fps: float, max_size: tuple[int, int] | None = None
) -> bytes | None:
    """Encode ordered image paths into a looping GIF, optionally bounded for playback memory.

    The source stills remain untouched at full resolution. Bounding only the assembled preview is
    essential for overview runs: retaining hundreds of decoded 4K frames can consume gigabytes.
    """
    from PIL import Image

    if not frames:
        return None
    imgs: list[Image.Image] = []
    size: tuple[int, int] | None = None
    for p in frames:
        with Image.open(p) as opened:
            im = opened.convert("RGB")
        if size is None and max_size is not None:
            im.thumbnail(max_size, Image.Resampling.LANCZOS)
        if size is None:
            size = im.size
        elif im.size != size:
            im = im.resize(size, Image.Resampling.LANCZOS)
        imgs.append(im)
    duration_ms = max(1, round(1000.0 / max(fps, 0.1)))
    buf = io.BytesIO()
    imgs[0].save(
        buf, format="GIF", save_all=True, append_images=imgs[1:],
        duration=duration_ms, loop=0, disposal=2,
    )
    return buf.getvalue()


def overview_frames(base: Path) -> list[Path]:
    """The run's overview timelapse frames (``overview/*``), time-ordered by zero-padded name."""
    d = Path(base) / "overview"
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _FRAME_EXTS)


def build_overview_timelapse_gif(base: Path, fps: float = 10.0) -> bytes | None:
    """Encode a playback-sized overview GIF. Full-resolution source frames remain on disk."""
    return _encode_gif(overview_frames(base), fps, max_size=(640, 360))


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
    """Encode the run's ``stage`` (science) stills into a looping GIF. None when there are none."""
    return _encode_gif(timelapse_frames(base, stage), fps)
