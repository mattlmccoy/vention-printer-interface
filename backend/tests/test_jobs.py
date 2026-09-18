"""Job intake against the REAL Meteor RIP layout captured from the lab hot folder
(code/rfam-web/Hot Folder/20260414_171155_8MM-ROD-CLAMPS-03MM-TOL/job_info.json)."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vention_printer_interface.jobs.store import (
    JobInfo,
    JobStore,
    _remap_ink_levels,
    layer_png,
    load_job,
)

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


def test_remap_ink_levels_renders_max_aquinox_level_black() -> None:
    # REAL PIL output for an Xaar Aquinox 8-grey-level page in a 4-bit container (captured from the
    # hot-folder FGM jobs): PIL scales on 2**bpp-1 = 15, so level k -> 255 - k*17, and max ink
    # (level 7) shows as 136 (mid-grey) — the bug. The remap must render level 7 BLACK, 0 WHITE.
    arr = np.array([[255, 238, 221, 204, 187, 170, 153, 136]], dtype=np.uint8)  # levels 0..7
    out = _remap_ink_levels(arr, bpp=4, grey_levels=8)
    assert out[0, 0] == 255   # level 0 -> white
    assert out[0, -1] == 0    # level 7 -> full black (was 136)
    assert list(out[0]) == [255, 219, 182, 146, 109, 73, 36, 0]  # even white->black ramp


def test_remap_ink_levels_is_a_noop_when_levels_equal_the_container() -> None:
    # Old 2bpp job (grey_levels == 2**bpp == 4): container_max == grey_levels-1, so the already-
    # correct rendering (level 3 -> 0 black) must be preserved unchanged.
    arr = np.array([[255, 170, 85, 0]], dtype=np.uint8)  # 2bpp levels 0..3 (255 - k*85)
    out = _remap_ink_levels(arr, bpp=2, grey_levels=4)
    assert list(out[0]) == [255, 170, 85, 0]


def test_load_job_grey_levels_default_is_bpp_aware(tmp_path: Path) -> None:
    # The Meteor RIP now writes grey_levels; older jobs lack it. Default so a 4-bit container is the
    # Aquinox's 8 levels (fixes the mid-grey preview) WITHOUT breaking a 2bpp job (4 levels, where
    # container==levels and the remap is a no-op). An explicit key always wins.
    d = tmp_path / "j4"
    d.mkdir()
    (d / "job_info.json").write_text(json.dumps({**SAMPLE_INFO, "bpp": 4}))  # 4bpp, no grey_levels
    assert load_job(d).grey_levels == 8
    d2 = tmp_path / "j2"
    d2.mkdir()
    (d2 / "job_info.json").write_text(json.dumps({**SAMPLE_INFO, "bpp": 2}))  # 2bpp, no grey_levels
    assert load_job(d2).grey_levels == 4
    d3 = tmp_path / "j3"
    d3.mkdir()
    (d3 / "job_info.json").write_text(json.dumps({**SAMPLE_INFO, "bpp": 4, "grey_levels": 8}))
    assert load_job(d3).grey_levels == 8


def test_job_to_print_settings_patch(tmp_path: Path) -> None:
    # The job dictates ONLY the layer COUNT; the layer thickness stays the operator's selected
    # (standard) value. The slicer-derived layer_height_mm is kept for informational display only.
    job = load_job(make_job(tmp_path, layers=50))
    patch = job.print_settings_patch()
    assert patch == {"printing": {"n_layers": 50}}
    assert "layer_thickness_mm" not in patch["printing"]
    assert job.layer_height_mm == pytest.approx(0.1)  # still available for the "slicer: X mm" label


# Captured 2026-09-14 from a real RIP _archive/.../job_info.json in the hot folder.
# A RIP (2D multi-pass) job: NO layer_count, NO bbox, TIFFs named <name>_Pass<N>_Page1_Clr1.tif.
RIP_INFO = {
    "generated_by": "Meteor RIP",
    "source_file": "gold_standard_300dpi_20260319_233656.pdf",
    "job_id": "9aa4788b",
    "workflow": "rip",
    "tiff_count": 4,
    "tiff_files": [
        "g_Pass1_Page1_Clr1.tif", "g_Pass2_Page1_Clr1.tif",
        "g_Pass3_Page1_Clr1.tif", "g_Pass4_Page1_Clr1.tif",
    ],
    "dpi": 720, "bpp": 4, "compression": "lzw", "color_plane": 1,
    "elapsed_sec": 56.7, "timestamp": "2026-09-14T19:22:32.940180",
}


def make_rip_job(root: Path, name: str = "20260914_192136_gold_standard", passes: int = 4) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "job_info.json").write_text(json.dumps(RIP_INFO))
    for p in range(1, passes + 1):  # all passes are Page1 — one printed layer, N jetting passes
        im = Image.new("L", (300, 30), 255)
        im.save(d / f"g_Pass{p}_Page1_Clr1.tif", compression="tiff_lzw")
    return d


def test_rip_job_is_loaded_as_single_layer(tmp_path: Path) -> None:
    # Regression: a RIP manifest has no layer_count, so load_job raised KeyError and scan()
    # silently dropped it — the job never appeared in the console. A RIP job is ONE printed
    # layer (all pages are Page1); it must load, not crash.
    job = load_job(make_rip_job(tmp_path))
    assert job.layer_count == 1
    assert len(job.pages) == 1
    assert job.complete is True
    assert job.dpi == 720 and job.bpp == 4


def test_scan_finds_rip_job(tmp_path: Path) -> None:
    make_rip_job(tmp_path / "hot", "20260914_192136_gold_standard")
    jobs = JobStore([tmp_path / "hot"]).scan()
    assert any(j.layer_count == 1 for j in jobs), "RIP job must be discoverable by scan()"


def test_job_finds_slicer_splash_preview(tmp_path: Path) -> None:
    # 3D slicer jobs ship an isometric splash image, but the filename has varied across versions
    # (<name>.bmp, <name>_preview.bmp, <name>.stl_Preview). JobStore must find whichever exists so
    # the console can render it. Real captured names: "8MM..._preview.bmp", "..._v1.stl_Preview".
    d = make_job(tmp_path / "a", layers=3)
    (d / "8MM-ROD-CLAMPS-03MM-TOL_preview.bmp").write_bytes(b"BM preview")  # SAMPLE job_name
    job = load_job(d)
    assert job.preview is not None
    assert job.preview.name == "8MM-ROD-CLAMPS-03MM-TOL_preview.bmp"
    assert job.to_dict()["has_preview"] is True


def test_job_without_splash_has_no_preview(tmp_path: Path) -> None:
    job = load_job(make_job(tmp_path / "b", layers=2))  # make_job writes no .bmp
    assert job.preview is None
    assert job.to_dict()["has_preview"] is False


def test_job_kind_2d_vs_3d(tmp_path: Path) -> None:
    # A RIP job (workflow "rip") is a 2D print; a slicer job (or many layers) is 3D. The UI shows
    # a badge from this, so it must be right for new AND old (workflow-less) jobs.
    rip = load_job(make_rip_job(tmp_path / "a"))
    assert rip.workflow == "rip" and rip.kind == "2D"

    sliced = load_job(make_job(tmp_path / "b", layers=50))  # SAMPLE_INFO has no workflow field
    assert sliced.kind == "3D"          # falls back to layer_count (50 > 1) -> 3D
    assert sliced.to_dict()["kind"] == "3D"

    one_layer = load_job(make_job(tmp_path / "c", layers=1))
    assert one_layer.kind == "2D"       # a single-layer, workflow-less job reads as 2D


_mk_counter = [0]


def _mk_single_layer(root: Path, extra: dict) -> Path:
    """A one-layer job with `extra` merged into a real-shaped job_info (for multipass import)."""
    _mk_counter[0] += 1
    d = root / f"mp{_mk_counter[0]}"
    d.mkdir(parents=True)
    (d / "job_info.json").write_text(
        json.dumps({**SAMPLE_INFO, "layer_count": 1, "tiff_count": 1, "height_mm": 0.1, **extra})
    )
    Image.new("L", (10, 10), 255).save(
        d / f"{SAMPLE_INFO['job_name']}_Page1_Clr1.tif", compression="tiff_lzw"
    )
    return d


def test_load_job_multipass_absent_is_none(tmp_path: Path) -> None:
    # The REAL captured slicer output (SAMPLE_INFO) carries no multipass field, so import must be
    # None — never an invented default (data-contract: absence is not a value).
    assert load_job(make_job(tmp_path)).slicer_multipass is None


def test_load_job_reads_slicer_multipass_when_present(tmp_path: Path) -> None:
    # Forward-compatible: IF the Meteor RIP begins writing a multipass factor, import it verbatim.
    assert load_job(_mk_single_layer(tmp_path, {"multipass": 3})).slicer_multipass == 3


def test_load_job_multipass_accepts_known_aliases(tmp_path: Path) -> None:
    assert load_job(_mk_single_layer(tmp_path, {"jet_passes": 2})).slicer_multipass == 2


def test_load_job_multipass_ignores_junk(tmp_path: Path) -> None:
    # Non-positive / non-int values are not a real multipass factor -> None, not a bogus number.
    assert load_job(_mk_single_layer(tmp_path, {"multipass": 0})).slicer_multipass is None
    assert load_job(_mk_single_layer(tmp_path, {"multipass": "lots"})).slicer_multipass is None


def test_load_job_multipass_in_to_dict(tmp_path: Path) -> None:
    assert load_job(_mk_single_layer(tmp_path, {"multipass": 4})).to_dict()["slicer_multipass"] == 4


def test_jobinfo_archived_flag(tmp_path: Path) -> None:
    active = load_job(make_job(tmp_path, name="active_job"))
    assert active.archived is False and active.to_dict()["archived"] is False
    # A job under _archive/ reads as archived.
    arch = load_job(make_job(tmp_path / "_archive", name="old_job"))
    assert arch.archived is True and arch.to_dict()["archived"] is True


def test_archive_job_moves_a_top_level_job_into_archive(tmp_path: Path) -> None:
    make_job(tmp_path, name="done_job")
    store = JobStore([tmp_path])
    assert [j.name for j in store.scan()]  # listed while active
    dest = store.archive_job("done_job")
    assert dest == tmp_path / "_archive" / "done_job"
    assert dest.is_dir() and not (tmp_path / "done_job").exists()
    # still listed, now flagged archived
    j = next(j for j in store.scan() if j.dir.name == "done_job")
    assert j.archived is True


def test_archive_job_rejects_bad_missing_and_already_archived(tmp_path: Path) -> None:
    store = JobStore([tmp_path])
    for bad in ("", "..", "a/b", "a\\b"):
        try:
            store.archive_job(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass
    try:
        store.archive_job("nope")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
    make_job(tmp_path, name="dup")
    store.archive_job("dup")
    make_job(tmp_path, name="dup")  # a new active job with the same name
    try:
        store.archive_job("dup")  # destination already exists in _archive
        raise AssertionError("expected ValueError for already-archived")
    except ValueError:
        pass
