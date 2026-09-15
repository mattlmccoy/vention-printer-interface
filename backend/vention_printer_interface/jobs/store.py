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

from PIL import Image

_PAGE_RE = re.compile(r"_Page(\d+)_Clr(\d+)\.tif{1,2}$", re.IGNORECASE)


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
    timestamp: str
    pages: tuple[Path, ...]
    workflow: str = ""
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
            "timestamp": self.timestamp,
            "complete": self.complete,
            "missing_pages": list(self.missing_pages),
            "workflow": self.workflow,
            "kind": self.kind,
        }


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
    bbox = info.get("bbox_mm") or {}
    return JobInfo(
        dir=job_dir,
        name=str(info.get("job_name") or job_dir.name),
        layer_count=layer_count,
        layer_height_mm=round(height / layer_count, 4) if layer_count else 0.0,
        height_mm=height,
        bbox_mm=(float(bbox.get("x_mm", 0.0)), float(bbox.get("y_mm", 0.0)), height),
        dpi=int(info.get("dpi", 720)),
        bpp=int(info.get("bpp", 2)),
        timestamp=str(info.get("timestamp", "")),
        pages=tuple(ordered),
        workflow=str(info.get("workflow") or ""),
        missing_pages=missing,
    )


def layer_png(job: JobInfo, layer: int, *, max_px: int = 700) -> bytes:
    """Render page `layer` (1-based) as a greyscale PNG (white paper, black ink), downscaled."""
    if not 1 <= layer <= len(job.pages):
        raise IndexError(f"layer {layer} not in 1..{len(job.pages)}")
    key = (layer, max_px)
    if key in job._cache:
        return job._cache[key]
    with Image.open(job.pages[layer - 1]) as im:
        gray = im.convert("L")
        # Pillow presents WhiteIsZero pages as a normal L image: 255 = paper, 0 = full ink
        # (verified on ir_heater_socket_mount_v1 from the lab hot folder, 2026-09-09).
        # The PNG keeps that greyscale as-is.
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
