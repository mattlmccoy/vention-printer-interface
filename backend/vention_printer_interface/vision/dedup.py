"""One-time dedup of already-stored runs.

Uncalibrated science captures wrote ``<stage>.webp`` (registered) as a byte-for-byte copy of
``<stage>.raw.webp`` (raw) — ~36% of run storage was this pure duplication. This removes each
duplicate that is a *confirmed SHA-256 match* to its raw and repoints the sidecar's
``images.registered`` and the run manifest at the raw file, so the compare UI still resolves the
same pixels. A registered image that genuinely differs (a real warp) is never touched.

Run it as a module::

    python -m vention_printer_interface.vision.dedup <runs-root> [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DedupResult:
    files_removed: int = 0
    bytes_reclaimed: int = 0
    sidecars_updated: int = 0

    def __add__(self, other: DedupResult) -> DedupResult:
        return DedupResult(
            self.files_removed + other.files_removed,
            self.bytes_reclaimed + other.bytes_reclaimed,
            self.sidecars_updated + other.sidecars_updated,
        )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def dedup_run(run_dir: Path, *, dry_run: bool = False) -> DedupResult:
    """Remove every ``<stage>.webp`` under ``run_dir/vision`` that is byte-identical to its
    ``<stage>.raw.webp``, repointing the sidecar at the raw file. ``dry_run`` only measures."""
    run_dir = Path(run_dir)
    res = DedupResult()
    vision = run_dir / "vision"
    if not vision.is_dir():
        return res
    remap: dict[str, str] = {}  # registered rel-path -> raw rel-path, for the manifest rewrite
    for raw in sorted(vision.rglob("*.raw.webp")):
        if raw.name.startswith("._"):
            continue
        stage = raw.name[: -len(".raw.webp")]
        registered = raw.with_name(f"{stage}.webp")
        if not registered.is_file():
            continue  # already deduped (no separate registered copy)
        raw_sha = _sha256(raw)
        if _sha256(registered) != raw_sha:
            continue  # a real, different registered image — keep it
        size = registered.stat().st_size
        remap[registered.relative_to(run_dir).as_posix()] = raw.relative_to(run_dir).as_posix()
        if not dry_run:
            registered.unlink()
            sidecar = raw.with_name(f"{stage}.json")
            if _repoint_sidecar(sidecar, raw.name, raw_sha):
                res.sidecars_updated += 1
        res.files_removed += 1
        res.bytes_reclaimed += size
    if remap and not dry_run:
        _repoint_manifest(vision / "manifest.json", remap)
    return res


def _repoint_sidecar(sidecar: Path, raw_name: str, raw_sha: str) -> bool:
    """Point the sidecar's ``images.registered`` at the raw file; checksum the raw."""
    try:
        doc = json.loads(sidecar.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    images = doc.get("images")
    if isinstance(images, dict):
        images["registered"] = raw_name
    doc["checksum_sha256"] = raw_sha
    sidecar.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return True


def _repoint_manifest(manifest: Path, remap: dict[str, str]) -> None:
    """Rewrite the run manifest so any record whose ``registered`` names a removed duplicate points
    at the surviving raw image (the compare UI reads ``registered`` from here)."""
    try:
        recs = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(recs, list):
        return
    changed = False
    for rec in recs:
        if isinstance(rec, dict) and rec.get("registered") in remap:
            rec["registered"] = remap[rec["registered"]]
            changed = True
    if changed:
        manifest.write_text(json.dumps(recs, indent=2), encoding="utf-8")


def dedup_runs_under(root: Path, *, dry_run: bool = False) -> DedupResult:
    """Dedup every run directory directly under ``root`` (skips dotfiles / ``.partial`` staging)."""
    total = DedupResult()
    root = Path(root)
    if not root.is_dir():
        return total
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        if run.name.startswith(".") or run.name.endswith(".partial"):
            continue
        total = total + dedup_run(run, dry_run=dry_run)
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove duplicate registered captures (== raw).")
    ap.add_argument(
        "root", type=Path, help="a runs root (local experiments dir or a drive's vpi-runs)"
    )
    ap.add_argument("--dry-run", action="store_true", help="measure only; delete nothing")
    args = ap.parse_args()
    res = dedup_runs_under(args.root, dry_run=args.dry_run)
    tag = "would reclaim" if args.dry_run else "reclaimed"
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{tag} {res.bytes_reclaimed / 1e6:.0f} MB from {res.files_removed} duplicate "
          f"registered images ({res.sidecars_updated} sidecars).")


if __name__ == "__main__":
    main()
