"""Science-camera calibration history (vision/calibration_history.py).

Every saved calibration is archived under ``experiments/vision_calibrations/<version>/`` with its
report and photos, so it can be viewed (and restored) long after it was made. Fixtures are the REAL
2026-10-26 files: the active calibration and its numbers-only certified validation. Validation
folders follow ``app.py:_store_validation`` (0.19.3+): ``validations/<version>/<stamp>/result.json``
+ ``annotated.jpg``.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from vention_printer_interface.vision.calibration_history import (
    archive_calibration,
    backfill_active,
    calibration_detail,
    image_path,
    list_calibrations,
    load_archived,
)
from vention_printer_interface.vision.registration import Calibration, load_calibration

FIX = Path(__file__).parent / "fixtures" / "calibration_history"
REAL = "cal-20261026T192538Z"


def _real() -> Calibration:
    c = load_calibration(FIX / "vision_calibration_20261026.json")
    assert c is not None
    return c


def _older() -> Calibration:
    return dataclasses.replace(_real(), version="cal-20261021T174751Z", provenance={})


def _validation(root: Path, version: str, stamp: str, passed: bool, photo: bool = True) -> None:
    d = root / "validations" / version / stamp
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({
        "calibration_version": version, "validated_at": stamp, "certified_mm": 10.0,
        "rms_mm": 0.03, "max_mm": 0.045 if passed else 0.12, "passed": passed,
        "target_mm": 0.05, "scale_bias": 1.0004}))
    if photo:
        (d / "annotated.jpg").write_bytes(b"\xff\xd8jpeg")


def test_archive_round_trips_the_real_calibration(tmp_path: Path) -> None:
    archive_calibration(tmp_path, _real())
    back = load_archived(tmp_path, REAL)
    assert back is not None and back.version == REAL
    assert np.allclose(back.H, _real().H) and back.provenance == _real().provenance


def test_archive_keeps_the_report_and_photos_as_jpeg(tmp_path: Path) -> None:
    img = np.full((30, 40, 3), 128, np.uint8)
    folder = archive_calibration(tmp_path, _real(), report={"passed": True},
                                 images={"capture": img, "residuals": img})
    assert json.loads((folder / "report.json").read_text()) == {"passed": True}
    assert (folder / "capture.jpg").read_bytes()[:2] == b"\xff\xd8"
    assert image_path(tmp_path, REAL, "residuals") == folder / "residuals.jpg"
    with pytest.raises(ValueError):
        archive_calibration(tmp_path, _real(), images={"../evil": img})


def test_list_is_newest_first_and_marks_the_active_one(tmp_path: Path) -> None:
    archive_calibration(tmp_path, _older())
    archive_calibration(tmp_path, _real())
    rows = list_calibrations(tmp_path, active=_real())
    assert [r["version"] for r in rows] == [REAL, "cal-20261021T174751Z"]
    assert [r["active"] for r in rows] == [True, False]
    assert rows[0]["saved_at"] == "2026-10-26T19:25:38Z"


def test_the_active_calibration_is_listed_even_if_never_archived(tmp_path: Path) -> None:
    rows = list_calibrations(tmp_path, active=_real())
    assert len(rows) == 1 and rows[0]["active"] and rows[0]["archived"] is False


def test_summary_reads_the_real_provenance(tmp_path: Path) -> None:
    row = list_calibrations(tmp_path, active=_real())[0]
    assert row["image_size"] == [5120, 3840] and row["n_views"] == 14
    assert row["lens_rms_mm"] == pytest.approx(0.0354, abs=1e-4)
    assert row["scale_ratio"] == pytest.approx(1.00204, abs=1e-5)
    assert row["area_mm"] == pytest.approx([89.07, 60.10], abs=0.01)  # as saved (pre-0.19.3 scale)
    assert row["self_check"] == {"passed": True, "rms_mm": pytest.approx(0.02755, abs=1e-5)}


def test_validations_are_listed_newest_first_with_their_photos(tmp_path: Path) -> None:
    archive_calibration(tmp_path, _real())
    _validation(tmp_path, REAL, "20261027T140000000000Z", passed=False)
    _validation(tmp_path, REAL, "20261027T150000000000Z", passed=True)
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None
    assert [v["stamp"] for v in d["validations"]] == ["20261027T150000000000Z",
                                                      "20261027T140000000000Z"]
    assert d["validations"][0]["annotated"] is True and d["validations"][0]["raw"] is False
    row = list_calibrations(tmp_path, active=_real())[0]
    assert row["validation"]["count"] == 2 and row["validation"]["status"] == "passed"


def test_a_numbers_only_validation_is_labelled_and_never_hidden(tmp_path: Path) -> None:
    # The real 2026-10-26 certified validation predates stored photos (0.19.3): numbers only.
    shutil.copy(FIX / "vision_validation_20261026.json", tmp_path / ".vision_validation.json")
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None
    (v,) = d["validations"]
    assert v["legacy"] is True and v["annotated"] is False and "not kept" in v["note"]
    assert v["rms_mm"] == pytest.approx(0.0751, abs=1e-4) and v["passed"] is False
    assert list_calibrations(tmp_path, active=_real())[0]["validation"]["status"] == "failed"


def test_the_summary_file_of_a_stored_validation_is_not_listed_twice(tmp_path: Path) -> None:
    # Every validation since 0.19.3 also rewrites .vision_validation.json with its numbers, so on
    # 2026-10-27 the history showed the newest validation twice (once as "numbers only"). Real
    # files: the stored result and the summary file the same run wrote.
    version = "cal-20261027T175542Z"
    cal = dataclasses.replace(_real(), version=version)
    stamp = "20261027T175712265073Z"
    d = tmp_path / "validations" / version / stamp
    d.mkdir(parents=True)
    shutil.copy(FIX / "validation_result_20261027.json", d / "result.json")
    shutil.copy(FIX / "vision_validation_20261027.json", tmp_path / ".vision_validation.json")
    detail = calibration_detail(tmp_path, version, active=cal)
    assert detail is not None
    assert [(v["stamp"], v["legacy"]) for v in detail["validations"]] == [(stamp, False)]
    assert list_calibrations(tmp_path, active=cal)[0]["validation"]["count"] == 1


def test_no_validation_reads_not_validated(tmp_path: Path) -> None:
    row = list_calibrations(tmp_path, active=_real())[0]
    assert row["validation"] == {"count": 0, "status": "none", "latest": None}


def test_detail_has_the_report_and_the_photo_names(tmp_path: Path) -> None:
    img = np.zeros((10, 10, 3), np.uint8)
    archive_calibration(tmp_path, _real(), report={"point_method": "all"},
                        images={"raw": img, "capture": img})
    d = calibration_detail(tmp_path, REAL, active=None)
    assert d is not None and d["report"] == {"point_method": "all"}
    assert d["images"] == ["capture", "raw"] and d["active"] is False


def test_unsafe_names_are_refused(tmp_path: Path) -> None:
    assert calibration_detail(tmp_path, "../etc", active=None) is None
    assert load_archived(tmp_path, "../etc") is None
    assert image_path(tmp_path, REAL, "../calibration") is None
    assert calibration_detail(tmp_path, "cal-19990101T000000Z", active=None) is None


# ---- backfill: the calibration in use before history existed (real 2026-10-26 files) ---------
SWEEP = FIX / "autocal_last_sweep_20261026.json"


def _sweep() -> dict:
    return json.loads(SWEEP.read_text())


def _photos(d: Path, sweep: dict, size: tuple[int, int] = (5120, 3840)) -> None:
    import cv2

    d.mkdir()
    img = np.full((size[1], size[0], 3), 200, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    for i, v in enumerate(sweep["views"]):
        (d / f"{i:02d}_{v['recoater_mm']:.1f}.png").write_bytes(buf.tobytes())


def test_backfill_archives_the_active_calibration_with_its_own_sweep(tmp_path: Path) -> None:
    sw = _sweep()
    _photos(tmp_path / "photos", sw)
    assert backfill_active(tmp_path, _real(), sweep=sw, photo_dir=tmp_path / "photos")
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None and d["archived"]
    assert d["report"]["shift_rms_mm"] == _real().provenance["shift_rms_mm"]
    assert d["images"] == ["capture", "raw", "corrected", "residuals"]


def test_backfill_keeps_only_the_calibration_when_the_sweep_is_another_run(
    tmp_path: Path,
) -> None:
    sw = _sweep()
    sw["result"]["shift_rms_mm"] = 0.05
    assert backfill_active(tmp_path, _real(), sweep=sw, photo_dir=None)
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None and d["archived"] and d["report"] is None and d["images"] == []


def test_backfill_skips_photos_that_are_not_this_sweeps(tmp_path: Path) -> None:
    sw = _sweep()
    other = {"views": [{"recoater_mm": 300.0 + i} for i in range(len(sw["views"]))]}
    _photos(tmp_path / "photos", other)
    assert backfill_active(tmp_path, _real(), sweep=sw, photo_dir=tmp_path / "photos")
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None and d["report"] is not None and d["images"] == []


def test_backfill_does_nothing_once_archived(tmp_path: Path) -> None:
    archive_calibration(tmp_path, _real())
    assert backfill_active(tmp_path, _real(), sweep=_sweep(), photo_dir=None) is False
    d = calibration_detail(tmp_path, REAL, active=_real())
    assert d is not None and d["report"] is None
