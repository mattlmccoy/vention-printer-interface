"""Browser uploads must work without server-owned camera hardware."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from vention_printer_interface.api.app import create_app
from vention_printer_interface.vision.registration import Calibration, save_calibration


@pytest.mark.parametrize("calibrated", [False, True])
def test_browser_upload_without_server_camera(tmp_path: Path, calibrated: bool) -> None:
    if calibrated:
        save_calibration(
            tmp_path / ".vision_calibration.json",
            Calibration(
                H=np.eye(3),
                mm_per_px=1.0,
                bed_extent_mm=(0.0, 0.0, 8.0, 8.0),
                version="browser-regression",
                reprojection_error=0.0,
            ),
        )
    app = create_app(backend="none", experiments_root=tmp_path, device_enumerator=lambda: [])
    with TestClient(app) as client:
        assert app.state.vision is None
        run = client.post("/api/recording/start", json={"name": "browser-only"}).json()["run"]
        image = np.zeros((64, 64, 3), np.uint8)
        image[:, 32:] = 255
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        url = "/api/vision/science/capture?layer=7&stage=post_jet&cad_layer=2"
        response = client.post(url, content=encoded.tobytes())
        assert response.status_code == 200, response.text
        records = client.get("/api/vision/captures", params={"run": run}).json()
        assert len(records) == 1
        assert records[0]["layer"] == 7 and records[0]["cad_layer"] == 2
        assert client.get(records[0]["url"]).status_code == 200
        meta = client.get(records[0]["sidecar_url"]).json()
        assert meta["source"] == "client"
        assert meta["camera"]["role"] == "science"
        assert (meta["calibration"] is not None) == calibrated
        if calibrated:
            assert meta["calibration"]["version"] == "browser-regression"
            assert meta["registered_space"]["mm_per_px"] == 1.0
        assert app.state.vision is None
        assert client.post(url, content=b"").status_code == 400
        assert client.post(url, content=b"not an image").status_code == 400
        client.post("/api/recording/stop")
        assert client.post(url, content=encoded.tobytes()).status_code == 409
