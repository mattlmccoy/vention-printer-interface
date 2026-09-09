import json

import pytest

from vention_printer_interface.device import create_transport
from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.simulated import SimulatedTransport
from vention_printer_interface.protocol import routes as r


def make() -> SimulatedTransport:
    return SimulatedTransport(realtime=False)


def home(t: SimulatedTransport) -> None:
    t.http_get(r.gcode_path(r.GCODE_HOME_ALL))
    t.advance(60)


def pos(t: SimulatedTransport) -> dict[str, float]:
    return json.loads(t.http_get(r.POSITION_PATH))  # type: ignore[no-any-return]


def test_registered_under_simulated() -> None:
    assert isinstance(create_transport("simulated", realtime=False), SimulatedTransport)


def test_health_reports_version_and_estop() -> None:
    t = make()
    h = json.loads(t.http_get(r.HEALTH_PATH))
    assert h["mqtt_services_running"]["services/mm-vention-control/version"] == "2.14.1"
    assert h["estop_triggered"] is False


def test_positions_have_all_axes_and_home_to_zero() -> None:
    t = make()
    assert set(pos(t)) == {"X", "Y", "Z", "W"}
    home(t)
    assert pos(t) == {"X": 0, "Y": 0, "Z": 0, "W": 0}


def test_move_absolute_integrates_at_max_speed() -> None:
    t = make()
    home(t)
    t.http_post_json(r.max_speed_path(3), r.max_speed_body(100))
    t.http_post_json(*r.move_absolute({3: 200}))
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is False
    t.advance(1.0)
    assert pos(t)["Z"] == pytest.approx(100)
    t.advance(1.5)
    assert pos(t)["Z"] == pytest.approx(200)
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is True
    assert "COMPLETED" in t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode()


def test_move_relative_and_clamp_to_travel() -> None:
    t = make()
    home(t)
    t.http_post_json(r.max_speed_path(2), r.max_speed_body(1000))
    t.http_post_json(*r.move_relative({2: 500}))  # feed travel is 145 mm
    t.advance(5)
    assert pos(t)["Y"] == pytest.approx(145)


def test_stop_all_halts_motion() -> None:
    t = make()
    home(t)
    t.http_post_json(r.max_speed_path(4), r.max_speed_body(100))
    t.http_post_json(*r.move_absolute({4: 500}))
    t.advance(1)
    t.http_get(r.gcode_path(r.GCODE_STOP_ALL))
    t.advance(5)
    assert pos(t)["W"] == pytest.approx(100)


def test_estop_round_trip_over_mqtt() -> None:
    t = make()
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "false"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "true"
    reply = t.mqtt_request(r.TOPIC_ESTOP_TRIGGER_REQUEST, r.TOPIC_ESTOP_TRIGGER_RESPONSE, "test", 1)
    assert reply == "true"
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "false"
    with pytest.raises(TransportError):
        t.http_post_json(*r.move_absolute({1: 10}))  # refused while e-stopped
    assert t.mqtt_request(r.TOPIC_ESTOP_RELEASE_REQUEST, r.TOPIC_ESTOP_RELEASE_RESPONSE, "", 1)
    assert t.mqtt_request(r.TOPIC_ESTOP_RESET_REQUEST, r.TOPIC_ESTOP_RESET_RESPONSE, "", 1)
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "false"
    t.advance(3.1)
    assert t.mqtt_latest(r.TOPIC_DRIVES_READY) == "true"


def test_io_output_is_retained_and_readable() -> None:
    t = make()
    t.mqtt_publish(r.io_output_topic(1, 2), "1", retain=True)
    assert t.mqtt_latest(r.io_output_topic(1, 2)) == "1"
    assert t.mqtt_latest(r.io_available_topic(1)) == "true"


def test_unreachable_knob() -> None:
    t = SimulatedTransport(realtime=False, unreachable=True)
    with pytest.raises(TransportError):
        t.http_get(r.HEALTH_PATH)


def test_slow_completion_knob_reproduces_v1_quirk() -> None:
    t = SimulatedTransport(realtime=False, slow_completion_s=1.0)
    home(t)
    t.http_post_json(r.max_speed_path(3), r.max_speed_body(100))
    t.http_post_json(*r.move_absolute({3: 10}))
    t.advance(0.2)
    assert pos(t)["Z"] == pytest.approx(10)
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is False
    t.advance(1.0)
    assert json.loads(t.http_get(r.complete_path(3)))["complete"] is True


def test_endstops_reflect_home() -> None:
    t = make()
    home(t)
    reply = t.http_get(r.gcode_path(r.GCODE_ENDSTOPS)).decode()
    assert "x_min: TRIGGERED" in reply
    assert "x_max: open" in reply


def test_unknown_route_is_404() -> None:
    with pytest.raises(TransportError, match="404"):
        make().http_get("/nope")
