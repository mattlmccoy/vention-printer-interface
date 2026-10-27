"""Science-camera calibration history: every saved calibration, viewable long after it was made.

Matt (2026-10-26): see the most recent and past calibrations in the console, "not a 'find the cal
file' button but actually route to where they are stored and allow viewing them (as well as
validation)". The active calibration lives in ``experiments/.vision_calibration.json`` and is
overwritten by each save, so each save is also archived:

  experiments/vision_calibrations/<version>/
    calibration.json            the Calibration (same format as the active file)
    report.json                 the run's solve report (autocal), when there was one
    capture|raw|corrected|residuals.jpg   the photos the Calibrate page showed

Validations stay where ``app.py:_store_validation`` writes them (0.19.3+):
``experiments/validations/<version>/<stamp>/`` (``result.json``, ``annotated.jpg``, ``raw.jpg``).
The numbers-only record in ``.vision_validation.json`` (older validations, no photo) is listed too,
labelled as such: an unknown never reads as validated.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from vention_printer_interface.vision.registration import (
    Calibration,
    load_calibration,
    save_calibration,
)

log = logging.getLogger(__name__)

HISTORY_DIRNAME = "vision_calibrations"
IMAGE_NAMES = ("capture", "raw", "corrected", "residuals")
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LEGACY_NOTE = "numbers only: the validation photo was not kept before 0.19.3"


def history_dir(root: Path) -> Path:
    return Path(root) / HISTORY_DIRNAME


def _folder(root: Path, version: str) -> Path | None:
    return history_dir(root) / version if _SAFE.match(version) else None


def archive_calibration(
    root: Path, calib: Calibration, *, report: dict[str, Any] | None = None,
    images: dict[str, np.ndarray] | None = None,
) -> Path:
    """Write ``calib`` (and its report and photos) to its history folder; returns the folder.
    Image names must be in ``IMAGE_NAMES``."""
    import cv2

    folder = _folder(root, calib.version)
    if folder is None:
        raise ValueError(f"unsafe calibration version {calib.version!r}")
    bad = [n for n in (images or {}) if n not in IMAGE_NAMES]
    if bad:
        raise ValueError(f"unknown calibration image(s) {bad}; expected {IMAGE_NAMES}")
    folder.mkdir(parents=True, exist_ok=True)
    save_calibration(folder / "calibration.json", calib)
    if report is not None:
        (folder / "report.json").write_text(json.dumps(report, default=float), encoding="utf-8")
    for name, img in (images or {}).items():
        cv2.imwrite(str(folder / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return folder


def load_archived(root: Path, version: str) -> Calibration | None:
    folder = _folder(root, version)
    return None if folder is None else load_calibration(folder / "calibration.json")


def image_path(root: Path, version: str, name: str) -> Path | None:
    folder = _folder(root, version)
    if folder is None or name not in IMAGE_NAMES:
        return None
    return folder / f"{name}.jpg"


def _saved_at(version: str) -> str | None:
    try:
        t = datetime.strptime(version, "cal-%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _area(region: Any) -> list[float] | None:
    pts = np.asarray(region if region else [], float).reshape(-1, 2)
    if len(pts) < 3:
        return None
    span = pts.max(axis=0) - pts.min(axis=0)
    return [float(span[0]), float(span[1])]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _validations(root: Path, version: str) -> list[dict[str, Any]]:
    """Stored validations newest first, then the numbers-only record if it is for ``version``."""
    out: list[dict[str, Any]] = []
    base = Path(root) / "validations" / version
    stamps = sorted((p for p in base.iterdir() if p.is_dir() and _SAFE.match(p.name)),
                    key=lambda p: p.name, reverse=True) if base.is_dir() else []
    for d in stamps:
        r = _read_json(d / "result.json")
        if not isinstance(r, dict):
            continue
        out.append({**r, "stamp": d.name, "legacy": False,
                    "annotated": (d / "annotated.jpg").is_file(), "raw": (d / "raw.jpg").is_file()})
    legacy = _read_json(Path(root) / ".vision_validation.json")
    scale = (legacy.get("scale") or {}) if isinstance(legacy, dict) else {}
    # Every stored validation (0.19.3+) also rewrites this file with its own numbers: it is only a
    # separate, photo-less validation when no stored one has the same numbers.
    mirrors = any(r.get("max_mm") == scale.get("max_mm") and r.get("rms_mm") == scale.get("rms_mm")
                  for r in out)
    if isinstance(legacy, dict) and legacy.get("calibration_version") == version and not mirrors:
        out.append({**scale, "stamp": None, "legacy": True,
                    "annotated": False, "raw": False, "note": LEGACY_NOTE})
    return out


def _validation_summary(vals: list[dict[str, Any]]) -> dict[str, Any]:
    if not vals:
        return {"count": 0, "status": "none", "latest": None}
    latest = vals[0]
    status = "passed" if latest.get("passed") is True else "failed"
    keep = ("stamp", "legacy", "passed", "rms_mm", "max_mm", "target_mm", "scale_bias")
    return {"count": len(vals), "status": status, "latest": {k: latest.get(k) for k in keep}}


def _summary(root: Path, calib: Calibration, *, active: bool, archived: bool) -> dict[str, Any]:
    prov = calib.provenance or {}
    sc = prov.get("self_check")
    folder = _folder(root, calib.version)
    return {
        "version": calib.version, "saved_at": _saved_at(calib.version),
        "method": prov.get("method", "manual"), "active": active, "archived": archived,
        "image_size": list(calib.image_size) if calib.image_size else None,
        "lens_rms_mm": prov.get("reprojection_rms_mm"),
        "shift_rms_mm": prov.get("shift_rms_mm", calib.reprojection_error),
        "scale_ratio": prov.get("scale_ratio"), "n_views": prov.get("n_views"),
        "area_mm": _area(prov.get("valid_region_mm")), "point_method": prov.get("point_method"),
        "self_check": ({"passed": sc.get("passed"), "rms_mm": sc.get("rms_mm")}
                       if isinstance(sc, dict) else None),
        "images": [n for n in IMAGE_NAMES
                   if folder is not None and (folder / f"{n}.jpg").is_file()],
        "validation": _validation_summary(_validations(root, calib.version)),
    }


def list_calibrations(root: Path, *, active: Calibration | None) -> list[dict[str, Any]]:
    """Every archived calibration plus the active one (even if never archived), newest first."""
    rows: dict[str, dict[str, Any]] = {}
    hd = history_dir(root)
    for d in (sorted(hd.iterdir()) if hd.is_dir() else []):
        if not _SAFE.match(d.name):
            continue
        try:
            calib = load_calibration(d / "calibration.json")
        except (OSError, ValueError, KeyError) as exc:
            log.warning("unreadable archived calibration %s: %s", d, exc)
            continue
        if calib is not None:
            rows[calib.version] = _summary(
                root, calib, active=active is not None and calib.version == active.version,
                archived=True)
    if active is not None and active.version not in rows:
        rows[active.version] = _summary(root, active, active=True, archived=False)
    return sorted(rows.values(), key=lambda r: r["version"], reverse=True)


def calibration_detail(
    root: Path, version: str, *, active: Calibration | None,
) -> dict[str, Any] | None:
    """Summary + report + validations of one calibration, or None when unknown/unsafe."""
    if _folder(root, version) is None:
        return None
    calib = load_archived(root, version)
    archived = calib is not None
    if calib is None and active is not None and active.version == version:
        calib = active
    if calib is None:
        return None
    folder = _folder(root, version)
    report = _read_json(folder / "report.json") if folder is not None else None
    return {
        **_summary(root, calib, active=active is not None and active.version == version,
                   archived=archived),
        "report": report if isinstance(report, dict) else None,
        "provenance": calib.provenance or {},
        "validations": _validations(root, version),
    }


_MATCH_KEYS = ("shift_rms_mm", "shift_worst_mm", "reprojection_rms_px", "scale_ratio", "n_views")
_PHOTO_RE = re.compile(r"^(\d{2,3})_(-?[\d.]+)\.png$")


def _sweep_made(sweep: dict[str, Any], calib: Calibration) -> bool:
    """True only when the saved sweep is provably the run this calibration was saved from: the
    same solve numbers (exactly) and solved before the save."""
    res, prov = sweep.get("result") or {}, calib.provenance or {}
    if not all(k in prov and res.get(k) == prov[k] for k in _MATCH_KEYS):
        return False
    saved, made = sweep.get("saved_at"), _saved_at(calib.version)
    return isinstance(saved, str) and made is not None and saved[:19] <= made[:19]


def _sweep_photo(photo_dir: Path, sweep: dict[str, Any], capture_index: int) -> np.ndarray | None:
    """The stored photo of view ``capture_index``, only when the folder holds exactly this sweep's
    photos (one per view, named by its recoater position)."""
    import cv2

    want = {i: f"{v['recoater_mm']:.1f}" for i, v in enumerate(sweep.get("views", []))}
    have = {}
    for f in photo_dir.iterdir() if photo_dir.is_dir() else []:
        m = _PHOTO_RE.match(f.name)
        if m:
            have[int(m.group(1))] = (m.group(2), f)
    if not want or {i: mm for i, (mm, _) in have.items()} != want:
        return None
    img = cv2.imread(str(have[capture_index][1]), cv2.IMREAD_COLOR)
    return img if img is not None else None


def _sweep_images(
    calib: Calibration, sweep: dict[str, Any], photo: np.ndarray, capture_index: int,
) -> dict[str, np.ndarray]:
    from types import SimpleNamespace

    from vention_printer_interface.vision.overlay import (
        board_grid_mm,
        draw_overlay,
        draw_residual_arrows,
        fit_board_to_bed,
    )

    res = SimpleNamespace(
        camera_matrix=calib.camera_matrix, dist_coeffs=calib.dist_coeffs, H=calib.H,
        bed_extent_mm=calib.bed_extent_mm, mm_per_px=calib.mm_per_px,
        valid_region_mm=(calib.provenance or {}).get("valid_region_mm") or [])
    view = sweep["views"][capture_index]
    pts = np.asarray(view["image_points"], float).reshape(-1, 2)
    board = sweep.get("board") or {}
    lines = None
    if len(pts) >= 4 and board.get("squares_x"):
        to_bed = fit_board_to_bed(pts, np.asarray(view["object_points"], float), res)
        lines = board_grid_mm(int(board["squares_x"]), int(board["squares_y"]),
                              float(board["square_length_mm"]), to_bed)
    images = {"capture": photo, "raw": draw_overlay(photo, res, "raw", lines),
              "corrected": draw_overlay(photo, res, "corrected", lines)}
    if view.get("residuals_px"):
        images["residuals"] = draw_residual_arrows(photo, pts, np.asarray(view["residuals_px"]))
    return images


def backfill_active(
    root: Path, active: Calibration, *, sweep: dict[str, Any] | None, photo_dir: Path | None,
) -> bool:
    """Archive the calibration in use when the history does not hold it yet (it was saved before
    the history existed). The saved sweep's report and photos are added only when that sweep is
    provably the run the calibration came from. Returns whether anything was written."""
    folder = _folder(root, active.version)
    if folder is None or (folder / "calibration.json").is_file():
        return False
    report: dict[str, Any] | None = None
    images: dict[str, np.ndarray] = {}
    if sweep is not None and _sweep_made(sweep, active):
        report = sweep.get("result")
        views = sweep.get("views") or []
        cap = float(sweep.get("capture_mm", float("nan")))
        if views and photo_dir is not None and np.isfinite(cap):
            ci = min(range(len(views)), key=lambda i: abs(views[i]["recoater_mm"] - cap))
            photo = _sweep_photo(photo_dir, sweep, ci)
            size = active.image_size
            if photo is not None and (size is None or
                                      (photo.shape[1], photo.shape[0]) == tuple(size)):
                images = _sweep_images(active, sweep, photo, ci)
    archive_calibration(root, active, report=report, images=images)
    return True
