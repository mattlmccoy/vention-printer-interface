"""Pure ignore-list logic: names stored beside the macOS unique ids, which names are safe to expose
to the browser (it only knows labels), and dropping ignored cameras from server enumeration.

The FaceTime/iPhone ids and names below are captured from this Mac's real
``system_profiler SPCameraDataType -json`` and its real ``.vision_ignored_cameras.json``
(2026-09-23); the ELP entries mirror the ids in ``test_vision_cameras.py``."""

from __future__ import annotations

import json
from pathlib import Path

from vention_printer_interface.vision.avfoundation import AvfCamera
from vention_printer_interface.vision.ignored_cameras import (
    IgnoredCamera,
    drop_ignored_devices,
    exposed_names,
    load_ignored,
    save_ignored,
    uid_of_stable_id,
    with_names,
)

FACETIME = AvfCamera(0, "FaceTime HD Camera", "3F45E80A-0176-46F7-B185-BB9E2C0E82E3")
IPHONE = AvfCamera(1, "mattmccoy-iphone Camera", "0075DA72-2CAB-4BE3-9FCA-8C9100000001")
ELP_A = AvfCamera(2, "ELP 4K USB Camera", "0x1411000012345678")
ELP_B = AvfCamera(3, "ELP 4K USB Camera", "0x1421000087654321")


def test_load_reads_the_legacy_ids_only_file(tmp_path: Path) -> None:
    # The exact shape on disk before this change: ids only, no names.
    p = tmp_path / ".vision_ignored_cameras.json"
    p.write_text(json.dumps({"unique_ids": [IPHONE.unique_id, FACETIME.unique_id]}))
    assert load_ignored(p) == [
        IgnoredCamera(IPHONE.unique_id, None, False),
        IgnoredCamera(FACETIME.unique_id, None, False),
    ]


def test_load_missing_or_junk_file_is_empty(tmp_path: Path) -> None:
    assert load_ignored(tmp_path / "nope.json") == []
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_ignored(p) == []


def test_save_then_load_round_trips_names(tmp_path: Path) -> None:
    p = tmp_path / ".vision_ignored_cameras.json"
    entries = [IgnoredCamera(FACETIME.unique_id, "FaceTime HD Camera", False)]
    save_ignored(p, entries)
    assert load_ignored(p) == entries
    # The id list stays at the top level so an older operator still reads the file.
    assert json.loads(p.read_text())["unique_ids"] == [FACETIME.unique_id]


def test_with_names_backfills_from_the_current_enumeration() -> None:
    prev = [IgnoredCamera(FACETIME.unique_id, None, False)]
    out = with_names([FACETIME.unique_id], [FACETIME, IPHONE], prev)
    assert out == [IgnoredCamera(FACETIME.unique_id, "FaceTime HD Camera", False)]


def test_with_names_keeps_the_stored_name_of_an_unplugged_camera() -> None:
    prev = [IgnoredCamera(IPHONE.unique_id, "mattmccoy-iphone Camera", False)]
    out = with_names([IPHONE.unique_id], [FACETIME], prev)
    assert out == prev


def test_with_names_marks_a_name_shared_by_two_identical_cameras() -> None:
    out = with_names([ELP_B.unique_id], [ELP_A, ELP_B], [])
    assert out == [IgnoredCamera(ELP_B.unique_id, "ELP 4K USB Camera", True)]


def test_exposed_names_hides_a_unique_builtin() -> None:
    entries = with_names([FACETIME.unique_id], [FACETIME, ELP_A], [])
    assert exposed_names(entries, [FACETIME, ELP_A]) == ["FaceTime HD Camera"]


def test_exposed_names_never_exposes_one_of_two_identical_elps() -> None:
    # Ignoring ELP B must not hide ELP A in the browser: their labels are identical.
    entries = with_names([ELP_B.unique_id], [ELP_A, ELP_B], [])
    assert exposed_names(entries, [ELP_A, ELP_B]) == []


def test_exposed_names_withholds_a_name_a_non_ignored_camera_now_shares() -> None:
    # Stored while its twin was unplugged (so not marked shared); the twin is now back.
    entries = [IgnoredCamera(ELP_B.unique_id, "ELP 4K USB Camera", False)]
    assert exposed_names(entries, [ELP_A]) == []


def test_exposed_names_still_exposes_an_unplugged_unique_camera() -> None:
    entries = [IgnoredCamera(IPHONE.unique_id, "mattmccoy-iphone Camera", False)]
    assert exposed_names(entries, [FACETIME]) == ["mattmccoy-iphone Camera"]


def test_exposed_names_skips_unnamed_entries() -> None:
    assert exposed_names([IgnoredCamera("0xABC", None, False)], []) == []


def test_uid_of_stable_id_strips_the_macos_prefix_only() -> None:
    assert uid_of_stable_id(f"macos-uid:{FACETIME.unique_id}") == FACETIME.unique_id
    assert uid_of_stable_id("idx:0") is None
    assert uid_of_stable_id(None) is None


def test_drop_ignored_devices_removes_only_ignored_macos_cameras() -> None:
    devices = [
        {"index": 0, "stable_id": f"macos-uid:{FACETIME.unique_id}", "name": "FaceTime HD Camera"},
        {"index": 2, "stable_id": f"macos-uid:{ELP_A.unique_id}", "name": "ELP 4K USB Camera"},
        {"index": 3, "stable_id": "idx:3", "name": "no uid"},
    ]
    kept = drop_ignored_devices(devices, [FACETIME.unique_id])
    assert [d["index"] for d in kept] == [2, 3]
