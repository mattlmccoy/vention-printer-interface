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
