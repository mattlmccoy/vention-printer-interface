"""vpi-probe: read-only commissioning probe — the first tool to run against the real controller.

Performs NO motion and NO writes: GET /health, /smartDrives/position, /smartDrives/complete/*,
/smartDrives/maxSpeed|maxAcceleration/*, /smartDrives/configuration?drive=N, M119 endstops, and a
timed MQTT capture of the subscribed topics. Writes a JSON report whose samples replace the
SDK-derived fixtures (plan/notes.md "Data-contract status").
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from vention_printer_interface.device import create_transport
from vention_printer_interface.device.base import Transport, TransportError
from vention_printer_interface.protocol import parsers as p
from vention_printer_interface.protocol import routes as r

log = logging.getLogger(__name__)
AXES = (1, 2, 3, 4)


def _try(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except (TransportError, p.ProtocolError, ValueError) as exc:
        return {"error": str(exc)}


def _each_axis(fn: Callable[[int], Any]) -> dict[int, Any]:
    return {n: _try(functools.partial(fn, n)) for n in AXES}


def _capture_mqtt(t: Transport, seconds: float) -> dict[str, str | None]:
    end = time.monotonic() + seconds
    seen: dict[str, str | None] = {}
    while True:
        for topic in (r.TOPIC_ESTOP_STATUS, r.TOPIC_DRIVES_READY):
            seen[topic] = t.mqtt_latest(topic)
        for dev in range(1, 9):
            v = t.mqtt_latest(r.io_available_topic(dev))
            if v is not None:
                seen[r.io_available_topic(dev)] = v
        for n in AXES:
            for topic in (f"drive/{n}/motionComplete", f"drive/{n}/error"):
                v = t.mqtt_latest(topic)
                if v is not None:
                    seen[topic] = v
        if time.monotonic() >= end:
            return seen
        time.sleep(0.2)


def run_probe(
    *, backend: str, ip: str | None, samples: int, interval_s: float, mqtt_capture_s: float
) -> dict[str, Any]:
    kwargs: dict[str, Any] = (
        {"ip": ip or r.DEFAULT_IP_ETHERNET} if backend == "machinemotion" else {"realtime": True}
    )
    t = create_transport(backend, **kwargs)
    report: dict[str, Any] = {
        "backend": backend,
        "ip": kwargs.get("ip"),
        "writes_performed": [],
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        h = p.parse_health(
            t.http_get(r.HEALTH_PATH, timeout_s=12.0)
        )  # /health is slow on real units
        report["health"] = {
            "version": ".".join(map(str, h.version)),
            "async_supported": h.async_supported,
            "estop_triggered": h.estop_triggered,
            "raw": h.raw,
        }
        report["drive_configs"] = _each_axis(
            lambda n: p.parse_json(t.http_get(r.drive_config_path(n)))
        )
        report["max_speed"] = _each_axis(lambda n: p.parse_json(t.http_get(r.max_speed_path(n))))
        report["max_accel"] = _each_axis(lambda n: p.parse_json(t.http_get(r.max_accel_path(n))))
        report["endstops"] = _try(
            lambda: p.parse_endstops(t.http_get(r.gcode_path(r.GCODE_ENDSTOPS)).decode())
        )
        report["motion_status_raw"] = _try(
            lambda: t.http_get(r.gcode_path(r.GCODE_MOTION_STATUS)).decode()
        )
        report["samples"] = []
        for _ in range(samples):
            pos_raw = t.http_get(r.POSITION_PATH)
            parsed = _try(functools.partial(p.parse_positions, pos_raw))
            positions = {} if "error" in parsed else {str(k): v for k, v in parsed.items()}
            report["samples"].append(
                {
                    "host_timestamp_ns": time.time_ns(),
                    "positions_raw": pos_raw.decode(errors="replace"),
                    "positions": positions,
                    "complete_raw": _each_axis(lambda n: t.http_get(r.complete_path(n)).decode()),
                }
            )
            time.sleep(interval_s)
        report["mqtt"] = _capture_mqtt(t, mqtt_capture_s)
    finally:
        t.close()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-probe", description=__doc__)
    ap.add_argument("--ip", default=None, help="controller IP (default 192.168.0.2)")
    ap.add_argument("--simulated", action="store_true", help="probe the built-in simulator")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--mqtt-seconds", type=float, default=10.0)
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    backend = "simulated" if args.simulated else "machinemotion"
    try:
        report = run_probe(
            backend=backend,
            ip=args.ip,
            samples=args.samples,
            interval_s=args.interval,
            mqtt_capture_s=args.mqtt_seconds,
        )
    except TransportError as exc:
        print(f"PROBE FAILED: {exc}")
        print(
            "Check: is this Mac on 192.168.0.x (Ethernet) or 192.168.7.x (USB)? "
            "ping the controller first."
        )
        return 2
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
        print(f"wrote {args.output}")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
