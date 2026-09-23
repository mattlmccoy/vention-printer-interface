"""Truncated-frame guard (vision/frame_integrity.py).

Real fixture: truncated_yuy2_20mp_windows_screenshot.png -- the operator's screenshot (2026-09-23,
Windows lab PC, ELP science camera at 5120x3840 YUY2 through a USB hub shared with a USB-Ethernet
adapter). The frame stopped arriving about 2/3 of the way down: torn rows, then a solid band whose
rows all average (147, 226, 130) -- unfilled YUY2 data decodes green. It is a screenshot (scaled,
compressed), so rows are not pixel-identical; the detector must not rely on exact repeats.

Known-good fixtures: real print-camera crops already in the repo (first-good-test) and the real
(dark) top of the corrupted frame itself -- dark regions also change slowly row to row.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from vention_printer_interface.vision.frame_integrity import frame_truncation

FIX = Path(__file__).parent
CORRUPT = FIX / "fixtures/frames/truncated_yuy2_20mp_windows_screenshot.png"
GOOD = [FIX / "analysis/fixtures/first-good-test/checkerboard_roi.png",
        FIX / "analysis/fixtures/first-good-test/dot_roi.png"]


def _rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def test_the_real_truncated_frame_is_caught_with_a_reason() -> None:
    reason = frame_truncation(_rgb(CORRUPT))
    assert reason is not None and "truncated" in reason


def test_real_print_frames_pass() -> None:
    for path in GOOD:
        assert frame_truncation(_rgb(path)) is None, path.name


def test_a_dark_but_real_region_passes() -> None:
    assert frame_truncation(_rgb(CORRUPT)[:170]) is None  # the real top of the same frame


def test_a_flat_grey_bottom_is_not_called_truncated() -> None:
    # e.g. an evenly lit, out-of-focus powder band: flat but not the green unfilled-data colour
    img = _rgb(GOOD[0]).copy()
    img[-img.shape[0] // 5:] = 180
    assert frame_truncation(img) is None


def test_a_frame_with_no_real_image_above_the_band_is_not_truncation() -> None:
    # The simulator's test pattern is one green ramp repeated on every row: flat and green like an
    # unfilled band, but a truncated transfer has REAL data above where it stopped.
    ramp = np.zeros((24, 32, 3), np.uint8)
    ramp[:, :, 1] = np.linspace(0, 255, 32, dtype=np.uint8)[None, :]
    assert frame_truncation(ramp, order="bgr") is None


def test_bgr_order_from_opencv_is_handled() -> None:
    # cv2.imdecode returns BGR; the guard is told the channel order
    assert frame_truncation(_rgb(CORRUPT)[..., ::-1], order="bgr") is not None


# ---- wired in where science stills are stored ---------------------------------------------------

def test_store_uploaded_refuses_the_truncated_frame_before_writing(tmp_path: Path) -> None:
    import pytest

    from tests.test_vision_capture import _svc

    svc = _svc(tmp_path, camera_role="science")
    with pytest.raises(ValueError, match="truncated"):
        bgr = _rgb(CORRUPT)[..., ::-1].copy()  # BGR, as cv2 decodes it
        svc.store_uploaded(bgr, layer=1, stage="post_jet")
    assert not (tmp_path / "vision").exists()


def test_upload_endpoint_refuses_the_truncated_frame_with_the_reason(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app
    from vention_printer_interface.vision.frame_source import SimulatedFrameSource

    app = create_app(backend="none", experiments_root=tmp_path,
                     vision_source=SimulatedFrameSource(width=32, height=24))
    with TestClient(app) as c:
        run = c.post("/api/recording/start", json={"name": "truncated-cap"}).json()["run"]
        r = c.post("/api/vision/science/capture?layer=1&stage=post_jet",
                   content=CORRUPT.read_bytes(), headers={"content-type": "image/png"})
        assert r.status_code == 422 and "truncated" in r.json()["detail"]
        assert not (tmp_path / run / "vision").exists()
        c.post("/api/recording/stop")


def test_the_simulated_camera_frame_passes_the_capture_guards() -> None:
    # The simulator stands in for a real camera in the sim backend and the e2e tests, so its test
    # pattern must look like a camera frame -- not like a truncated one (content above a flat,
    # green band that never changes down the columns).
    from vention_printer_interface.vision.capture import image_has_usable_content
    from vention_printer_interface.vision.frame_source import SimulatedFrameSource

    for w, h in ((32, 24), (640, 480)):
        src = SimulatedFrameSource(width=w, height=h)
        src.open()
        img = src.grab().image
        assert image_has_usable_content(img)
        assert frame_truncation(img, order="bgr") is None, (w, h)
