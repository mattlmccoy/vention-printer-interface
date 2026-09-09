import json

import httpx
import pytest

from vention_printer_interface.device import create_transport
from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.machinemotion import MachineMotionTransport
from vention_printer_interface.protocol import routes as r


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == r.HEALTH_PATH:
        return httpx.Response(200, json={"estop_triggered": False})
    if request.url.path == r.MOVE_ABSOLUTE_PATH:
        assert json.loads(request.content) == {"1": 10.0}
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, text="{}")
    return httpx.Response(500, text="boom")


class _Msg:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic, self.payload = topic, payload


def make() -> MachineMotionTransport:
    http = httpx.Client(base_url="http://192.0.2.1:8000", transport=httpx.MockTransport(handler))
    return MachineMotionTransport("192.0.2.1", http=http, mqtt=None)


def test_registered_under_machinemotion() -> None:
    http = httpx.Client(base_url="http://192.0.2.1:8000", transport=httpx.MockTransport(handler))
    t = create_transport("machinemotion", ip="192.0.2.1", http=http, mqtt=None)
    assert isinstance(t, MachineMotionTransport)


def test_http_get_returns_bytes() -> None:
    assert json.loads(make().http_get(r.HEALTH_PATH))["estop_triggered"] is False


def test_http_post_json_sends_json() -> None:
    assert make().http_post_json(*r.move_absolute({1: 10})) == b"{}"


def test_non_200_raises_transport_error_with_path() -> None:
    with pytest.raises(TransportError, match="/smartDrives/position"):
        make().http_get(r.POSITION_PATH)


def test_connection_error_raises_transport_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http = httpx.Client(base_url="http://192.0.2.1:8000", transport=httpx.MockTransport(boom))
    with pytest.raises(TransportError, match="refused"):
        MachineMotionTransport("192.0.2.1", http=http, mqtt=None).http_get(r.HEALTH_PATH)


def test_mqtt_cache_updates_from_messages() -> None:
    t = make()
    t._on_message(None, None, _Msg(r.TOPIC_ESTOP_STATUS, b"true"))
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"


def test_mqtt_publish_without_client_raises() -> None:
    with pytest.raises(TransportError):
        make().mqtt_publish("x", "1")


@pytest.mark.hardware
def test_real_controller_health() -> None:
    t = MachineMotionTransport(r.DEFAULT_IP_ETHERNET)
    try:
        assert b"mqtt_services_running" in t.http_get(r.HEALTH_PATH)
    finally:
        t.close()
