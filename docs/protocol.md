# MachineMotion 2 protocol (as used here)

Source: Vention `MachineMotion.py` v4.7 (line numbers below), `vention/json/configuration.json`,
and Vention public docs where marked. Controller: firmware 2.14.x, ETHERNET IP 192.168.0.2,
DEFAULT/USB IP 192.168.7.2. HTTP on :8000, MQTT (Mosquitto, no auth) on :1883.

## HTTP

| Route | Method / body | Reply (SDK-derived) | SDK line |
|---|---|---|---|
| `/health` | GET | `{mqtt_services_running: {"services/mm-vention-control/version": "x.y.z"}, estop_triggered, motion_controller_reachable, ...}` | 1393-1441 |
| `/gcode?gcode=<urlencoded>` | GET | text containing `echo` and `ok` | 477, 486-495 |
| `/smartDrives/position` | GET | `{"X","Y","Z","W"}` mm | 536, 1171-1185 |
| `/smartDrives/motion/moveAbsolute` | POST json `{"<axis 1..4>": mm}` | ignored | 1620-1624 |
| `/smartDrives/motion/moveRelative` | POST json `{"<axis>": mm}` | ignored | 1688-1692 |
| `/smartDrives/maxSpeed/<axis>` | POST json `{"maxSpeed": mm_s}` / GET | `{"maxSpeed": ...}` | 1478, 1504 |
| `/smartDrives/maxAcceleration/<axis>` | POST json `{"maxAcceleration": mm_s2}` / GET | | 1565, 1592 |
| `/smartDrives/complete/<X|Y|Z|W>` | GET | `{"complete": bool}` | 1795-1799 |
| `/smartDrives/configuration?drive=N` | GET (read-only here) | JSON, shape UNVERIFIED | 519 |

G-code via `/gcode`: `G28` home all (1369), `G28 X` (1387), `M410` stop all (1339), `M410 X Z`
(1359), `V0` motion status, "COMPLETED" when idle (1786), `M119` endstops (1229).

## MQTT

| Topic | Direction | Payload | Source |
|---|---|---|---|
| `estop/status` | sub | JSON bool | 199 |
| `estop/trigger/request` → `estop/trigger/response` | pub / sub | reason text → JSON bool | 200-201, 2350-2389 |
| `estop/release/request` → `.../response` | pub / sub | "" → JSON bool | 202-203 |
| `estop/systemreset/request` → `.../response` | pub / sub | "" → JSON bool; drives ready ~3 s later | 204-205, 2445-2499 |
| `smartDrives/areReady` | sub | JSON bool | 210 |
| `devices/io-expander/<id>/available` | sub | JSON bool | 2764, 2830 |
| `devices/io-expander/<id>/digital-output/<pin>` | pub (retain) | "1"/"0" | 2140-2147 |
| `devices/io-expander/<id>/digital-input/<pin>` | sub | "1"/"0" | 2765, 2846 |
| `drive/<n>/motionComplete`, `drive/<n>/error` | sub | UNVERIFIED | Vention docs |

## Data-contract status (unverified against our unit)

Everything above is CAPTURED FROM the SDK source, NOT from our physical controller. Test fixtures
derived from it are "shape/spec-correct", not hardware-captured. Before any powered operation, run
`vpi-probe --ip 192.168.0.2 --output plan/probe_report.json` and reconcile every reply shape,
the MQTT payloads, and the heater IO module id/pin. Flag disagreements in `plan/notes.md`; do not
silently trust.
