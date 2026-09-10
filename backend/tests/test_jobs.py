"""Job intake against the REAL Meteor RIP layout captured from the lab hot folder
(code/rfam-web/Hot Folder/20260414_171155_8MM-ROD-CLAMPS-03MM-TOL/job_info.json)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from vention_printer_interface.jobs.store import JobInfo, JobStore, layer_png, load_job

SAMPLE_INFO = {  # captured 2026-09-09, field for field
    "generated_by": "Meteor RIP",
    "job_name": "8MM-ROD-CLAMPS-03MM-TOL",
    "slice_id": "83f54364",
    "layer_count": 50,
    "tiff_count": 50,
    "bbox_mm": {"x_mm": 58.2, "y_mm": 56.0, "z_mm": 5.0},
    "height_mm": 5.0,
    "part_vol_mm3": 449.6,
    "dpi": 720,
    "bpp": 2,
    "compression": "lzw",
    "color_plane": 1,
    "elapsed_sec": 0.3,
    "timestamp": "2026-04-14T17:11:55.911345",
}


def make_job(
    root: Path, name: str = "20260414_171155_8MM-ROD-CLAMPS-03MM-TOL", layers: int = 3
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    info = {**SAMPLE_INFO, "layer_count": layers, "tiff_count": layers, "height_mm": layers * 0.1}
    (d / "job_info.json").write_text(json.dumps(info))
    for n in range(1, layers + 1):  # pages are 1-based: <job>_Page<N>_Clr1.tif
        im = Image.new("L", (300, 30), 255)  # as Pillow loads them: 255 = paper, 0 = ink
        for x in range(10, 10 + n * 5):
            for y in range(5, 25):
                im.putpixel((x, y), 0)
        im.save(d / f"{SAMPLE_INFO['job_name']}_Page{n}_Clr1.tif", compression="tiff_lzw")
    return d


def test_load_job_reads_manifest_and_orders_pages_numerically(tmp_path: Path) -> None:
    d = make_job(tmp_path, layers=12)
    job = load_job(d)
    assert isinstance(job, JobInfo)
    assert job.name == "8MM-ROD-CLAMPS-03MM-TOL" and job.layer_count == 12
    assert job.layer_height_mm == pytest.approx(0.1)
    assert job.bbox_mm[:2] == (58.2, 56.0) and job.bbox_mm[2] == pytest.approx(1.2)
    assert job.dpi == 720 and job.bpp == 2
    assert [p.name for p in job.pages][:3] == [
        "8MM-ROD-CLAMPS-03MM-TOL_Page1_Clr1.tif",
        "8MM-ROD-CLAMPS-03MM-TOL_Page2_Clr1.tif",
        "8MM-ROD-CLAMPS-03MM-TOL_Page3_Clr1.tif",
    ]
    assert job.pages[9].name.endswith("_Page10_Clr1.tif")  # numeric, not lexical, order
    assert job.complete is True


def test_missing_pages_marks_job_incomplete(tmp_path: Path) -> None:
    d = make_job(tmp_path, layers=3)
    (d / "8MM-ROD-CLAMPS-03MM-TOL_Page2_Clr1.tif").unlink()
    job = load_job(d)
    assert job.complete is False and job.missing_pages == [2]


def test_store_scans_roots_newest_first_and_skips_junk(tmp_path: Path) -> None:
    make_job(tmp_path / "hot" / "_archive", "20260413_113827_a", 2)
    make_job(tmp_path / "hot" / "_archive", "20260414_110620_b", 2)
    (tmp_path / "hot" / "_archive" / "junk").mkdir()
    (tmp_path / "hot" / "stray.tif").write_bytes(b"")
    store = JobStore([tmp_path / "hot", tmp_path / "missing"])
    names = [j.dir.name for j in store.scan()]
    assert names == ["20260414_110620_b", "20260413_113827_a"]


def test_layer_png_renders_ink_and_is_cached(tmp_path: Path) -> None:
    job = load_job(make_job(tmp_path, layers=2))
    png1 = layer_png(job, 1, max_px=200)
    assert png1[:8] == b"\x89PNG\r\n\x1a\n"
    im = Image.open(__import__("io").BytesIO(png1))
    assert im.size[0] <= 200 and im.mode == "L"
    assert im.getpixel((0, 0)) == 255  # paper is white
    assert im.getpixel((int(12 * im.size[0] / 300), im.size[1] // 2)) == 0  # ink is black
    assert layer_png(job, 1, max_px=200) is png1  # cached object
    with pytest.raises(IndexError):
        layer_png(job, 3)


def test_job_to_print_settings_patch(tmp_path: Path) -> None:
    # The job dictates ONLY the layer COUNT; the layer thickness stays the operator's selected
    # (standard) value. The slicer-derived layer_height_mm is kept for informational display only.
    job = load_job(make_job(tmp_path, layers=50))
    patch = job.print_settings_patch()
    assert patch == {"printing": {"n_layers": 50}}
    assert "layer_thickness_mm" not in patch["printing"]
    assert job.layer_height_mm == pytest.approx(0.1)  # still available for the "slicer: X mm" label
