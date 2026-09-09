"""In-memory event log (spec §6): the last N operator/machine events for the Print view.

Not a substitute for the run recorder (which is the durable record); sinks let the recorder and
the API both receive every event from one place.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)
Sink = Callable[[str, dict[str, Any]], None]


class EventLog:
    def __init__(self, capacity: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._sinks: list[Sink] = []
        self._lock = threading.Lock()

    def add_sink(self, sink: Sink) -> None:
        self._sinks.append(sink)

    def append(self, label: str, data: dict[str, Any] | None = None) -> None:
        payload = dict(data or {})
        with self._lock:
            self._events.append(
                {"host_timestamp_ns": time.time_ns(), "label": label, "data": payload}
            )
        for sink in list(self._sinks):
            try:
                sink(label, payload)
            except Exception as exc:  # noqa: BLE001 - a sink must never break the caller
                log.warning("event sink failed: %s", exc)

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        return items[-n:]
