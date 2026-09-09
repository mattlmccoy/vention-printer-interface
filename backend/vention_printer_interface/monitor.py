"""vpi-monitor: live console telemetry through the real Controller (protection active).

Never arms, never moves, never touches the heater.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from vention_printer_interface.control.controller import Controller
from vention_printer_interface.device import create_transport
from vention_printer_interface.device.printer import PrinterDevice
from vention_printer_interface.protocol import routes as r


def format_line(snapshot: dict[str, Any]) -> str:
    t = snapshot.get("telemetry") or {}
    pos = " ".join(f"{k}={v:7.2f}" for k, v in t.get("positions", {}).items())
    flags = ""
    if t.get("estop_triggered"):
        flags += "ESTOP "
    if t and not t.get("drives_ready", True):
        flags += "NOT-READY "
    if t.get("heater_on"):
        flags += "HEATER "
    line = f"[{snapshot['state']}] {pos} {flags}".rstrip()
    if snapshot.get("fault_reasons"):
        line += " FAULT: " + "; ".join(snapshot["fault_reasons"])
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-monitor", description=__doc__)
    ap.add_argument("--ip", default=None)
    ap.add_argument("--simulated", action="store_true")
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args(argv)
    backend = "simulated" if args.simulated else "machinemotion"
    kwargs: dict[str, Any] = (
        {"ip": args.ip or r.DEFAULT_IP_ETHERNET} if backend == "machinemotion" else {}
    )
    c = Controller(poll_interval_s=0.2)
    c.attach_device(PrinterDevice(create_transport(backend, **kwargs)), backend=backend)
    try:
        while True:
            print(format_line(c.snapshot()))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        c.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
