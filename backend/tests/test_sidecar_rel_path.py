"""The sidecar JSON sits beside a capture as `<stage>.json`, whichever image `registered` names —
including the raw file when an uncalibrated (deduped) capture points `registered` at
`<stage>.raw.webp`."""

from vention_printer_interface.api.app import _sidecar_rel_path


def test_sidecar_for_registered_webp() -> None:
    assert _sidecar_rel_path("vision/layer_0001/post_jet.webp") == "vision/layer_0001/post_jet.json"


def test_sidecar_for_deduped_raw_webp_is_the_stage_json_not_raw_json() -> None:
    # A deduped capture's `registered` is the raw file; its sidecar is still `<stage>.json`.
    got = _sidecar_rel_path("vision/layer_0001/post_jet.raw.webp")
    assert got == "vision/layer_0001/post_jet.json"


def test_sidecar_for_legacy_png() -> None:
    assert _sidecar_rel_path("vision/layer_0002/pre_jet.png") == "vision/layer_0002/pre_jet.json"
