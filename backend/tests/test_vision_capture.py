from vention_printer_interface.vision.events import CAPTURE_LABELS, CaptureRequest, label_to_stage


def test_capture_labels_are_the_three_stage_marks():
    assert CAPTURE_LABELS == ("capture:pre_jet", "capture:post_jet", "capture:post_heat")


def test_label_to_stage_extracts_stage_for_capture_labels():
    assert label_to_stage("capture:post_jet") == "post_jet"
    assert label_to_stage("capture:pre_jet") == "pre_jet"
    assert label_to_stage("capture:post_heat") == "post_heat"


def test_label_to_stage_returns_none_for_non_capture_labels():
    assert label_to_stage("layer_started") is None
    assert label_to_stage("capture:unknown") is None


def test_capture_request_fields():
    req = CaptureRequest(
        layer=3,
        stage="post_jet",
        host_timestamp_ns=123,
        axis_positions_mm={"build": 0.0},
        job={"id": "j1"},
    )
    assert req.layer == 3
    assert req.stage == "post_jet"
    assert req.host_timestamp_ns == 123
    assert req.axis_positions_mm == {"build": 0.0}
    assert req.job == {"id": "j1"}
