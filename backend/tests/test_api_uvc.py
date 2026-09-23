"""/api/vision/uvc/* -- operator-side UVC camera controls (the Mac path; the browser exposes
none of them on macOS). Uses the captured-data FakeCamera from test_uvc."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_uvc import FIX, FakeCamera
from vention_printer_interface.api.app import create_app

ELP_A, ELP_B = "0x23100032e42020", "0x23400032e42020"
FACETIME = "3F45E80A-0176-46F7-B185-BB9E2C0E82E3"


class FakeDevice(FakeCamera):
    def __init__(self, uid: str) -> None:
        super().__init__(uid)
        self._desc = bytes.fromhex((FIX / f"elp_20mp_{uid}.desc.hex").read_text())

    def config_descriptor(self) -> bytes:
        return self._desc


class FakeBackend:
    def __init__(self) -> None:
        self.devices = {ELP_A: FakeDevice(ELP_A), ELP_B: FakeDevice(ELP_B)}

    def cameras(self) -> list[dict[str, str]]:
        return [{"unique_id": u, "name": "20MP U3 Camera"} for u in self.devices] + [
            {"unique_id": FACETIME, "name": "FaceTime HD Camera"}]

    @contextmanager
    def open(self, unique_id: str) -> Iterator[FakeDevice]:
        if unique_id not in self.devices:
            raise KeyError(unique_id)
        yield self.devices[unique_id]


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(tmp_path: Path, backend: FakeBackend) -> Iterator[TestClient]:
    app = create_app(backend="none", experiments_root=tmp_path, uvc_backend=backend)
    with TestClient(app) as c:
        yield c


def test_lists_uvc_cameras_and_hides_ignored_ones(client: TestClient) -> None:
    client.put("/api/vision/ignored-cameras", json={"unique_ids": [FACETIME]})
    r = client.get("/api/vision/uvc").json()
    assert r["available"] is True
    assert [c["unique_id"] for c in r["cameras"]] == [ELP_A, ELP_B]


def test_controls_come_from_the_camera(client: TestClient) -> None:
    c = {x["key"]: x for x in client.get(f"/api/vision/uvc/{ELP_A}/controls").json()["controls"]}
    assert c["brightness"]["default"] == 128 and c["exposure"]["max"] == 10000


def test_set_a_control_and_read_it_back(client: TestClient) -> None:
    r = client.put(f"/api/vision/uvc/{ELP_A}/controls", json={"key": "brightness", "value": 90})
    assert r.status_code == 200
    c = {x["key"]: x for x in r.json()["controls"]}
    assert c["brightness"]["value"] == 90


def test_out_of_range_is_a_400_with_the_range(client: TestClient) -> None:
    r = client.put(f"/api/vision/uvc/{ELP_A}/controls", json={"key": "brightness", "value": 999})
    assert r.status_code == 400 and "0..255" in r.json()["detail"]


def test_reset_restores_factory_defaults(client: TestClient) -> None:
    client.put(f"/api/vision/uvc/{ELP_A}/controls", json={"key": "exposure", "value": 900})
    r = client.post(f"/api/vision/uvc/{ELP_A}/reset").json()
    c = {x["key"]: x for x in r["controls"]}
    assert r["failed"] == {} and c["exposure"]["value"] == 156 and c["exposure_auto"]["value"]


def test_unknown_or_ignored_camera_is_404(client: TestClient) -> None:
    assert client.get("/api/vision/uvc/0xdead/controls").status_code == 404
    client.put("/api/vision/ignored-cameras", json={"unique_ids": [ELP_B]})
    assert client.get(f"/api/vision/uvc/{ELP_B}/controls").status_code == 404


def test_no_backend_says_why(tmp_path: Path) -> None:
    app = create_app(backend="none", experiments_root=tmp_path, uvc_backend=None)
    with TestClient(app) as c:
        r = c.get("/api/vision/uvc").json()
    assert r["available"] is False and r["cameras"] == [] and r["reason"]
