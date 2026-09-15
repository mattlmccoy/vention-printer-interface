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
    ap.add_argument(
        "--print-min-wait",
        type=float,
        default=0.25,
        help="fallback floor (s) per wait step during a run. A wait after a real move now ends as "
        "soon as the move finishes (move-started detection), so this only bites no-op moves and is "
        "the safety margin against a stale 'complete'. Raise it if fast moves collide on hardware.",
    )
    ap.add_argument(
        "--print-poll-interval",
        type=float,
        default=0.1,
        help="finer telemetry cadence (s) while a run records, for smoother motion profiles / "
        "build-piston accuracy. Each poll makes several HTTP calls, so go below 0.1 only after "
        "checking the controller keeps up. Default 0.1 (10 Hz); equal to --poll-interval = off.",
    )
    ap.add_argument("--experiments-root", type=Path, default=None)
    ap.add_argument(
        "--jobs-root",
        type=Path,
        action="append",
        default=None,
        help="folder to scan for Meteor RIP jobs (job_info.json); repeatable. "
        "E.g. the MetPrint hot folder (its _archive is scanned too).",
    )
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
        print_poll_interval_s=args.print_poll_interval,
        print_min_wait_s=args.print_min_wait,
        experiments_root=args.experiments_root,
        jobs_roots=args.jobs_root,
        site_origin=args.site_origin or None,
        heater_io=(dev, pin),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
