# Architecture

```
MachineMotion 2 (HTTP :8000, MQTT :1883)
  → protocol/   build requests, parse replies                       (pure, no IO)
  → device/     Transport {http_get, http_post_json, mqtt_publish, mqtt_latest, mqtt_request}
                registry: simulated | machinemotion
  → device/printer.py   PrinterDevice: one method per capability (no config-write methods exist)
  → control/    safety.evaluate() (pure) + Controller (poll thread, io lock, ARM, E-STOP, FAULT)
  → recording/  Recorder (metadata at start, csv streamed, manifest on clean stop)
  → api/        FastAPI: GET /api/status == /ws/telemetry (10 Hz); guarded commands → 409
  → frontend/   Studio UI (Plan 3)
```

Three data concerns are kept apart, as in the FLIR and T&C tools:

1. **Raw controller protocol** (`protocol/`) — strings and dicts in/out, no IO.
2. **Device + control state** (`device/`, `control/`) — the transport, telemetry, the protection
   verdict, the ARM gate. All device IO is serialized behind one lock.
3. **Presentation** (`api/`, `frontend/`) — never mutates control state except through the
   guarded command methods.

## Control layering (protection dominant)

1. **Protection** — `safety.evaluate(sample, limits, age, heater_on_s, move_pending)` is a pure
   function evaluated every poll. Trips: stale telemetry, controller e-stop, health not ok, drives
   not ready while a move is pending, position outside the soft travel window, heater on past its
   watchdog. A trip stops all motion (`M410`), writes the heater output low, latches FAULT and
   disarms. While faulted, every successful poll re-enforces stop + heater-off (a fault action may
   have failed while the link was down). `clear_fault` needs a fresh clean sample.
2. **ARM gate** — guarded: home, move, speed, accel, heater on, recipe start (Plan 2).
   Never gated: stop, heater off, E-STOP, disarm.
3. **E-STOP** — best-effort in any state: `M410`, heater off, MQTT `estop/trigger/request`,
   disarm. Release is a separate explicit action (`estop/release` then `estop/systemreset`, wait
   for `smartDrives/areReady`).
4. **Recipe engine** (Plan 2) — a feature loop ticked from the controller listener; one step in
   flight, advance on motion-complete, per-step timeout → FAULT.

## Why nothing runs on hardware yet (by design)

Every reply shape and topic payload is transcribed from the SDK, not captured from our unit. The
staged order in `docs/commissioning.md` is: read-only probe → reconcile fixtures → ARM and home one
gantry → identify the heater IO pin with the relay coil disconnected → two-layer dry run → full
recipe.
