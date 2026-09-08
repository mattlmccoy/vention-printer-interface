# Vention Printer Interface — design

**Status:** approved in conversation 2026-09-08 (sections 1–7); awaiting written-spec review.
**Family:** third sibling of the FLIR Research Interface (`FLIR/`) and the T&C Power Interface (`TC-POWER/`). Mirrors their architecture and conventions so the three read as one family.
**Hardware:** Vention MachineMotion 2 four-drive, firmware 2.14.x, controller IP 192.168.0.2 (ETHERNET port) / 192.168.7.2 (DEFAULT USB port). Four axes from `vention/json/configuration.json`: 1 Part Piston (belt, 150 mm/rot, brake), 2 Feed Piston (belt, 150 mm/rot, brake, rotation −1), 3 Printhead Gantry (enclosed ball screw, 16 mm/rot), 4 Recoater Gantry (enclosed ball screw, 16 mm/rot, carries the IR heater). One IR-heater relay on a Vention IO module (id/pin unknown until probe).

## Goal
Replace the Cloud9 scripts (`vention/python/V1.py`) with an operator program that drives the printer over the controller's own open transports, runs the precoat/print/postcoat recipe as a pausable step machine, records every run with the family integrity model, and is fully testable against a simulator.

## Non-goals (explicitly deferred to v2)
- MetPrint / hot-folder job sync (layer TIFF queued before each pass). Jetting is triggered Meteor-side by the print-axis quadrature encoder + layer-start sensor; v1 only moves the gantry.
- FLIR and TC-POWER links (`--flir-url`, `--tcp-url`) — the integration seam is reserved.
- Writing drive configuration (`/smartDrives/configuration`), motor current, homing speed. Read-only.
- LAN exposure of the operator (localhost-bound, as siblings).

## Principles (firm)
1. Only the documented protocol. The Vention SDK source (`MachineMotion.py` v4.7) and Vention's public docs are the reference; nothing is invented. Every route/topic constant cites its SDK line.
2. Everything is unverified until `vpi-probe` captures it from the physical controller. SDK-derived test fixtures are labelled as such and replaced by captured samples.
3. Three data concerns kept apart: raw controller protocol (`protocol/`, pure), device + control state (`device/`, `control/`), presentation (`api/`, `frontend/`). Presentation mutates control state only through guarded command methods.
4. The whole system runs and is tested without the printer (`--backend simulated`).
5. Red-green TDD for all testable logic; browser verification for UI.

## Safety model (firm)
- Heater is treated like RF in TC-POWER: it turns on only by an explicit operator action while ARMED; any FAULT, disconnect, E-STOP, disarm, recipe abort, or max-on-time watchdog commands it off. `heater_off` is never gated.
- ARM gate: a connected controller is read-only until ARMed. Guarded: home, move, set speed/accel, heater on, recipe start/resume, E-STOP release. Never gated (safe-direction): stop all motion, heater off, E-STOP, disarm, recipe pause/abort.
- E-STOP = `M410` + heater off + MQTT `estop/trigger/request` + disarm; bypasses every gate, safe in any state. Release requires explicit `POST /api/estop/release` (MQTT `estop/release/request` then `estop/systemreset/request`, wait for `smartDrives/areReady`).
- Protection is a pure function evaluated every poll; a trip stops motion, kills the heater, latches FAULT; `clear_fault` needs a clean latest sample.
- Hard bounds are tighten-only; the operator can never widen them from the UI or a config file.

## 1. Repository layout
```
vention-printer-interface/
  backend/vention_printer_interface/
    protocol/   routes.py (HTTP paths + MQTT topics, cited), gcode.py, parsers.py   — pure
    device/     base.py (Transport ABC), __init__.py (registry), simulated.py, machinemotion.py, printer.py (PrinterDevice)
    control/    safety.py, controller.py, recipe.py, recipe_compiler.py, heater.py, limits_store.py, recipe_store.py
    recording/  recorder.py
    integration/  (reserved: flir_link.py, tcp_link.py in v2)
    api/        app.py (create_app), server.py (vpi-serve)
    probe.py (vpi-probe), monitor.py (vpi-monitor)
  backend/tests/  flat test_<module>.py; conftest.py with --hardware gate
  frontend/   Vite + React 18 + TS; theme.css verbatim from FLIR (keyframes vpi-*); lib/ pure + node --test
  docs/       architecture.md, protocol.md, recipe.md, commissioning.md, development.md
  plan/       task_plan.md, notes.md (data-contract status), reference/ (git-ignored SDK copy)
  deploy/     install-operator-service.sh / uninstall (LaunchAgent, port 8020)
  .github/workflows/ ci.yml, pages.yml (VITE_BASE=/vention-printer-interface/)
```
Family slot: ports **8020** (operator) / **5175** (Vite); prefix `vpi-`; header `X-VPI-Client`; localStorage `vpi.*.v1`; site origin `https://mattlmccoy.github.io`.

Data flow:
```
MachineMotion 2 (HTTP :8000, MQTT :1883)
  → protocol/ (build requests, parse replies)
  → device/Transport {http_get, http_post_json, mqtt_publish, mqtt_subscribe/cache}  [simulated | machinemotion]
  → device/PrinterDevice {health, positions, motion_complete, home, move_abs, move_rel, set_max_speed, set_max_accel,
                          stop_all, estop_trigger/release/reset, estop_status, drives_ready, io_write, io_read}
  → control/Controller (poll thread, io lock, ARM, E-STOP, listeners, snapshot)
  → control/RecipeController, HeaterController (feature loops on the listener)
  → recording/Recorder
  → api/ FastAPI (/api/*, /ws/telemetry)  → frontend/ Studio UI
```

## 2. Protocol layer and simulator
`protocol/routes.py` — constants, each with `# MachineMotion.py:<line>`:
| Name | Value |
|---|---|
| HTTP_PORT | 8000 |
| HEALTH | GET `/health` |
| GCODE | GET `/gcode?gcode=<urlencoded>` (reply must contain "echo" and "ok") |
| POSITION | GET `/smartDrives/position` → `{"X","Y","Z","W"}` mm |
| MOVE_ABS / MOVE_REL | POST json `/smartDrives/motion/moveAbsolute` / `moveRelative`, body `{"<axis 1..4>": mm}` |
| MAX_SPEED(n) / MAX_ACCEL(n) | POST json `{"maxSpeed": mm_s}` / `{"maxAcceleration": mm_s2}` to `/smartDrives/maxSpeed/<n>` / `maxAcceleration/<n>`; GET returns current |
| COMPLETE(letter) | GET `/smartDrives/complete/<X|Y|Z|W>` → `{"complete": bool}` |
| ACTUAL_SPEED | GET `/smartDrives/get/actualSpeed` |
| DRIVE_CONFIG(n) | GET `/smartDrives/configuration?drive=<n>` (read-only use) |
| MQTT topics | `estop/status`, `estop/{trigger,release,systemreset}/{request,response}`, `smartDrives/areReady`, `devices/+/+/available`, `devices/io-expander/<id>/digital-input/<pin>`, `devices/io-expander/<id>/digital-output/<pin>` (retain), `drive/+/motionComplete`, `drive/+/error` (last two from Vention docs, UNVERIFIED) |
G-code used: `G28`, `G28 <letter>`, `M410`, `M410 <letters>`, `V0` ("COMPLETED" in reply), `M119` (endstops, probe only).
Axis map: API 1..4 ↔ letters X Y Z W; roles part/feed/printhead/recoater from configuration.json (friendlyName), loaded at connect.

`device/simulated.py` answers the same routes/topics from an in-process model: per-axis position, max speed/accel, trapezoidal motion integrated in real time (or stepped by `advance(dt)` in tests), home sensor at 0 and end sensor at the axis extent (145, 145, 840, 930 mm), G28 drives to 0 at the configured homing speed, E-STOP flag refuses motion and publishes `estop/status`, `smartDrives/areReady` false → true 3 s after systemreset, one virtual IO module (id 1) whose digital-output pin models the heater relay. Fault-injection kwargs: `unreachable=True`, `slow_completion_s=`, `stall_axis=`, `estop_on_boot=True`. Docstring: "a model of the MachineMotion, not a capture of the physical unit".

`device/machinemotion.py`: `httpx.Client(base_url=f"http://{ip}:8000", timeout=…)` + `paho.mqtt.Client` loop thread caching the subscribed topics under a lock; `mqtt_request(topic_req, topic_resp, payload, timeout)` for the estop round-trips. Only this module opens sockets to the controller.

## 3. Controller and safety
`Telemetry` (frozen): `host_timestamp_ns, positions{1..4}, motion_complete{1..4}, estop_triggered, drives_ready, health_ok, heater_on, heater_on_s, endstops?`.
`Controller`: states DISCONNECTED / CONNECTED / FAULT / CLOSED; `poll_interval_s=0.2`; `_lock` (state) + `_io_lock` (all device calls); every tick: read → `evaluate()` → notify listeners with `snapshot()`; read exception ⇒ FAULT; `attach_device/detach_device`; `arm/disarm`; `estop()` bypasses gates; guarded `home(axes)`, `move_abs(axis, mm)`, `move_rel(axis, mm)`, `set_max_speed`, `set_max_accel`, `heater_on()`; ungated `stop_all()`, `heater_off()`.
`safety.py`: `HARD_BOUNDS` (per-axis travel `[0, extent]`; max speed per axis: pistons ≤ 20 mm/s, gantries ≤ 300 mm/s; max accel: pistons ≤ 100, gantries ≤ 2000 mm/s²; heater max_on_s `[5, 600]`; telemetry timeout `[0.5, 5]` s). Defaults from V1.py/test.py, "conservative starting values, not validated limits". `SafetyLimits.bounded()`, `SafetyDecision(trip, reasons, warnings)`, pure `evaluate(t, limits, age_s)`: trips = stale telemetry, `estop_triggered`, `not drives_ready` while a move is pending, position outside `[min, max]` soft window, `heater_on_s > max_on_s`, health not ok; warnings = within 5 mm of a soft limit.
Persistence: `.limits.json`, `.recipe.json` under experiments_root; load re-clamps via `.bounded()`.

## 4. Recipe engine and run recording
`RecipePlan` (frozen; seeded from V1.py): phases `precoat, print, postcoat` each `{layer_thickness_mm, n_layers, part_speed, part_accel, feed_speed, feed_accel, printhead_speed, printhead_accel, recoater_speed, recoater_accel}`; general `{feed_end_mm=145, recoater_home=5, recoater_end=930, heater_home=5, heater_end=600, printhead_home=5, printhead_end=840, heater_speed=50, heater_accel=250, n_heater_passes=1, heater_enabled=False, settle_s=1.0}`; `.bounded(limits)`; `validate() -> list[str]` (printability: total thickness ≤ feed_end; positions inside travel; n_layers ≥ 0).
`compile_recipe(plan) -> list[Step]`, `Step = {index, phase, layer, kind: set_speed|set_accel|move_abs|move_rel|wait_complete|heater|dwell, axis?, value?}`; deterministic; order per layer = part +t, wait, recoater→end, wait, feed −t, wait, dwell settle, recoater→home, wait, [print only: printhead→end, wait, printhead→home, wait, heater speed, heater on?, N×(recoater→heater_end, wait, →heater_home, wait), heater off]. Setup prefix = home all, wait, feed fast to feed_end, wait.
`RecipeController`: IDLE / RUNNING / PAUSED / DONE / ABORTED / FAULT; `start(plan, dry_run=False, single_step=False)`, `pause()`, `resume()`, `abort()`, `step()`; `tick(dt)` on the controller listener; one step in flight; advance on `motion_complete` (poll) or `drive/<n>/motionComplete` edge if verified; per-step timeout (`travel/speed·2 + 10 s`) ⇒ FAULT; controller FAULT/disarm ⇒ ABORTED + heater off. Snapshot: `{state, step_index, n_steps, phase, layer, n_layers, part_height_mm, elapsed_s, eta_s, dry_run, current_step}`. Events: `recipe_started/paused/resumed/aborted/done`, `layer_started/completed{phase, layer, part_height_mm}`, `heater_on/off`.
Recorder: `experiments/<YYYYMMDD_HHMMSS>_<slug>/` with `metadata.json` (plan, axis config, limits, software, backend) at start; `telemetry.csv` streamed per poll; `layers.csv`; `events.json` + `manifest.json` (sha256s, `complete: true`) on clean stop. Recipe start auto-opens a run (`auto_log` toggle).

## 5. API and telemetry
`create_app(*, backend="none", poll_interval_s=0.2, experiments_root=None, limits=None, transport_kwargs=None, frontend_dist=None, site_origin=None)`. `GET /api/status` ≡ `/ws/telemetry` (JSON push every 100 ms): `{device, controller{state, armed, fault_reasons, telemetry, warnings, limits}, heater, recipe, recording, auto_log}`.
Routes: `GET /api/health`; `GET /api/discovery` (TCP-connect probe of 192.168.0.2:8000 and 192.168.7.2:8000 with 0.5 s timeout + `simulated`); `POST /api/connect {backend, ip?}`; `POST /api/disconnect`; `POST /api/arm|disarm|estop|estop/release`; `POST /api/motion/home {axes}`; `POST /api/motion/move {axis, mode: abs|rel, mm}`; `POST /api/motion/stop {axes?}`; `GET/PUT /api/axes/{n}/motion {max_speed, max_accel}` (+bounds); `GET/PUT /api/safety-limits` (+bounds); `POST /api/heater/on|off`; `GET/PUT /api/recipe` (+bounds, +validation); `POST /api/recipe/start {dry_run, single_step}|pause|resume|abort|step`; `POST /api/recording/start|stop`, `GET /api/recording/status`, `GET /api/recordings`, `GET /api/recordings/{run}/telemetry.csv|layers.csv` (path-traversal guard); `GET/PUT /api/auto-log`. Refusals 409 with reason. `install_cross_origin_policy` + `X-VPI-Client` copied from siblings; `Cache-Control: no-store` on HTML.

## 6. Studio UI
Copied from FLIR: `theme.css` (verbatim, keyframes `vpi-*`, add `--err-btn`, traces `--trace-part/--trace-feed/--trace-ph/--trace-rc` = axisColor green/yellow/red/blue from configuration.json mapped to family hues), `styles.css` Studio grid, `components/studio/*`, `lib/layout.ts` (`vpi.layout.v1`), `lib/operator.ts` (`vpi.operator.v1`, default `http://localhost:8020`), `lib/api.ts` (method+URL locked by tests).
Pages: live, experiments. Strip tools: jog, home, recipe, measure. Center `MachineView.tsx` (SVG, to scale: two pistons as vertical bars with travel 0–145, two gantries as horizontal rails 0–840/0–930, live markers, soft-limit bands, homed state, heater glyph on the recoater, recipe cursor + current step label). Dock `TimePlot` of position (and speed) per axis. Rail sections: connection (discovery list, operator address in SITE_MODE, version handshake), arm/E-STOP (ARM toggle, E-STOP, release), axes (per axis: position, speed/accel with bound hints, home, jog ±1/±10/±custom, move-to), heater (on/off, on-time, watchdog), recipe (plan editor grouped by phase, validation verdict, start/dry-run/pause/resume/abort/step, layer progress), recording (name, notes, start/stop, run list). StatusBar (never green): state, poll Hz, E-STOP, drives ready, heater on-time, recorder counters, disk free.
Gating: `connected = reachable && state in {connected, fault}`; `armed`; `controllable = connected && armed`; all motion/heater/recipe-start controls `disabled={!controllable}`; STOP / HEATER OFF / E-STOP / DISARM / PAUSE / ABORT on `connected` only; `window.confirm` on recipe start (non-dry) and heater on; server re-checks (409). `ErrorBoundary` keyed by page. Pure `lib/recipe.ts` mirrors `compile_recipe` for step preview and printability; `lib/machineview.ts` maps mm→px.

## 7. Testing and commissioning
Backend (`uv run pytest`): `test_routes.py` (builders/parsers vs fixtures labelled SDK-derived), `test_simulated.py`, `test_safety.py`, `test_controller.py` (with simulator + fault injection), `test_recipe_compiler.py` (asserts V1.py order/length; 10 print layers), `test_recipe_controller.py`, `test_heater.py` (watchdog), `test_recorder.py` (manifest only on clean stop), `test_api*.py` (TestClient), `test_cors.py`; `--hardware` gates `test_machinemotion_hw.py`. Frontend: `node --test` on `lib/*.test.ts`. CI as siblings.
Commissioning order (morning in lab): (1) Mac Ethernet adapter static 192.168.0.10/24 or USB; `vpi-probe --ip 192.168.0.2 --output plan/probe_report.json` — read-only: /health, positions, drive configs 1–4, M119, 10 s MQTT capture (`estop/status`, `smartDrives/areReady`, `devices/+/+/available`, `drive/+/motionComplete`, `drive/+/error`); NO motion, NO writes. (2) Reconcile fixtures; update `plan/notes.md` data-contract table. (3) `vpi-serve --backend machinemotion --ip 192.168.0.2`; ARM; home printhead gantry; jog ±10 mm. (4) Identify heater module/pin with the relay coil disconnected. (5) Dry-run recipe, 2 print layers, heater disabled. (6) Full recipe with heater.

## Grounding facts (data contract)
See `plan/notes.md` in `vention/` (copied to this repo's `plan/notes.md`): verified-from-files vs verified-from-vendor-docs vs UNVERIFIED lists. Nothing in the UNVERIFIED list may be reported as healthy by the UI until captured.
