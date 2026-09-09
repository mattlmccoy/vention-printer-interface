"""Real MachineMotion 2 transport: HTTP on :8000 and MQTT on :1883 (spec §2).

The ONLY module that opens sockets to the controller. HTTP mirrors HTTPSend
(MachineMotion.py:364-410: GET, or POST with Content-type application/json); MQTT mirrors the
SDK client (:813-819 connect with no auth, :2762-2771 subscriptions, :2802-2899 caches).

Honesty rules (review C1/C2/M1): the cache is fed ONLY by broker messages, never by our own
publishes; construction fails unless the broker sends CONNACK with reason 0; a publish that paho
cannot send raises; a broker disconnect clears the cache so nothing stale reads as healthy;
retained payloads on request/response topics are ignored.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx

from vention_printer_interface.device import register_transport
from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import routes as r

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 5.0  # the SDK uses 65 s (:355); we poll, so fail fast and let protection act
HEALTH_TIMEOUT_S = (
    12.0  # /health blocks ~5 s on our unit (io-expander-hub subscribe_failed, 2026-09-09)
)


class MachineMotionTransport(Transport):
    name = "machinemotion"

    def __init__(
        self,
        ip: str,
        *,
        http: httpx.Client | None = None,
        mqtt: Any = "auto",
        mqtt_connect_timeout_s: float = 5.0,
    ) -> None:
        self.ip = ip
        self._http = http or httpx.Client(
            base_url=f"http://{ip}:{r.HTTP_PORT}", timeout=HTTP_TIMEOUT_S
        )
        self._cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()
        self._cond = threading.Condition(self._cache_lock)
        self._connected = threading.Event()
        self._connect_reason: Any = None
        self._mqtt: Any = None
        if mqtt is None:
            return
        client = self._new_paho_client() if mqtt == "auto" else mqtt
        self._start_mqtt(client, mqtt_connect_timeout_s)

    @property
    def mqtt_connected(self) -> bool:
        return self._connected.is_set()

    def _new_paho_client(self) -> Any:
        import paho.mqtt.client as mqtt  # local import: keeps import-time deps light
        from paho.mqtt.enums import CallbackAPIVersion

        return mqtt.Client(CallbackAPIVersion.VERSION2)

    def _start_mqtt(self, client: Any, timeout_s: float) -> None:
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        try:
            client.connect(self.ip, r.MQTT_PORT, keepalive=30)
        except OSError as exc:
            raise TransportError(f"MQTT connect to {self.ip}:{r.MQTT_PORT} failed: {exc}") from exc
        client.loop_start()
        if not self._connected.wait(timeout_s):
            client.loop_stop()
            if self._connect_reason is not None:
                raise TransportError(
                    f"MQTT broker refused connection (reason {self._connect_reason})"
                )
            raise TransportError(
                f"MQTT broker at {self.ip}:{r.MQTT_PORT} sent no CONNACK within {timeout_s}s"
            )
        self._mqtt = client

    def _on_connect(
        self, client: Any, userdata: Any, flags: Any, reason_code: Any, *args: Any
    ) -> None:
        code = getattr(reason_code, "value", reason_code)
        if code not in (0, None):
            self._connect_reason = code
            log.error("MQTT CONNACK refused: reason %s", code)
            return
        for topic in r.SUBSCRIPTIONS:
            client.subscribe(topic)
        log.info("MQTT connected to %s; subscribed %d topics", self.ip, len(r.SUBSCRIPTIONS))
        self._connected.set()

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        if msg.topic in r.RESPONSE_TOPICS and getattr(msg, "retain", False):
            return  # a retained answer to an old request is not an answer to ours
        payload = msg.payload.decode("utf-8", errors="replace")
        with self._cond:
            self._cache[msg.topic] = payload
            self._cond.notify_all()

    def _on_disconnect(self, client: Any, userdata: Any, *args: Any) -> None:
        log.warning("MQTT disconnected from %s; clearing cached status", self.ip)
        self._connected.clear()
        with self._cond:
            self._cache.clear()
            self._cond.notify_all()

    # ---- HTTP -------------------------------------------------------------------------------
    def http_get(self, path: str, *, timeout_s: float | None = None) -> bytes:
        return self._request("GET", path, None, timeout_s)

    def http_post_json(self, path: str, body: dict[str, float]) -> bytes:
        return self._request("POST", path, body, None)

    def _request(
        self, method: str, path: str, body: dict[str, float] | None, timeout_s: float | None
    ) -> bytes:
        kwargs: dict[str, Any] = {}
        if timeout_s is not None:
            kwargs["timeout"] = timeout_s
        try:
            if body is None:
                resp = self._http.request(method, path, **kwargs)
            else:
                resp = self._http.request(
                    method,
                    path,
                    content=json.dumps(body),
                    headers={"Content-type": "application/json"},
                    **kwargs,
                )
        except httpx.HTTPError as exc:
            raise TransportError(f"Could not {method} {path}: {exc}") from exc
        if resp.status_code != 200:
            raise TransportError(
                f"request http://{self.ip}:{r.HTTP_PORT}{path} failed with status "
                f"{resp.status_code}: {resp.text[:120]}"
            )
        return resp.content

    # ---- MQTT -------------------------------------------------------------------------------
    def _require_mqtt(self) -> Any:
        if self._mqtt is None or not self._connected.is_set():
            raise TransportError("MQTT not connected")
        return self._mqtt

    def mqtt_publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        info = self._require_mqtt().publish(topic, payload, retain=retain)
        rc = getattr(info, "rc", 0)
        if rc != 0:
            raise TransportError(f"MQTT publish to {topic} failed (paho rc={rc})")

    def mqtt_latest(self, topic: str) -> str | None:
        with self._cache_lock:
            return self._cache.get(topic)

    def mqtt_request(
        self, request_topic: str, response_topic: str, payload: str, timeout_s: float
    ) -> str:
        client = self._require_mqtt()
        with self._cond:
            self._cache.pop(response_topic, None)
        info = client.publish(request_topic, payload)
        if getattr(info, "rc", 0) != 0:
            raise TransportError(f"MQTT publish to {request_topic} failed (rc={info.rc})")
        with self._cond:
            if not self._cond.wait_for(lambda: response_topic in self._cache, timeout=timeout_s):
                raise TransportError(f"no response on {response_topic} within {timeout_s}s")
            return self._cache[response_topic]

    def close(self) -> None:
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._mqtt = None
        self._http.close()


register_transport("machinemotion")(MachineMotionTransport)
