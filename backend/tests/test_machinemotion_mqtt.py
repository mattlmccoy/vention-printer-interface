"""MQTT behaviour of the real transport against a fake paho client (review C1, C2, M1)."""

from typing import Any

import httpx
import pytest

from vention_printer_interface.device.base import TransportError
from vention_printer_interface.device.machinemotion import MachineMotionTransport
from vention_printer_interface.protocol import routes as r


class _Info:
    def __init__(self, rc: int) -> None:
        self.rc = rc


class FakeMqtt:
    """Enough of paho.mqtt.client.Client to drive MachineMotionTransport."""

    def __init__(self, *, connack: bool = True, reason_code: int = 0, publish_rc: int = 0) -> None:
        self.connack, self.reason_code, self.publish_rc = connack, reason_code, publish_rc
        self.subscribed: list[str] = []
        self.published: list[tuple[str, str, bool]] = []
        self.on_connect: Any = None
        self.on_message: Any = None
        self.on_disconnect: Any = None
        self.looping = False

    def connect(self, host: str, port: int, keepalive: int = 60) -> int:
        return 0

    def loop_start(self) -> None:
        self.looping = True
        if self.connack:
            self.on_connect(self, None, {}, self.reason_code)

    def loop_stop(self) -> None:
        self.looping = False

    def disconnect(self) -> None:
        pass

    def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)

    def publish(self, topic: str, payload: str, retain: bool = False) -> _Info:
        self.published.append((topic, payload, retain))
        return _Info(self.publish_rc)


class _Msg:
    def __init__(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self.topic, self.payload, self.retain = topic, payload, retain


def http() -> httpx.Client:
    return httpx.Client(
        base_url="http://192.0.2.1:8000",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="{}")),
    )


def make(fake: FakeMqtt) -> MachineMotionTransport:
    return MachineMotionTransport("192.0.2.1", http=http(), mqtt=fake, mqtt_connect_timeout_s=0.2)


def test_connect_subscribes_all_topics_including_outputs() -> None:
    fake = FakeMqtt()
    make(fake)
    assert "devices/+/+/digital-output/#" in fake.subscribed
    assert r.TOPIC_ESTOP_TRIGGER_RESPONSE in fake.subscribed


def test_no_connack_raises() -> None:
    with pytest.raises(TransportError, match="CONNACK"):
        make(FakeMqtt(connack=False))


def test_bad_reason_code_raises() -> None:
    with pytest.raises(TransportError, match="reason"):
        make(FakeMqtt(reason_code=5))


def test_publish_does_not_feed_cache() -> None:
    t = make(FakeMqtt())
    t.mqtt_publish(r.io_output_topic(1, 0), "1", retain=True)
    assert t.mqtt_latest(r.io_output_topic(1, 0)) is None  # only the broker echo does


def test_publish_error_rc_raises() -> None:
    t = make(FakeMqtt(publish_rc=4))  # MQTT_ERR_NO_CONN
    with pytest.raises(TransportError, match="publish"):
        t.mqtt_publish("x", "1")


def test_disconnect_clears_cache() -> None:
    fake = FakeMqtt()
    t = make(fake)
    t._on_message(fake, None, _Msg(r.TOPIC_ESTOP_STATUS, b"false"))
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "false"
    fake.on_disconnect(fake, None, None, 1)
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) is None
    assert t.mqtt_connected is False


def test_retained_response_is_ignored_but_status_is_kept() -> None:
    fake = FakeMqtt()
    t = make(fake)
    t._on_message(fake, None, _Msg(r.TOPIC_ESTOP_TRIGGER_RESPONSE, b"true", retain=True))
    assert t.mqtt_latest(r.TOPIC_ESTOP_TRIGGER_RESPONSE) is None
    t._on_message(fake, None, _Msg(r.TOPIC_ESTOP_STATUS, b"true", retain=True))
    assert t.mqtt_latest(r.TOPIC_ESTOP_STATUS) == "true"


def test_mqtt_request_times_out_without_fresh_response() -> None:
    t = make(FakeMqtt())
    with pytest.raises(TransportError, match="no response"):
        t.mqtt_request(r.TOPIC_ESTOP_TRIGGER_REQUEST, r.TOPIC_ESTOP_TRIGGER_RESPONSE, "x", 0.1)


def test_http_get_timeout_override() -> None:
    seen: list[float | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.extensions.get("timeout", {}).get("read"))
        return httpx.Response(200, text="{}")

    client = httpx.Client(base_url="http://192.0.2.1:8000", transport=httpx.MockTransport(handler))
    t = MachineMotionTransport("192.0.2.1", http=client, mqtt=None)
    t.http_get("/health", timeout_s=42.0)
    assert seen[-1] == 42.0
