"""Timelapse assembly (#4): per-layer stills -> ordered frames -> looping GIF."""

import io
from pathlib import Path

from PIL import Image

from vention_printer_interface.vision.store import append_manifest
from vention_printer_interface.vision.timelapse import (
    best_stage,
    build_timelapse_gif,
    timelapse_frames,
)


def _still(base: Path, layer: int, stage: str, color: tuple[int, int, int]) -> None:
    """Write a registered still + its manifest record, mirroring how captures are stored."""
    rel = f"vision/layer_{layer:04d}/{stage}.png"
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), color).save(p)
    append_manifest(base, {"layer": layer, "stage": stage, "registered": rel})


def test_timelapse_frames_orders_by_layer_and_filters_stage(tmp_path: Path) -> None:
    # Write out of order + a different stage; frames come back stage-filtered, layer-ordered.
    _still(tmp_path, 5, "post_heat", (10, 10, 10))
    _still(tmp_path, 3, "post_heat", (20, 20, 20))
    _still(tmp_path, 4, "post_jet", (30, 30, 30))
    frames = timelapse_frames(tmp_path, "post_heat")
    assert [p.parent.name for p in frames] == ["layer_0003", "layer_0005"]


def test_best_stage_prefers_the_stage_with_the_most_frames(tmp_path: Path) -> None:
    _still(tmp_path, 1, "post_jet", (1, 1, 1))
    _still(tmp_path, 2, "post_jet", (2, 2, 2))
    _still(tmp_path, 1, "post_heat", (3, 3, 3))
    assert best_stage(tmp_path) == "post_jet"


def test_best_stage_is_none_without_captures(tmp_path: Path) -> None:
    assert best_stage(tmp_path) is None


def test_build_timelapse_gif_returns_a_multiframe_gif(tmp_path: Path) -> None:
    for layer in (1, 2, 3):
        _still(tmp_path, layer, "post_heat", (layer * 40, 0, 0))
    data = build_timelapse_gif(tmp_path, "post_heat", fps=8.0)
    assert data is not None
    gif = Image.open(io.BytesIO(data))
    assert gif.format == "GIF"
    assert getattr(gif, "n_frames", 1) == 3


def test_build_timelapse_gif_none_when_no_frames(tmp_path: Path) -> None:
    assert build_timelapse_gif(tmp_path, "post_heat") is None


def test_timelapse_endpoint_serves_gif_and_404s_when_empty(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        c.post("/api/recording/start", json={"name": "tl-run"})
        run = c.get("/api/recordings").json()["runs"][-1]["run"]
        run_dir = tmp_path / run
        # No stills yet -> 404.
        assert c.get(f"/api/recordings/{run}/timelapse.gif").status_code == 404
        # Add three post_heat stills, then it serves a GIF.
        for layer in (1, 2, 3):
            _still(run_dir, layer, "post_heat", (0, layer * 40, 0))
        r = c.get(f"/api/recordings/{run}/timelapse.gif")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/gif"
        assert r.content[:6] in (b"GIF87a", b"GIF89a")
        # bad run name -> 400
        assert c.get("/api/recordings/../timelapse.gif").status_code in (400, 404)


def _overview_frame(base: Path, seq: int, color: tuple[int, int, int]) -> None:
    d = base / "overview"
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), color).save(d / f"{seq:06d}.webp")


def test_overview_frames_are_time_ordered(tmp_path: Path) -> None:
    from vention_printer_interface.vision.timelapse import overview_frames

    _overview_frame(tmp_path, 2, (2, 2, 2))
    _overview_frame(tmp_path, 0, (0, 0, 0))
    _overview_frame(tmp_path, 1, (1, 1, 1))
    assert [p.stem for p in overview_frames(tmp_path)] == ["000000", "000001", "000002"]


def test_build_overview_timelapse_gif(tmp_path: Path) -> None:
    from vention_printer_interface.vision.timelapse import build_overview_timelapse_gif

    assert build_overview_timelapse_gif(tmp_path) is None  # no frames
    for i in range(4):
        _overview_frame(tmp_path, i, (i * 30, 0, 0))
    data = build_overview_timelapse_gif(tmp_path, fps=10.0)
    assert data is not None
    gif = Image.open(io.BytesIO(data))
    assert gif.format == "GIF" and getattr(gif, "n_frames", 1) == 4


def test_write_overview_frame_sequences(tmp_path: Path) -> None:
    import numpy as np

    from vention_printer_interface.vision.store import write_overview_frame

    img = np.zeros((12, 16, 3), np.uint8)
    p0 = write_overview_frame(tmp_path, img)
    p1 = write_overview_frame(tmp_path, img)
    assert p0.name == "000000.webp" and p1.name == "000001.webp"


def test_overview_capture_endpoint_and_timelapse_source(tmp_path: Path) -> None:
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient

    from vention_printer_interface.api.app import create_app

    app = create_app(backend="none", experiments_root=tmp_path, poll_interval_s=0.05)
    with TestClient(app) as c:
        # no run recording -> 409
        png = cv2.imencode(".png", np.zeros((12, 16, 3), np.uint8))[1].tobytes()
        assert c.post("/api/vision/overview/capture", content=png).status_code == 409
        c.post("/api/recording/start", json={"name": "ov-run"})
        run = c.get("/api/recordings").json()["runs"][-1]["run"]
        for _ in range(3):
            assert c.post("/api/vision/overview/capture", content=png).status_code == 200
        # overview timelapse serves a GIF; science source 404s (no science stills)
        r = c.get(f"/api/recordings/{run}/timelapse.gif?source=overview")
        assert r.status_code == 200 and r.content[:6] in (b"GIF87a", b"GIF89a")
        assert c.get(f"/api/recordings/{run}/timelapse.gif?source=science").status_code == 404
        assert c.get(f"/api/recordings/{run}/timelapse.gif?source=bogus").status_code == 400
