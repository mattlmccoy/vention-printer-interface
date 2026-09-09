import pytest

from vention_printer_interface.device import create_transport, register_transport
from vention_printer_interface.device.base import Transport


def test_unknown_transport_lists_known_names() -> None:
    with pytest.raises(KeyError) as exc:
        create_transport("nope")
    assert "simulated" in str(exc.value)


def test_register_and_create_custom() -> None:
    class Fake(Transport):
        name = "fake"

        def http_get(self, path: str) -> bytes:
            return b""

        def http_post_json(self, path: str, body: dict[str, float]) -> bytes:
            return b""

        def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
            pass

        def mqtt_latest(self, topic: str) -> str | None:
            return None

        def mqtt_request(
            self, request_topic: str, response_topic: str, payload: str, timeout_s: float
        ) -> str:
            return "true"

        def close(self) -> None:
            pass

    register_transport("fake-test")(Fake)
    assert isinstance(create_transport("fake-test"), Fake)
