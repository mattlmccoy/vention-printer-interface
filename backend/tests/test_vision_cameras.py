from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from vention_printer_interface.vision.cameras import (
    CameraConfig,
    CameraSpec,
    camera_access_state,
    default_backend,
    enumerate_devices,
    load_role_map,
    resolve_roles,
    save_role_map,
    unresolved_roles,
)


def test_default_backend_per_os():
    import cv2

    with patch("platform.system", return_value="Darwin"):
        assert default_backend() == cv2.CAP_AVFOUNDATION
    with patch("platform.system", return_value="Linux"):
        assert default_backend() == cv2.CAP_V4L2
    with patch("platform.system", return_value="Windows"):
        assert default_backend() == cv2.CAP_DSHOW


def test_default_backend_falls_back_to_cap_any_on_unknown_os():
    import cv2

    with patch("platform.system", return_value="Plan9"):
        assert default_backend() == cv2.CAP_ANY


def test_camera_spec_effective_backend_resolves_os_default_when_unset():
    spec = CameraSpec(role="overview", model="m", asin="a", backend=None)
    with patch("platform.system", return_value="Darwin"):
        import cv2

        assert spec.effective_backend() == cv2.CAP_AVFOUNDATION


def test_camera_spec_effective_backend_honors_explicit_value():
    spec = CameraSpec(role="overview", model="m", asin="a", backend=1234)
    assert spec.effective_backend() == 1234


def test_camera_config_defaults_match_finalized_elp_cameras():
    cfg = CameraConfig.from_dict()

    assert cfg.overview.role == "overview"
    assert cfg.overview.model == "ELP-U3CAM20MP01-KV100"
    assert cfg.overview.asin == "B0GMFM4CJV"
    assert cfg.overview.width == 1920
    assert cfg.overview.height == 1080
    assert cfg.overview.pixel_format == "MJPG"
    assert cfg.overview.fps == 30.0

    assert cfg.science.role == "science"
    assert cfg.science.model == "ELP-U3CAM20MP01-IB(5-50B)"
    assert cfg.science.asin == "B0GMFN5RTD"
    assert cfg.science.width == 5120
    assert cfg.science.height == 3840
    assert cfg.science.pixel_format == "YUY2"
    assert cfg.science.fps == 7.5


def test_camera_config_from_dict_overrides_index():
    cfg = CameraConfig.from_dict({"science": {"index": 1}, "overview": {"index": 0}})
    assert cfg.science.index == 1
    assert cfg.overview.index == 0
    # unrelated defaults are preserved
    assert cfg.science.model == "ELP-U3CAM20MP01-IB(5-50B)"


def test_camera_config_from_env_reads_index_overrides(monkeypatch):
    monkeypatch.setenv("VPI_VISION_OVERVIEW_INDEX", "2")
    monkeypatch.setenv("VPI_VISION_SCIENCE_INDEX", "3")
    monkeypatch.setenv("VPI_VISION_SCIENCE_STABLE_ID", "usb-1.2")

    cfg = CameraConfig.from_env()

    assert cfg.overview.index == 2
    assert cfg.science.index == 3
    assert cfg.science.stable_id == "usb-1.2"


def test_camera_config_from_env_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("VPI_VISION_OVERVIEW_INDEX", raising=False)
    monkeypatch.delenv("VPI_VISION_SCIENCE_INDEX", raising=False)

    cfg = CameraConfig.from_env()

    assert cfg.overview.index == 0
    assert cfg.science.index == 1


def test_resolve_roles_stable_id_match_wins_over_configured_index():
    """Both ELP cameras enumerate alike; a stable_id map must override index order."""
    config = CameraConfig.from_dict({"overview": {"index": 0}, "science": {"index": 1}})
    # The OS enumerated them in the OPPOSITE order this time (index swap is common
    # for identical-VID/PID devices across reboots).
    enumerated = [
        {"index": 0, "stable_id": "usb-B-science"},
        {"index": 1, "stable_id": "usb-A-overview"},
    ]
    mapping = {"usb-A-overview": "overview", "usb-B-science": "science"}

    resolved = resolve_roles(enumerated, mapping, config)

    assert resolved["science"].index == 0
    assert resolved["science"].stable_id == "usb-B-science"
    assert resolved["overview"].index == 1
    assert resolved["overview"].stable_id == "usb-A-overview"


def test_resolve_roles_falls_back_to_configured_index_when_map_is_empty():
    config = CameraConfig.from_dict({"overview": {"index": 0}, "science": {"index": 1}})
    enumerated = [
        {"index": 0, "stable_id": "usb-unknown-0"},
        {"index": 1, "stable_id": "usb-unknown-1"},
    ]

    resolved = resolve_roles(enumerated, {}, config)

    assert resolved["overview"].index == 0
    assert resolved["science"].index == 1


def test_resolve_roles_falls_back_to_index_when_stable_id_not_in_mapping():
    config = CameraConfig.from_dict({"overview": {"index": 0}, "science": {"index": 1}})
    enumerated = [
        {"index": 0, "stable_id": "usb-new-0"},
        {"index": 1, "stable_id": "usb-new-1"},
    ]
    # mapping only knows about a device that isn't plugged in right now
    mapping = {"usb-old-device": "overview"}

    resolved = resolve_roles(enumerated, mapping, config)

    assert resolved["overview"].index == 0
    assert resolved["science"].index == 1


def test_resolve_roles_does_not_assign_two_roles_to_the_same_device():
    """I-2: only ONE device is enumerated (index 0). It is explicitly mapped to 'science' via
    stable_id. 'overview' has no stable_id mapping and must NOT fall back to grabbing the same
    device index -- that would auto-open two VideoCaptures on one physical camera. Instead
    'overview' must come back unresolved."""
    config = CameraConfig.from_dict({"overview": {"index": 0}, "science": {"index": 0}})
    enumerated = [{"index": 0, "stable_id": "usb-X", "name": "ELP cam"}]
    mapping = {"usb-X": "science"}

    resolved = resolve_roles(enumerated, mapping, config)

    assert resolved["science"].index == 0
    assert resolved["science"].stable_id == "usb-X"
    assert "overview" not in resolved

    assert unresolved_roles(enumerated, mapping) == ["overview"]


def test_save_and_load_role_map_round_trips(tmp_path: Path):
    path = tmp_path / "role_map.json"
    mapping = {"usb-A-overview": "overview", "usb-B-science": "science"}

    save_role_map(path, mapping)
    loaded = load_role_map(path)

    assert loaded == mapping


def test_load_role_map_returns_empty_dict_when_missing(tmp_path: Path):
    assert load_role_map(tmp_path / "does_not_exist.json") == {}


# ---- unresolved_roles (A7: auto-connect + persistent roles) ---------------------------------
def test_unresolved_roles_empty_when_both_roles_confidently_mapped():
    """A role counts resolved only when a CURRENTLY ENUMERATED device's stable_id is present
    in the persisted map for that role -- not merely via resolve_roles' index fallback."""
    enumerated = [
        {"index": 0, "stable_id": "usb-A-overview"},
        {"index": 1, "stable_id": "usb-B-science"},
    ]
    mapping = {"usb-A-overview": "overview", "usb-B-science": "science"}
    assert unresolved_roles(enumerated, mapping) == []


def test_unresolved_roles_lists_role_when_mapping_is_empty():
    enumerated = [
        {"index": 0, "stable_id": "usb-unknown-0"},
        {"index": 1, "stable_id": "usb-unknown-1"},
    ]
    assert unresolved_roles(enumerated, {}) == ["overview", "science"]


def test_unresolved_roles_lists_role_when_mapped_stable_id_not_currently_plugged_in():
    """The map knows about a device that isn't enumerated right now (swapped/unplugged) --
    that role must be reported unresolved even though resolve_roles would still fall back to
    an index guess for it."""
    enumerated = [
        {"index": 0, "stable_id": "usb-new-0"},
        {"index": 1, "stable_id": "usb-B-science"},
    ]
    mapping = {"usb-old-overview": "overview", "usb-B-science": "science"}
    assert unresolved_roles(enumerated, mapping) == ["overview"]


def test_unresolved_roles_ignores_devices_with_no_stable_id():
    enumerated = [{"index": 0, "stable_id": None}]
    assert unresolved_roles(enumerated, {}) == ["overview", "science"]


# ---- enumerate_devices (A7: real best-effort enumerator, hardware-verified not unit-tested) --
def test_enumerate_devices_returns_a_list_and_never_raises():
    # No camera hardware assumed present in CI; this only proves the guarded, bounded probe
    # completes and returns a list (possibly empty) rather than raising.
    result = enumerate_devices(max_index=1)
    assert isinstance(result, list)


# ---- camera_access_state (camera-permission signal) -------------------------------------------
# Pure aggregation over enumerated devices' `has_frame` flags -- no hardware needed. Mirrors the
# macOS "camera permission not granted" signature: VideoCapture.isOpened() succeeds (the device
# enumerates) but every read() fails, so a device is present yet never yields a frame.
def test_camera_access_state_ok_when_at_least_one_device_has_a_frame():
    devices = [
        {"index": 0, "stable_id": "usb-A", "has_frame": False},
        {"index": 1, "stable_id": "usb-B", "has_frame": True},
    ]
    assert camera_access_state(devices) == "ok"


def test_camera_access_state_denied_when_devices_present_but_none_yield_a_frame():
    devices = [
        {"index": 0, "stable_id": "usb-A", "has_frame": False},
        {"index": 1, "stable_id": "usb-B", "has_frame": False},
    ]
    assert camera_access_state(devices) == "denied"


def test_camera_access_state_no_devices_when_enumeration_is_empty():
    assert camera_access_state([]) == "no_devices"


def test_camera_access_state_treats_missing_has_frame_key_as_no_frame():
    """An enumerator that hasn't been upgraded to report `has_frame` must not silently read as
    healthy -- a missing key is treated the same as `False` (data-contract-verification: unknown
    must never render as verified-good)."""
    assert camera_access_state([{"index": 0, "stable_id": "usb-A"}]) == "denied"


# ---- enumerate_devices has_frame probe (stubbed cv2.VideoCapture, no real hardware) -----------
class _StubVideoCapture:
    """Fake `cv2.VideoCapture` exposing exactly the surface `enumerate_devices` uses."""

    def __init__(self, read_ok: bool) -> None:
        self._read_ok = read_ok
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors cv2.VideoCapture's method name
        return True

    def read(self) -> tuple[bool, Any]:
        if self._read_ok:
            return True, np.zeros((4, 4, 3), dtype=np.uint8)
        return False, None

    def release(self) -> None:
        self.released = True


def test_enumerate_devices_marks_has_frame_true_when_read_succeeds(monkeypatch):
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **k: _StubVideoCapture(read_ok=True))
    devices = enumerate_devices(max_index=1)
    assert len(devices) == 1
    assert devices[0]["has_frame"] is True


def test_enumerate_devices_marks_has_frame_false_when_opened_but_read_fails(monkeypatch):
    """The macOS "not authorized" signature: isOpened() succeeds but every read() fails."""
    import cv2

    monkeypatch.setattr(cv2, "VideoCapture", lambda *a, **k: _StubVideoCapture(read_ok=False))
    devices = enumerate_devices(max_index=1)
    assert len(devices) == 1
    assert devices[0]["has_frame"] is False
