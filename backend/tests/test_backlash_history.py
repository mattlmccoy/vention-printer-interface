"""Persisted backlash calibration history (survives operator restarts)."""

from __future__ import annotations

from pathlib import Path

from vention_printer_interface.control.backlash_history import (
    list_backlash,
    load_backlash,
    save_backlash,
)

_RESULT = {
    "axis": 1,
    "recommended_mm": 0.1,
    "positions": [
        {"ref_mm": 15.0, "backlash_median_mm": -0.1, "backlash_mag_median_mm": 0.1,
         "reps_mm": [-0.1, -0.1, 0.0]},
        {"ref_mm": 30.0, "backlash_median_mm": -0.1, "backlash_mag_median_mm": 0.1,
         "reps_mm": [-0.1, -0.2]},
    ],
}


def test_save_then_list_and_load(tmp_path: Path) -> None:
    rid = save_backlash(tmp_path, _RESULT)
    assert rid.startswith("backlash_a1_")
    rid2 = save_backlash(tmp_path, {**_RESULT, "axis": 2, "recommended_mm": 2.0})

    summaries = list_backlash(tmp_path)
    assert len(summaries) == 2
    assert {s["axis"] for s in summaries} == {1, 2}
    s1 = next(s for s in summaries if s["id"] == rid)
    assert s1["recommended_mm"] == 0.1 and s1["n_positions"] == 2 and s1["saved_utc"]

    full = load_backlash(tmp_path, rid)
    assert full is not None and full["axis"] == 1
    assert full["positions"][0]["ref_mm"] == 15.0
    assert load_backlash(tmp_path, rid2)["recommended_mm"] == 2.0


def test_two_saves_same_second_do_not_collide(tmp_path: Path) -> None:
    a = save_backlash(tmp_path, _RESULT)
    b = save_backlash(tmp_path, _RESULT)
    assert a != b and len(list_backlash(tmp_path)) == 2


def test_missing_dir_and_bad_id_are_safe(tmp_path: Path) -> None:
    assert list_backlash(tmp_path / "nope") == []
    assert load_backlash(tmp_path, "does_not_exist") is None
    assert load_backlash(tmp_path, "../secrets") is None  # traversal guarded
