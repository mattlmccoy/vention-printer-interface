"""Transport abstraction (spec §1-2): the MachineMotion's two pipes, HTTP and MQTT.

The same PrinterDevice/Controller logic runs over the in-process simulator and the real
controller. ``mqtt_latest`` returns the cached last payload of a subscribed topic (the SDK keeps
the same caches: MachineMotion.py:2802-2899). ``mqtt_request`` publishes and waits for the next
message on a response topic (the SDK's threaded MQTTsubscribe.simple pattern, :2350-2389).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class TransportError(RuntimeError):
    """The controller could not be reached or replied with a non-200 status."""


class Transport(ABC):
    name: str = "transport"

    @abstractmethod
    def http_get(self, path: str, *, timeout_s: float | None = None) -> bytes: ...

    @abstractmethod
    def http_post_json(self, path: str, body: dict[str, float]) -> bytes: ...

    @abstractmethod
    def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None: ...

    @abstractmethod
    def mqtt_latest(self, topic: str) -> str | None: ...

    @abstractmethod
    def mqtt_request(
        self, request_topic: str, response_topic: str, payload: str, timeout_s: float
    ) -> str: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
