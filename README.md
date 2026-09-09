# Vention Printer Interface

Operator backend + (planned) browser UI for the **Vention MachineMotion 2** four-drive controller
that runs the binder-jet printer (part piston, feed piston, printhead gantry, recoater gantry with
IR heater). Third sibling of the [FLIR Research Interface](../../../../FLIR) and the
[T&C Power Interface](../TC-POWER); it mirrors their architecture and conventions so the three
read as one family.

**Status (2026-09-09): backend, recipe engine and Studio UI working against a built-in simulator;
NOT yet run against the physical controller.** Protocol layer, simulator, real HTTP+MQTT
transport, supervisory controller (ARM gate, E-STOP, pure protection, heater watchdog), the V1.py
recipe as a pausable step machine, run recorder with per-layer log, FastAPI + `/ws/telemetry`,
three CLIs, sliced-job intake (Meteor RIP folders), and the **Binder Jet Console** UI (Print /
Job / Control / Runs, draggable self-sized modules) are implemented and tested (181 backend tests,
30 frontend tests). An independent review pass fixed several safety gaps (see `plan/task_plan.md`).
The console was browser-verified against the simulator with real sliced jobs from the lab hot
folder: select job → connect and take control → dry run → Print view shows the current layer's
cross-section with progress.

| Piece | Location | State |
|---|---|---|
| Routes, topics, G-code (cited to the Vention SDK) | `backend/vention_printer_interface/protocol/routes.py` | tested |
| Reply parsers | `backend/.../protocol/parsers.py` | tested with **SDK-derived** fixtures (not hardware captures) |
| Transport ABC + registry (`simulated` / `machinemotion`) | `backend/.../device/` | tested |
| Simulator (kinematics, homing, e-stop, IO, fault knobs) | `backend/.../device/simulated.py` | tested |
| Real transport (httpx + paho-mqtt) | `backend/.../device/machinemotion.py` | unit-tested with a mock; **UNVERIFIED on hardware** |
| `PrinterDevice` (one method per capability) | `backend/.../device/printer.py` | tested |
| Pure protection evaluator + tighten-only limits | `backend/.../control/safety.py` | tested |
| Supervisory `Controller` (poll, ARM, E-STOP, FAULT latch, listeners) | `backend/.../control/controller.py` | tested; simulator-verified live |
| Run recorder (`metadata.json` at start; `manifest.json` only on clean stop) | `backend/.../recording/recorder.py` | tested |
| FastAPI operator + `/ws/telemetry` + cross-origin policy | `backend/.../api/app.py` | tested; live-verified on :8020 |
| Recipe plan (V1.py constants) + pure compiler asserted against the script order | `backend/.../control/recipe.py` | tested |
| Recipe step machine (pause/resume/abort, dry-run, single-step, timeouts) | `backend/.../control/recipe_controller.py` | tested; simulator-verified |
| Recipe API + auto-logged runs with `layers.csv` | `backend/.../api/app.py` | tested |
| CLIs `vpi-serve`, `vpi-probe` (read-only), `vpi-monitor` | `backend/.../api/server.py`, `probe.py`, `monitor.py` | run against the simulator |
| Park macros on the step machine (`load_cart`, `clear_bed`), event log, measured part height, duration estimate | `backend/.../control/{macros,events}.py`, `recipe_controller.py`, `api/app.py` | tested |
| Sliced-job intake: Meteor RIP `job_info.json` folders + `_Page<N>_Clr1.tif` pages (real format captured), layer PNGs, job → recipe mapping | `backend/.../jobs/store.py`, `/api/jobs*` | tested with captured-shape fixtures; verified on real jobs |
| Binder Jet Console: Print (current layer cross-section + progress, print card, machine), Job (pick a sliced job, preview any layer, powder stack, start), Control (jog pads, park macros, heater), Runs; draggable self-sized modules; connect takes control (read-only optional); E-STOP always on screen | `frontend/` (Vite + React + TS; FLIR design language, printer layout) | logic tested (`node --test`, 30); browser-verified with real jobs |

## Scientific / engineering stance

Only the documented protocol. Every HTTP route, MQTT topic and G-code string is transcribed from
Vention's own SDK (`MachineMotion.py` v4.7, copy under `plan/reference/`) with a line citation, or
from Vention's public docs and marked UNVERIFIED. Reaching the controller does not prove the reply
shapes; **run `vpi-probe` (read-only) first** and reconcile `plan/probe_report.json` against the
SDK-derived fixtures before any powered operation. See `docs/protocol.md` and `plan/notes.md`.

**Safety.** A connected controller is read-only until ARMed. The heater relay is treated like RF in
the T&C tool: it turns on only by an explicit operator action while armed, and is forced off on
any fault, disconnect, E-STOP, disarm, or when its on-time watchdog expires. Stop, heater-off,
E-STOP and disarm are never gated. Hard bounds on speed, acceleration, travel and heater on-time are
tighten-only; the UI and config files can narrow them, never widen them.

## Quick start (no hardware)

```bash
cd backend
uv sync --extra dev
uv run pytest                                   # 164 tests
uv run vpi-probe --simulated --samples 3        # read-only probe of the simulator
uv run vpi-serve --backend simulated            # http://127.0.0.1:8020/api/status
# with your sliced jobs (the MetPrint hot folder; its _archive is scanned):
uv run vpi-serve --backend simulated --jobs-root "/path/to/Hot Folder"
```

Run the full app (UI + API) against the simulator:

```bash
cd frontend && npm install && npm run build     # builds frontend/dist, served by the operator
cd ../backend && uv run vpi-serve --backend simulated   # open http://127.0.0.1:8020
# UI hot-reload during development:
cd frontend && npm run dev                      # http://127.0.0.1:5175 (proxies /api + /ws to :8020)
```

## Talking to the real printer (read-only first)

See `docs/commissioning.md`. In short:

```bash
ping -c 3 192.168.0.2                             # ETHERNET port; USB port is 192.168.7.2
cd backend && uv run vpi-probe --ip 192.168.0.2 --output ../plan/probe_report.json
```

## Layout

```
backend/    Python package `vention_printer_interface` + tests (uv-managed)
  protocol/   routes, parsers (pure)
  device/     Transport ABC + registry, simulator, real transport, PrinterDevice
  control/    safety (pure), controller, limits persistence
  recording/  run recorder
  api/        FastAPI create_app + vpi-serve
docs/       architecture, protocol, recipe, commissioning, development
plan/       task plan, research notes, data-contract status, SDK reference copy (git-ignored)
frontend/   Vite + React + TS console (built into frontend/dist, served by vpi-serve); dev on 5175
  src/lib/     pure logic with node --test: console state, operator, api (routes locked), telemetry, recipe mirror, duration estimate, elevation geometry, format/gates
  src/components/views/   PrintView, PrepareView, ControlView, RunsView
  src/components/         Elevation (front-elevation drawing), HeaterRing, IoGrid, EventLog, StatusBar, ErrorBoundary
```

## License

MIT for this repository's own code. Vention's SDK and firmware are not redistributed; the SDK
copy under `plan/reference/` is git-ignored.
