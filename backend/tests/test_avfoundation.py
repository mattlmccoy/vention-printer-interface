"""AVFoundation camera-identity parsing/resolution (Phase-2 unattended science capture)."""

from vention_printer_interface.vision.avfoundation import (
    AvfCamera,
    parse_camera_uids,
    resolve_index_for_uid,
)

# Captured shape from a real `system_profiler SPCameraDataType -json` on this Mac (2026-09-18),
# extended with a second identical ELP entry (distinct unique ids, same model/name) to model the
# two-camera rig the feature exists for.
REAL_SINGLE = (
    '{"SPCameraDataType":[{"_name":"FaceTime HD Camera",'
    '"spcamera_model-id":"FaceTime HD Camera",'
    '"spcamera_unique-id":"3F45E80A-0176-46F7-B185-BB9E2C0E82E3"}]}'
)
TWO_IDENTICAL = (
    '{"SPCameraDataType":[{"_name":"FaceTime HD Camera",'
    '"spcamera_unique-id":"3F45E80A-0176-46F7-B185-BB9E2C0E82E3"},'
    '{"_name":"UVC Camera VendorID_13028 ProductID_8224",'
    '"spcamera_unique-id":"0x1411000012345678"},'
    '{"_name":"UVC Camera VendorID_13028 ProductID_8224",'
    '"spcamera_unique-id":"0x1421000087654321"}]}'
)


def test_parse_real_single_camera() -> None:
    cams = parse_camera_uids(REAL_SINGLE)
    assert cams == [AvfCamera(index=0, name="FaceTime HD Camera",
                              unique_id="3F45E80A-0176-46F7-B185-BB9E2C0E82E3")]


def test_parse_two_identical_cameras_keeps_distinct_unique_ids_in_order() -> None:
    cams = parse_camera_uids(TWO_IDENTICAL)
    assert [c.index for c in cams] == [0, 1, 2]
    # Same NAME for the two ELPs, but distinct unique ids at distinct indices — the whole point.
    assert cams[1].name == cams[2].name
    assert cams[1].unique_id != cams[2].unique_id


def test_resolve_index_binds_a_unique_id_to_its_avfoundation_index() -> None:
    cams = parse_camera_uids(TWO_IDENTICAL)
    assert resolve_index_for_uid(cams, "0x1421000087654321") == 2
    assert resolve_index_for_uid(cams, "0x1411000012345678") == 1
    assert resolve_index_for_uid(cams, "not-present") is None


def test_parse_skips_entries_without_a_unique_id_and_survives_junk() -> None:
    assert parse_camera_uids('{"SPCameraDataType":[{"_name":"no uid"}]}') == []
    assert parse_camera_uids("not json") == []
    assert parse_camera_uids("{}") == []


def test_frame_source_resolves_uid_to_current_index(monkeypatch) -> None:
    # The FrameSource binds to a unique id and resolves it to whatever index it sits at NOW.
    from vention_printer_interface.vision import frame_source as fs

    cams = parse_camera_uids(TWO_IDENTICAL)
    monkeypatch.setattr(fs, "list_avf_cameras", lambda *a, **k: cams, raising=False)
    monkeypatch.setattr(
        "vention_printer_interface.vision.avfoundation.list_avf_cameras",
        lambda *a, **k: cams,
    )
    src = fs.AVFoundationFrameSource("0x1421000087654321")
    assert src._resolve_index() == 2


def test_frame_source_raises_when_uid_absent(monkeypatch) -> None:
    from vention_printer_interface.vision import frame_source as fs

    monkeypatch.setattr(
        "vention_printer_interface.vision.avfoundation.list_avf_cameras",
        lambda *a, **k: [],
    )
    src = fs.AVFoundationFrameSource("missing-uid")
    try:
        src._resolve_index()
        raise AssertionError("expected RuntimeError for an absent unique id")
    except RuntimeError as e:
        assert "not found" in str(e)


def test_science_uid_endpoints_round_trip(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        assert c.get("/api/vision/science-uid").json() == {"unique_id": None}
        # avf-cameras returns a well-formed (possibly empty) list + the current science uid.
        body = c.get("/api/vision/avf-cameras").json()
        assert isinstance(body["cameras"], list) and body["science_uid"] is None
        # Set it (server reopens science; no camera is opened until a capture, so this is fine).
        r = c.put("/api/vision/science-uid", json={"unique_id": "0x1421000087654321"})
        assert r.status_code == 200
        assert c.get("/api/vision/science-uid").json() == {"unique_id": "0x1421000087654321"}
        # Junk rejected; null clears it.
        assert c.put("/api/vision/science-uid", json={"unique_id": "  "}).status_code == 400
        assert c.put("/api/vision/science-uid", json={"unique_id": None}).status_code == 200
        assert c.get("/api/vision/science-uid").json() == {"unique_id": None}
