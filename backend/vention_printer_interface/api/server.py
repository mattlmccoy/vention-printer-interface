"""vpi-serve: run the operator (API + built UI) on 127.0.0.1:8020 (8000 = FLIR, 8010 = T&C)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from vention_printer_interface.api.app import create_app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vpi-serve", description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument(
        "--backend",
        choices=["none", "simulated", "machinemotion"],
        default="none",
        help="none = boot idle and connect via the UI (default)",
    )
    ap.add_argument("--ip", default=None, help="controller IP (implies --backend machinemotion)")
    ap.add_argument(
        "--heater-io",
        default="1,0",
        help="IO module id,pin for the heater relay (UNVERIFIED default; confirm in commissioning)",
    )
    ap.add_argument("--poll-interval", type=float, default=0.2)
    ap.add_argument("--experiments-root", type=Path, default=None)
    ap.add_argument(
        "--site-origin",
        default="https://mattlmccoy.github.io",
        help="origin allowed to control this operator cross-origin; '' disables",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    backend = "machinemotion" if args.ip else args.backend
    dev, pin = (int(x) for x in args.heater_io.split(","))
    app = create_app(
        backend=backend,
        ip=args.ip,
        poll_interval_s=args.poll_interval,
        experiments_root=args.experiments_root,
        site_origin=args.site_origin or None,
        heater_io=(dev, pin),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
