"""Meteor RIP job folders (spec §6, jobs).

Data contract, captured from the lab hot folder on 2026-09-09
(``code/rfam-web/Hot Folder/<YYYYMMDD_HHMMSS>_<name>/``):
  job_info.json  {generated_by, job_name, slice_id, layer_count, tiff_count,
                  bbox_mm{x_mm,y_mm,z_mm}, height_mm, part_vol_mm3, dpi, bpp, compression,
                  color_plane, elapsed_sec, timestamp}
  <job_name>_Page<N>_Clr<plane>.tif   N is 1-based; mode L, BitsPerSample 2,
                                       PhotometricInterpretation 0 (WhiteIsZero: 0 = no ink), LZW.
Layer thickness is not stored: it is height_mm / layer_count (slicer default 0.1 mm).
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_PAGE_RE = re.compile(r"_Page(\d+)_Clr(\d+)\.tif{1,2}$", re.IGNORECASE)


def _remap_ink_levels(arr: np.ndarray, bpp: int, grey_levels: int) -> np.ndarray:
    """Re-map PIL's container-scaled greyscale to the printhead's usable grey-level range, for
    DISPLAY only. PIL loads a WhiteIsZero page scaled on the 4-bit container (``2**bpp - 1``): ink
    level ``k`` becomes ``255 - k*255/(2**bpp-1)``. An 8-grey-level head (Xaar Aquinox) in a 4-bit
    container therefore renders max ink (level 7) as ``7/15 ≈ 47%`` grey instead of black. This
    recovers the true ink level from the container scale, then rescales on ``grey_levels - 1`` so
    the top level renders full black (level 0 stays white). It is a no-op when
    ``grey_levels - 1 == 2**bpp - 1`` (an older job where the container equals the level count).
    Display-only: it never touches the TIFF or what MetPrint fires."""
    container_max = (1 << max(1, bpp)) - 1
    ceil = max(1, grey_levels - 1)
    level = np.rint((255.0 - arr.astype(np.float64)) * container_max / 255.0)
    disp = 255.0 - level * (255.0 / ceil)
    return np.clip(disp, 0.0, 255.0).round().astype(np.uint8)


@dataclass(frozen=True)
class JobInfo:
    dir: Path
    name: str
    layer_count: int
    layer_height_mm: float
    height_mm: float
    bbox_mm: tuple[float, float, float]
    dpi: int
    bpp: int
    grey_levels: int  # usable ink levels of the head (Aquinox = 8); the preview scales on this - 1
    timestamp: str
    pages: tuple[Path, ...]
    workflow: str = ""
    # Multipass factor the SLICER declared, if any (#7). None when job_info carries no multipass
    # field — the current Meteor RIP output does not, so this stays None until the slicer emits it.
    # NEVER invented: the print's own n_jet_passes is separate and unaffected unless the operator
    # chooses to apply this.
    slicer_multipass: int | None = None
    preview: Path | None = None
    missing_pages: list[int] = field(default_factory=list)
    _cache: dict[tuple[int, int], bytes] = field(default_factory=dict, repr=False, compare=False)

    @property
    def complete(self) -> bool:
        return not self.missing_pages and len(self.pages) == self.layer_count

    @property
    def kind(self) -> str:
        """"2D" for a flat RIP print, "3D" for a sliced part. Uses the manifest ``workflow`` when
        present (current jobs), else falls back to layer count — old jobs predate the workflow
        field, and a single-layer job is a 2D print while many layers means a 3D part."""
        if self.workflow == "rip":
            return "2D"
        if self.workflow == "slicer":
            return "3D"
        return "2D" if self.layer_count <= 1 else "3D"

    def print_settings_patch(self) -> dict[str, Any]:
        """What the job dictates: ONLY the print phase's layer COUNT.

        The slicer's ``height_mm / layer_count`` is a derived, non-standard value (e.g. 0.3013 mm),
        so selecting a job must NOT force it onto the print. The operator's selected/standard
        ``layer_thickness_mm`` is kept; ``layer_height_mm`` stays on JobInfo only for the
        informational "slicer: X mm" display.
        """
        return {"printing": {"n_layers": self.layer_count}}

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.dir),
            "name": self.name,
            "folder": self.dir.name,
            "layer_count": self.layer_count,
            "layer_height_mm": self.layer_height_mm,
            "height_mm": self.height_mm,
            "bbox_mm": {"x": self.bbox_mm[0], "y": self.bbox_mm[1], "z": self.bbox_mm[2]},
            "dpi": self.dpi,
            "bpp": self.bpp,
            "grey_levels": self.grey_levels,
            "timestamp": self.timestamp,
            "complete": self.complete,
            "missing_pages": list(self.missing_pages),
            "workflow": self.workflow,
            "kind": self.kind,
            "slicer_multipass": self.slicer_multipass,
            "has_preview": self.preview is not None,
        }


def _read_multipass(info: dict[str, Any]) -> int | None:
    """Import the slicer's declared multipass factor if job_info carries one (#7). Accepts a few
    plausible key names and returns the first that is a positive integer; None otherwise. Reads
    only what is present — the current RIP output has no such key, so this returns None for it."""
    for key in ("multipass", "jet_passes", "n_jet_passes", "passes"):
        v = info.get(key)
        if isinstance(v, bool):  # bool is an int subclass — reject it explicitly
            continue
        if isinstance(v, int) and v >= 1:
            return v
    return None


def load_job(job_dir: Path) -> JobInfo:
    info = json.loads((job_dir / "job_info.json").read_text())
    height = float(info.get("height_mm") or (info.get("bbox_mm") or {}).get("z_mm") or 0.0)
    pages: dict[int, Path] = {}
    for f in job_dir.iterdir():
        m = _PAGE_RE.search(f.name)
        if m and int(m.group(2)) == int(info.get("color_plane", 1)):
            pages[int(m.group(1))] = f
    # Slice jobs carry layer_count. A RIP (2D multi-pass) job does not: workflow "rip" writes
    # N passes of one page (all _Page1_), so it is a SINGLE printed layer. Derive the count from
    # the highest Page number present rather than crashing on the missing key.
    layer_count = int(info["layer_count"]) if info.get("layer_count") is not None else (
        max(pages) if pages else 0
    )
    ordered = [pages[n] for n in sorted(pages) if n <= layer_count]
    missing = [n for n in range(1, layer_count + 1) if n not in pages]
    preview = _find_preview(
        job_dir, str(info.get("job_name") or job_dir.name), info.get("preview_file")
    )
    bbox = info.get("bbox_mm") or {}
    bpp = int(info.get("bpp", 2))
    # The Meteor RIP now writes the head's usable grey-level count. Older jobs lack it: a 4-bit
    # container on this printer is the Aquinox's 8 levels; a 2-bit container is its own 4 levels
    # (where grey_levels == 2**bpp, so the preview remap is a no-op). Explicit key always wins.
    grey_levels = int(info.get("grey_levels") or (8 if bpp >= 4 else (1 << bpp)))
    return JobInfo(
        dir=job_dir,
        name=str(info.get("job_name") or job_dir.name),
        layer_count=layer_count,
        layer_height_mm=round(height / layer_count, 4) if layer_count else 0.0,
        height_mm=height,
        bbox_mm=(float(bbox.get("x_mm", 0.0)), float(bbox.get("y_mm", 0.0)), height),
        dpi=int(info.get("dpi", 720)),
        bpp=bpp,
        grey_levels=grey_levels,
        timestamp=str(info.get("timestamp", "")),
        pages=tuple(ordered),
        workflow=str(info.get("workflow") or ""),
        slicer_multipass=_read_multipass(info),
        preview=preview,
        missing_pages=missing,
    )


# Preview/splash image extensions the slicer has emitted (an isometric render of the part).
_PREVIEW_EXTS = (".bmp", ".png", ".jpg", ".jpeg")


def _find_preview(job_dir: Path, name: str, manifest_name: Any) -> Path | None:
    """Locate the slicer's splash/preview image in a job folder. The filename has varied across
    slicer versions, so try the manifest's ``preview_file`` first, then the known conventions
    (``<name>.bmp``, ``<name>_preview.bmp``, ``<name>.stl_Preview``), then any image/preview file.
    Never returns a print TIFF."""
    candidates: list[str] = []
    if isinstance(manifest_name, str) and manifest_name:
        candidates.append(manifest_name)
    candidates += [f"{name}.bmp", f"{name}_preview.bmp", f"{name}.stl_Preview"]
    for cand in candidates:
        p = job_dir / cand
        if p.is_file():
            return p
    for f in sorted(job_dir.iterdir()):
        if f.is_file() and (f.suffix.lower() in _PREVIEW_EXTS or f.name.endswith(".stl_Preview")):
            return f
    return None


def layer_png(job: JobInfo, layer: int, *, max_px: int = 700) -> bytes:
    """Render page `layer` (1-based) as a greyscale PNG (white paper, black ink), downscaled."""
    if not 1 <= layer <= len(job.pages):
        raise IndexError(f"layer {layer} not in 1..{len(job.pages)}")
    key = (layer, max_px)
    if key in job._cache:
        return job._cache[key]
    with Image.open(job.pages[layer - 1]) as im:
        # Pillow loads a WhiteIsZero page scaled on the 4-bit CONTAINER (2**bpp-1=15), so an 8-grey-
        # level Aquinox head's max ink (level 7) comes back as 136 (mid-grey), not black. Rescale on
        # the head's usable level ceiling (grey_levels-1=7) so full ink renders black. Display-only.
        gray = Image.fromarray(
            _remap_ink_levels(np.asarray(im.convert("L")), job.bpp, job.grey_levels), mode="L"
        )
        w, h = gray.size
        scale = min(1.0, max_px / max(w, h))
        if scale < 1.0:
            gray = gray.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BOX
            )
        buf = io.BytesIO()
        gray.save(buf, format="PNG", optimize=True)
    job._cache[key] = buf.getvalue()
    return job._cache[key]


def layer_png_scaled(job: JobInfo, layer: int, *, max_px: int = 1200) -> tuple[bytes, float]:
    """Like ``layer_png`` but also returns the rendered PNG's millimetres-per-pixel, for Lane B
    metrology. Native RIP resolution is ``25.4 / dpi`` mm/px; any downscale to ``max_px`` raises
    mm/px by the same factor. Returns (png_bytes, mm_per_px); mm_per_px is 0.0 if dpi is unknown."""
    if not 1 <= layer <= len(job.pages):
        raise IndexError(f"layer {layer} not in 1..{len(job.pages)}")
    native_mm_per_px = 25.4 / job.dpi if job.dpi else 0.0
    with Image.open(job.pages[layer - 1]) as im:
        gray = im.convert("L")
        w, h = gray.size
        scale = min(1.0, max_px / max(w, h))
        if scale < 1.0:
            gray = gray.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BOX
            )
        buf = io.BytesIO()
        gray.save(buf, format="PNG", optimize=True)
    mm_per_px = native_mm_per_px / scale if scale > 0 else native_mm_per_px
    return buf.getvalue(), mm_per_px


def preview_png(job: JobInfo, *, max_px: int = 512) -> bytes:
    """Render the slicer's splash/preview image as a downscaled RGB PNG the browser can show.

    Raises IndexError when the job has no preview, or OSError when the file can't be decoded (a
    ``.stl_Preview`` of an unknown format, say) — both become a 404 at the endpoint."""
    if job.preview is None:
        raise IndexError("job has no preview image")
    with Image.open(job.preview) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        scale = min(1.0, max_px / max(w, h))
        if scale < 1.0:
            rgb = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BOX)
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class JobStore:
    """Scans configured roots (hot folder, its _archive, any job folder) for job_info.json."""

    def __init__(self, roots: list[Path]) -> None:
        self.roots = [Path(r) for r in roots]

    def scan(self) -> list[JobInfo]:
        found: dict[Path, JobInfo] = {}
        for root in self.roots:
            if not root.exists():
                continue
            candidates = [root, *[p for p in root.iterdir() if p.is_dir()]]
            archive = root / "_archive"
            if archive.is_dir():
                candidates += [p for p in archive.iterdir() if p.is_dir()]
            for d in candidates:
                if (d / "job_info.json").is_file() and d.resolve() not in found:
                    try:
                        found[d.resolve()] = load_job(d)
                    except (OSError, ValueError, KeyError):
                        continue
        return sorted(found.values(), key=lambda j: j.dir.name, reverse=True)

    def within_roots(self, path: Path) -> bool:
        target = path.resolve()
        return any(root.exists() and root.resolve() in target.parents for root in self.roots)
