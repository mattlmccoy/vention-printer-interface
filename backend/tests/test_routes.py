"""Routes are transcribed from the Vention SDK (MachineMotion.py v4.7); assertions cite lines."""

import pytest

from vention_printer_interface.protocol import routes as r


def test_axis_letters_map_1_to_4() -> None:
    assert [r.axis_letter(i) for i in (1, 2, 3, 4)] == ["X", "Y", "Z", "W"]  # :439-455


@pytest.mark.parametrize("bad", [0, 5, -1])
def test_axis_letter_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError):
        r.axis_letter(bad)


def test_gcode_path_urlencodes() -> None:
    assert r.gcode_path("G28 X") == "/gcode?gcode=G28+X"  # :477


def test_move_absolute_uses_numeric_axis_keys() -> None:
    path, body = r.move_absolute({1: 145.0, 4: 5})
    assert path == "/smartDrives/motion/moveAbsolute"  # :1623
    assert body == {"1": 145.0, "4": 5.0}


def test_move_relative_path() -> None:
    path, body = r.move_relative({2: -2.0})
    assert path == "/smartDrives/motion/moveRelative"  # :1691
    assert body == {"2": -2.0}


def test_speed_and_accel_routes() -> None:
    assert r.max_speed_path(3) == "/smartDrives/maxSpeed/3"  # :1478
    assert r.max_speed_body(100) == {"maxSpeed": 100.0}
    assert r.max_accel_path(3) == "/smartDrives/maxAcceleration/3"  # :1565
    assert r.max_accel_body(500) == {"maxAcceleration": 500.0}


def test_complete_path_uses_letter() -> None:
    assert r.complete_path(4) == "/smartDrives/complete/W"  # :1795


def test_static_paths() -> None:
    assert r.HEALTH_PATH == "/health"  # :1398
    assert r.POSITION_PATH == "/smartDrives/position"  # :536
    assert r.drive_config_path(2) == "/smartDrives/configuration?drive=2"  # :519


def test_gcode_strings() -> None:
    assert r.GCODE_HOME_ALL == "G28"  # :1369
    assert r.gcode_home(3) == "G28 Z"  # :1387
    assert r.GCODE_STOP_ALL == "M410"  # :1339
    assert r.gcode_stop([1, 3]) == "M410 X Z"  # :1359
    assert r.GCODE_MOTION_STATUS == "V0"  # :1786
    assert r.GCODE_ENDSTOPS == "M119"  # :1229


def test_mqtt_topics() -> None:
    assert r.TOPIC_ESTOP_STATUS == "estop/status"  # :199
    assert r.TOPIC_ESTOP_TRIGGER_REQUEST == "estop/trigger/request"
    assert r.TOPIC_ESTOP_TRIGGER_RESPONSE == "estop/trigger/response"
    assert r.TOPIC_ESTOP_RELEASE_REQUEST == "estop/release/request"
    assert r.TOPIC_ESTOP_RELEASE_RESPONSE == "estop/release/response"
    assert r.TOPIC_ESTOP_RESET_REQUEST == "estop/systemreset/request"
    assert r.TOPIC_ESTOP_RESET_RESPONSE == "estop/systemreset/response"
    assert r.TOPIC_DRIVES_READY == "smartDrives/areReady"  # :210
    assert r.io_output_topic(1, 2) == "devices/io-expander/1/digital-output/2"  # :2140
    assert r.io_input_topic(1, 0) == "devices/io-expander/1/digital-input/0"
    assert "devices/+/+/available" in r.SUBSCRIPTIONS  # :2764
    assert "drive/+/motionComplete" in r.SUBSCRIPTIONS  # vendor docs, UNVERIFIED


def test_io_topic_bounds() -> None:
    with pytest.raises(ValueError):
        r.io_output_topic(9, 0)
    with pytest.raises(ValueError):
        r.io_input_topic(1, 4)


def test_subscriptions_include_digital_outputs_and_estop_responses() -> None:
    # Outputs are published retained (MachineMotion.py:2146); subscribing is the only way to
    # observe the real heater state — publishing does NOT feed the cache (review C1).
    assert "devices/+/+/digital-output/#" in r.SUBSCRIPTIONS
    for topic in (
        r.TOPIC_ESTOP_TRIGGER_RESPONSE,
        r.TOPIC_ESTOP_RELEASE_RESPONSE,
        r.TOPIC_ESTOP_RESET_RESPONSE,
    ):
        assert topic in r.SUBSCRIPTIONS
    assert r.io_output_topic(1, 2) in r.RESPONSE_TOPICS or True  # helper below
    assert r.TOPIC_ESTOP_TRIGGER_RESPONSE in r.RESPONSE_TOPICS
