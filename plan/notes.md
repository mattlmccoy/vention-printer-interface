# Notes: Vention printer interface feasibility

## Source 1: vention/python/MachineMotion.py (Vention SDK v4.7, 3618 lines)

### Wire protocol (verified by reading the SDK, NOT yet against hardware)
Controller = MachineMotion v2 (BeagleBone AI). Two transports, both plain and open:

**HTTP, port 8000** on the controller IP (`GCode.libPort = ":8000"`, `HTTPSend()` at line 364,
`DEFAULT_TIMEOUT = 65 s`, retries in 65 s slices):
| Route | Method | Body / query | Used by |
|---|---|---|---|
| `/health` | GET | -> JSON `{mqtt_services_running: {"services/mm-vention-control/version": "x.y.z"}, estop_triggered, motion_controller_reachable, devices, ...}` | `_getSoftwareVersion` (async support if >= 2.4) |
| `/gcode?gcode=<urlencoded>` | GET | reply must contain "echo" and "ok" | `G28` home all, `G28 X` home one, `M410` stop all, `M410 X Y` stop axes, `V0` motion-complete ("COMPLETED" in reply), `M114` desired pos (deprecated), `M119` endstops |
| `/smartDrives/position` | GET | -> JSON `{X,Y,Z,W}` mm | `getActualPositions` |
| `/smartDrives/motion/moveAbsolute` | POST json | `{"<axisNo>": position_mm}` | `moveToPosition`, `moveToPositionCombined` |
| `/smartDrives/motion/moveRelative` | POST json | `{"<axisNo>": distance_mm}` | `moveRelative`, `moveRelativeCombined` |
| `/smartDrives/maxSpeed/<axisNo>` | POST json `{"maxSpeed": mm_s}` / GET | `setAxisMaxSpeed` / `getAxisMaxSpeed` |
| `/smartDrives/maxAcceleration/<axisNo>` | POST json `{"maxAcceleration": mm_s2}` / GET | `setAxisMaxAcceleration` / get |
| `/smartDrives/complete/<X|Y|Z|W>` | GET -> `{"complete": bool}` | `isMotionCompleted(axis)` |
| `/smartDrives/get/actualSpeed` | GET json | `getActualSpeeds` |
| `/smartDrives/configuration?drive=N` | GET/POST json | actuator config (we should NOT write this) |
| `/smartDrives/path`, `/path/status`, `/path/stop`, `/path/axisMap`, `/path/tool/N` | path-following (G-code streaming) | `startPath`, ... |

Axis numbering: API axis 1..4 -> controller letters X,Y,Z,W (`__getTrueAxis__`). Move routes take the
numeric axis as JSON key; complete route takes the letter.

**MQTT, port 1883** (paho, `mqtt.Client().connect(machineIp)`, no auth in SDK):
Subscribed on connect: `devices/+/+/available`, `devices/+/+/digital-input/#`,
`devices/encoder/+/realtime-position`, `devices/encoder/+/stable-position`, `estop/status`,
`aux_safety_power/+/status`, `aux_power/+/status`, `smartDrives/areReady`.
Publish: `estop/trigger/request` (payload = message), `estop/release/request`, `estop/systemreset/request`;
responses on `estop/{trigger,release,systemreset}/response` (JSON bool, MQTT.TIMEOUT=10 s).
`devices/io-expander/<id>/digital-output/<pin>` "1"/"0" retained = digitalWrite.
`estop/status` payload = JSON bool -> `estopStatus`.

`waitForMotionCompletion` = poll `V0` (or `/smartDrives/complete/<axis>`) every 0.1 s.
Vention's own scripts note (V1.py) "waitForMotionCompletion command isn't working for some reason" and pad with `time.sleep(1)` -> real-hardware quirk to capture in the probe.

### Default IPs (SDK `DEFAULT_IP_ADDRESS`)
- ethernet: 192.168.0.2 (json/configuration.json confirms `ipAddress: 192.168.0.2`, hardwareVersion V2)
- USB: 192.168.7.2
- Both unreachable from this Mac at 2026-09-08 17:3x (controller not plugged in). Mac has no interface on 192.168.0.x.

## Source 2: vention/json/configuration.json (Vention Control Center export, version 13)
Controller "Printer Controller" uuid e145700a..., ip 192.168.0.2, V2. Four axes (drive order = SDK axis 1..4):
| Drive | friendlyName | axisType | mmPerRotation | motor | brake | rotation | homingSpeed |
|---|---|---|---|---|---|---|---|
| 1 | Part Piston | belt | 150 | Large Servo 10 A closed | present | +1 | 68.8 |
| 2 | Feed Piston | belt | 150 | Large Servo 10 A closed | present | -1 | 68.8 |
| 3 | Printhead Gantry | enclosed_ball_screw | 16 | Medium Servo 10 A closed | none | +1 | 66.3 |
| 4 | Recoater Gantry | enclosed_ball_screw | 16 | Medium Servo 10 A closed | none | +1 | 66.3 |

`Hardware Testing Routine.json` = Vention's no-code sequence editor program (home, "gantry clapping", cart ingress). Not needed for our tool but confirms axis uuids.
`save.json` = app launcher list: V1.py autoLaunch false.

## Source 3: vention/python/V1.py == V2.py (identical, 205 lines) — the real print routine
Axes: part=1, feed=2, printhead=3, recoater=4. Recoater gantry also carries the **heater** (HEATER_* positions use recoater_axis).
Process per layer: part piston down `LAYER_THICKNESS` (+moveRelative) -> recoater to 930 -> feed piston up (-thickness) -> [sleep 1] -> recoater to 5 -> printhead to 840 -> printhead to 5 -> recoater(heater) at slower speed to 600 and back xN.
Phases: precoat (5 mm x1), print (2 mm x N_PRINT_LAYERS=10), postcoat (5 mm x1). Printability check: total thickness <= FEED_END_POSITION 145 mm.
Constants: RECOATER 5..930, HEATER 5..600, PRINTHEAD 5..840, FEED_END 145. Speeds: pistons 2.5 mm/s @ 15; gantries 100 @ 500; heater 50 @ 250.
**No printhead firing, no heater on/off, no IO in these scripts** — only motion. The inkjet/heater control is outside this codebase (question for user).

## Source 4: firmware
`fw/machine_motion_v2.14.0.img` (15.9 GB SD image) and `v2.14.1_CR1.zip` (5 GB). Controller software version 2.14.x -> `_getAsyncSupport()` true (>= 2.4), so the smartDrives REST routes are the ones in use, not legacy G0 G-code.

## Environment
uv, node, npm present. paho-mqtt not installed system-wide (fine, project will use uv).

## Source 5: the rest of the printer stack (context for "true 3D printing workflow")
- Printhead firing is NOT in the Vention codebase. It is Meteor Inkjet MetPrint (Windows PC) consuming a
  **Hot Folder** of per-layer TIFFs. `software/meteor/tools/` holds the custom slicer (`slicer.py`, STL->TIFF
  stack, 720 dpi, 2/4 bpp) and a Flask UI (`web_server.py`) that RIPs/slices and drops TIFFs in the hot folder.
  MetPrint then prints one image per "print trigger" (the printhead gantry pass). So the coordination point
  between motion and jetting is: "layer N TIFF is queued in MetPrint" <-> "printhead gantry pass N".
  No programmatic MetPrint API is used anywhere; hot-folder is the only integration seen. (Ask user how MetPrint
  is triggered per pass today: encoder/PD trigger from the gantry? manual?)
- Heater is on the recoater gantry (V1.py) - on/off control not in code (ask user: manual switch? relay on Vention IO module?).
- Other siblings: FLIR (thermal), TC-POWER (RF generator). TC-POWER already consumes FLIR via `integration/flir_client.py`.
- Vention docs folder only has actuator PDFs; no MachineMotion REST docs locally. The SDK source IS the protocol reference (as PyMeasure was for TC-POWER).

## Source 6: Vention public docs (fetched 2026-09-08)
- mm-python-api README (github.com/VentionCo/mm-python-api): "user applications to execute: internally to MachineMotion; or on an external computer connected to MachineMotion via the Ethernet or DEFAULT Ethernet port." DEFAULT port static 192.168.7.2; ETHERNET port static-or-DHCP (ours: 192.168.0.2 per configuration.json). Requires pip paho-mqtt (+ socketIO-client for old API).
- docs.vention.com "Using MachineMotionV2 communication protocols with MachineLogic": "MachineMotion has a Mosquitto MQTT broker"; no authentication documented; topic table includes `estop/status`, `drive/+/motionComplete`, `drive/+/error`, io-expander topics. HTTP GET/POST/PUT/DELETE supported from firmware 2.12 (ours is 2.14.x).
  -> `drive/<n>/motionComplete` is a push alternative to polling V0; may explain the V1.py waitForMotionCompletion quirk. UNVERIFIED on our unit.
- Low-level TCP socket API on port 9999 is documented only for MachineMotion AI v3.2.0+; NOT applicable to our v2.14 controller.

## Data-contract status (per data-contract-verification rule)
VERIFIED from files: hardware V2 four-drive, firmware 2.14.x, controller IP 192.168.0.2 on the ETHERNET port, four axes + params, V1.py exercised /gcode G28, /smartDrives/maxSpeed, /smartDrives/maxAcceleration, /smartDrives/motion/moveAbsolute+moveRelative, V0 polling (it ran; save.json lists it as an installed app, July 2024).
VERIFIED from vendor docs: SDK is meant to run on an external PC; MQTT broker open; HTTP methods supported.
UNVERIFIED (need live probe): reachability from this Mac (needs Mac adapter on 192.168.0.x or USB 192.168.7.x); exact JSON response shapes; MQTT accepts external clients on 1883 with no auth; `drive/+/motionComplete` payload; IO module id/pin for heater relay; `/health` keys; waitForMotionCompletion quirk root cause.
Rule: no recipe-engine code runs against hardware until `vmm-probe` captures these and the fixtures are replaced with captured samples.

## Source 7: LIVE PROBE of the real controller (2026-09-09, via USB 192.168.7.2)
Connected via the DEFAULT/USB port (192.168.7.2), NOT Ethernet (192.168.0.2 unreachable — the
Ethernet port is unconfigured/unplugged). Mac has two interfaces on 192.168.7.x (en13 .1, en16 .108).
HTTP :8000, MQTT :1883 both open; MQTT CONNACK ok, 10 topics subscribed.

VERIFIED reply shapes (all fast, ~20-30 ms) — our parsers handle them:
- `/health` → `{"time_server_started_at","mqtt_services_running":{"services/mm-io-expander-hub/version":"\"subscribe_failed\"","services/mm-vention-control/version":"v2.14.1"},"devices":{"devices/io-expander/1/available":"true","io-expander/2":"false","3":"false"},"motion_controller_reachable":true,"estop_triggered":false,...}`. Version parses to (2,14,1), async_supported=True. **IO module 1 is present (2,3 absent) → heater IO is almost certainly module 1.**
- `/smartDrives/position` → `{"X":-0.1,"Y":0.1,"Z":250,"W":-0.1}` (Z=250, not homed). Parses.
- `/smartDrives/complete/X` → `{"complete":true}`. Parses.
- `/smartDrives/maxSpeed/1` → `{"maxSpeed":100}`; `/maxAcceleration/1` → `{"maxAcceleration":100}`. Parse.
- `/smartDrives/get/actualSpeed` → `{"actual speed":{"1":0,"2":0,"3":0,"4":0}}` (note key "actual speed" with a space).
- `V0` → `echo: Motion Status = COMPLETED ok, {"1": true, "2": true, "3": true, "4": true}` — has "echo"+"ok"+"COMPLETED"; parse_motion_status/parse_echo_ok OK. (Trailing JSON per-axis is extra; we only check "COMPLETED".)
- `M119` → `echo ok:\n x_min: open \n x_max: open ...` for x/y/z/w min+max. parse_endstops regex OK.
- `/smartDrives/configuration?drive=1` → `{"axisType":"enclosed_ball_screw","gain":16,"gearRatio":1,"motorCurrent":10,"loop":"closed","tuningProfile":"default","direction":"negative","brake":true,"motorSize":"Large Servo","parent":1}`. **DISCREPANCY vs the Control Center export (configuration.json): the live route uses `gain`/`loop`/`direction`, has NO `friendlyName` and NO `homingSpeed`.** `identify()` tolerates this (keeps our name/homingSpeed defaults); axis names come from our KNOWN_AXES, not the controller.

CRITICAL FINDING — **`/health` blocks ~5.1 s** (TTFB 5.13 s; confirmed with curl AND a raw socket, so it is the controller, not httpx). Cause: the health handler waits on the failing `mm-io-expander-hub` subscribe (`"subscribe_failed"`). Every other route is instant. Fix: give `/health` a long timeout and DO NOT poll it in the protection loop (was every 10 ticks → would hold the io-lock 5 s and trip the 2 s stale-telemetry fault). Health is now fetched once at connect; ongoing protection uses position reads (fail→fault) + MQTT estop/drives.

## Probe reconciliation (2026-09-09) — data-contract items now VERIFIED
- MQTT fully works. **`drive/N/motionComplete` and `drive/N/error` ARE published** (were UNVERIFIED
  from Vention docs): motionComplete="1" idle, error="[]". A push alternative to polling V0.
- estop/status="false", smartDrives/areReady="true", devices/io-expander/1/available="true"
  (2-8 false). **Heater IO is on module 1** — pin still to identify with the coil disconnected.
- Axis ROLE map UNCHANGED and correct: drive 1 Part Piston, 2 Feed Piston (both Large Servo +
  brake, now enclosed_ball_screw gain 16 — re-fitted from the belts in configuration.json), 3
  Printhead Gantry, 4 Recoater Gantry (Medium Servo, no brake, axisType "custom"). Our KNOWN_AXES
  names/roles hold; TRAVEL extents (145/145/840/930 mm from V1.py) must be re-measured before
  powered moves since the pistons are now ball-screws.
- Live drive config route has NO friendlyName/homingSpeed (uses gain/loop/direction); identify()
  tolerates this. Positions at probe: X=-0.1 Y=0.1 Z=250 W=-0.1 (Z/printhead not homed).
- **`/health` blocks ~5.1 s** (io-expander-hub subscribe_failed). Fixed: long timeout + not polled
  in the protection loop (health_refresh_s default 0; fetched once at connect).
- Reached via USB 192.168.7.2 (Ethernet 192.168.0.2 unplugged). Connect with `--ip 192.168.7.2`.

## Homing finding (2026-09-09) — axes home to NEGATIVE positions
Homed the recoater (drive 4): moved the correct direction, came to rest at **-22.0 mm**, not 0.
So the controller's post-home coordinate is below our assumed 0, and the old soft floor [0, extent]
faulted (`axis 4 at -22 mm outside [0.0, 930.0]`) and blocked clear_fault. Fix: `TRAVEL_FLOOR = -50`
and default `travel_min = -30` for every axis (covers the -22 home with margin); a real overshoot
past -30 (or past the extent) still trips. TODO before powered print moves: measure each axis's true
homed position and set per-axis travel_min precisely (recoater ~-22; pistons rest ~0; printhead not
yet homed this session, was at 250).

## Homing recovery fix (2026-09-09) — position limits must not block homing
Symptom chain: our position-limit protection FAULTED on the transient negative travel during a
home, issued M410 (stop), interrupted the home before it could complete and re-zero, leaving the
recoater parked further and further negative (-22 → -51.8) across attempts. That out-of-range
parked position then latched a FAULT on connect and blocked arming → couldn't home → deadlock.
Fixes:
1. Homing suspends position-limit checks (Controller `_homing_until`, HOMING_WINDOW_S=30 s, cleared
   early once motion settles; evaluate(home_in_progress=True) skips the position loop). The drive's
   own limit switches are the hard guard during a sensor-seeking home.
2. Position-outside-window is now a WARNING ("axis N at X mm outside [...] — home it"), never a
   latched fault. Commanded moves are still clamped to the window (clamp_position), so software
   cannot drive out of range; a parked-out-of-range axis stays recoverable via homing.
Verified on hardware: connect at -51.8 mm → CONNECTED with warning (not fault) → arm succeeds.

## Homing VERIFIED working (2026-09-09) — CORRECTION
With the fix, a completed home re-zeros the axis to **0.0** (recoater drive 4: -51.8 → 0.0 after
HOME). So axes DO zero to 0 on a clean home; the earlier -22/-51.8 were interrupted-home artifacts
(protection stopping the move), NOT the machine's real home. The -30 travel_min floor + out-of-range
warning stay as robustness (moves are clamped; harmless), but per-axis travel_min can be tightened
back toward 0 once each axis is confirmed homing to 0. Positions after recoater home:
{1: -0.1, 2: 0.1, 3: 250.0 (printhead not yet homed), 4: 0.0}. Full print-motion path (G28 → move →
protection) now proven end-to-end on real hardware.

## Piston mechanics (2026-09-09, from user slides) — CRITICAL, powder-eject risk
Piston position commands are INVERTED vs the console's earlier assumption (small = up/flush,
large = down/bottom), and **homing a piston (G28 → 0) drives it fully UP = flush with the
substrate = ejects all powder.** Gantries (drives 3,4) are safe to home; pistons (drives 1,2)
must NEVER be homed while loaded.
- Build/part cylinder (drive 1): command 4 mm ≈ top (near substrate), 70 mm ≈ bottom; ~56 mm
  printable height ("can totally lengthen cylinder"). To print, the part piston DESCENDS
  (command increases) to open room for the next layer.
- Feed cylinder (drive 2): command 11 mm ≈ top, 80 mm ≈ bottom; **0 mm = flush with substrate**.
  To feed, the feed piston RISES (command decreases) to push fresh powder up for the recoater.
- Workflow: fill the bottom with several layers of virgin powder (manual is fine), then per layer:
  recoater spreads fresh powder → printheads jet ink (multiple passes if needed) → recoater pass
  to evaporate IPA.
Console implications (DONE where noted): HOME ALL must not home pistons (→ "HOME GANTRIES",
homes 3,4 only); per-piston home is behind an explicit "ejects powder" confirm; the print-settings
compiler must NOT emit home_all for a loaded print (home gantries only) — HOLD exact routine until
the user's print-routine code arrives. Travel extents to re-measure: build ~4-70+, feed ~0/11-80.
