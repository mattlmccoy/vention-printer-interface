# Development

* Red-green TDD for all testable logic (`backend/tests`). Write the failing test first.
* `uv run pytest` — unit tests (no hardware). `uv run pytest --hardware` — also run tests marked
  `hardware` (need a reachable controller; they are read-only).
* `uv run ruff format . && uv run ruff check .` — format/lint. `uv run mypy vention_printer_interface` — types (strict).
* Only `device/machinemotion.py` opens sockets to the controller. Everything else consumes
  `Transport` / `PrinterDevice`.
* Every protocol constant cites its `MachineMotion.py` line; anything from vendor docs is marked
  UNVERIFIED until the probe confirms it.
* Conventional Commits; small, reviewable diffs; never commit probe outputs with serials,
  experiment data, or the SDK copy (see `.gitignore`).
* Ports: operator 8020, Vite dev 5175 (FLIR 8000/5173, T&C 8010/5174). Header `X-VPI-Client`.
