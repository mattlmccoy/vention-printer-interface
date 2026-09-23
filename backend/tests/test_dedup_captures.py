"""One-time dedup of already-stored runs: a `<stage>.webp` byte-identical to its `<stage>.raw.webp`
is a pure duplicate (uncalibrated capture) — remove it and repoint the sidecar at the raw file."""

import hashlib
import json
from pathlib import Path

from vention_printer_interface.vision.dedup import dedup_run, dedup_runs_under


def _capture(d: Path, stage: str, raw: bytes, registered: bytes) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.raw.webp").write_bytes(raw)
    (d / f"{stage}.webp").write_bytes(registered)
    (d / f"{stage}.json").write_text(json.dumps({
        "stage": stage,
        "images": {"raw": f"{stage}.raw.webp", "registered": f"{stage}.webp"},
        "checksum_sha256": hashlib.sha256(registered).hexdigest(),
    }))
    # The run manifest (what the compare UI actually reads) records the registered relative path.
    run = d.parent.parent  # <run>/vision/layer_NNNN -> <run>
    manifest = run / "vision" / "manifest.json"
    recs = json.loads(manifest.read_text()) if manifest.exists() else []
    rel = d.relative_to(run).as_posix()
    recs.append({"stage": stage, "layer": 1, "registered": f"{rel}/{stage}.webp"})
    manifest.write_text(json.dumps(recs))


def test_dedup_removes_identical_registered_and_repoints_sidecar(tmp_path: Path) -> None:
    run = tmp_path / "20260101_000000_a"
    layer = run / "vision" / "layer_0001"
    _capture(layer, "post_jet", raw=b"RIFF-same-bytes", registered=b"RIFF-same-bytes")  # identical
    res = dedup_run(run)
    assert res.files_removed == 1
    assert res.bytes_reclaimed == len(b"RIFF-same-bytes")
    assert not (layer / "post_jet.webp").exists()          # duplicate removed
    assert (layer / "post_jet.raw.webp").exists()          # raw kept
    side = json.loads((layer / "post_jet.json").read_text())
    assert side["images"]["registered"] == "post_jet.raw.webp"   # repointed at raw
    assert side["checksum_sha256"] == hashlib.sha256(b"RIFF-same-bytes").hexdigest()
    # the manifest record the compare UI reads must also point at the surviving raw file
    manifest = json.loads((run / "vision" / "manifest.json").read_text())
    assert manifest[0]["registered"] == "vision/layer_0001/post_jet.raw.webp"


def test_dedup_leaves_a_genuinely_different_registered(tmp_path: Path) -> None:
    run = tmp_path / "run"
    layer = run / "vision" / "layer_0001"
    _capture(layer, "post_jet", raw=b"RAW-pixels", registered=b"WARPED-different")  # differs
    res = dedup_run(run)
    assert res.files_removed == 0
    assert (layer / "post_jet.webp").exists()              # a real registered image is preserved
    side = json.loads((layer / "post_jet.json").read_text())
    assert side["images"]["registered"] == "post_jet.webp"


def test_dedup_runs_under_aggregates(tmp_path: Path) -> None:
    for name in ("20260101_000000_a", "20260102_000000_b"):
        _capture(tmp_path / name / "vision" / "layer_0001", "post_jet",
                 raw=b"dup", registered=b"dup")
    total = dedup_runs_under(tmp_path)
    assert total.files_removed == 2
    assert total.bytes_reclaimed == 2 * len(b"dup")
