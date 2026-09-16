"""Meteor firing-adapter readiness (control/meteor.py).

The operator drives the axes; Meteor MetPrint fires the printhead from the hot folder. Before the
choreography sweeps the printhead, the adapter must answer one honest question: does Meteor actually
have a COMPLETE job loaded for this build? A missing/incomplete job must read as NOT ready, never as
a false green (else the operator spreads powder and sweeps over a bed that gets no binder).
"""

import json
from pathlib import Path

from PIL import Image

from vention_printer_interface.control.meteor import (
    HotFolderMeteorAdapter,
    MeteorStatus,
    SimulatedMeteorAdapter,
)
from vention_printer_interface.jobs.store import load_job

_INFO = {
    "generated_by": "Meteor RIP",
    "job_name": "METEOR-TEST",
    "layer_count": 3,
    "tiff_count": 3,
    "bbox_mm": {"x_mm": 20.0, "y_mm": 20.0, "z_mm": 0.3},
    "height_mm": 0.3,
    "dpi": 720,
    "bpp": 2,
    "color_plane": 1,
    "timestamp": "2026-09-16T00:00:00",
}


def make_job(root: Path, name: str = "20260916_000000_METEOR-TEST", layers: int = 3) -> Path:
    d = root / name
    d.mkdir(parents=True)
    info = {**_INFO, "layer_count": layers, "tiff_count": layers, "height_mm": layers * 0.1}
    (d / "job_info.json").write_text(json.dumps(info))
    for n in range(1, layers + 1):
        Image.new("L", (60, 20), 255).save(
            d / f"METEOR-TEST_Page{n}_Clr1.tif", compression="tiff_lzw"
        )
    return d


def test_hot_folder_ready_when_job_complete_under_root(tmp_path: Path) -> None:
    d = make_job(tmp_path)
    job = load_job(d)
    a = HotFolderMeteorAdapter([tmp_path])
    st = a.status(job)
    assert isinstance(st, MeteorStatus)
    assert st.backend == "hot_folder"
    assert st.available is True
    assert st.ready is True
    assert st.job_name == "METEOR-TEST"
    assert st.layers_ready == 3 and st.layers_expected == 3


def test_hot_folder_not_ready_when_job_incomplete(tmp_path: Path) -> None:
    # A dropped page => Meteor would fire the wrong/short stack. Must NOT be green.
    d = make_job(tmp_path)
    (d / "METEOR-TEST_Page2_Clr1.tif").unlink()
    job = load_job(d)
    st = HotFolderMeteorAdapter([tmp_path]).status(job)
    assert st.ready is False
    assert st.layers_ready == 2 and st.layers_expected == 3
    assert "missing" in st.detail.lower() or "incomplete" in st.detail.lower()


def test_hot_folder_not_ready_without_job(tmp_path: Path) -> None:
    # No job selected is the classic false-green trap: absence must be distinct from ready.
    st = HotFolderMeteorAdapter([tmp_path]).status(None)
    assert st.available is True  # the folder exists
    assert st.ready is False
    assert st.job_name is None


def test_hot_folder_unavailable_when_root_missing(tmp_path: Path) -> None:
    st = HotFolderMeteorAdapter([tmp_path / "nope"]).status(None)
    assert st.available is False
    assert st.ready is False


def test_hot_folder_not_ready_when_job_outside_watched_root(tmp_path: Path) -> None:
    # A complete job that MetPrint does NOT watch is not armable — ready must be false.
    watched = tmp_path / "watched"
    watched.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    job = load_job(make_job(other))
    st = HotFolderMeteorAdapter([watched]).status(job)
    assert st.ready is False
    assert "root" in st.detail.lower() or "watch" in st.detail.lower()


def test_simulated_ready_and_records_fired_layers(tmp_path: Path) -> None:
    job = load_job(make_job(tmp_path))
    a = SimulatedMeteorAdapter()
    assert a.status(job).ready is True
    assert a.status(None).ready is False
    a.fire_layer(1)
    a.fire_layer(2)
    a.end_job()
    assert a.fired == [1, 2]
    assert a.ended is True
