# Commissioning (lab session)

Order matters. Each step is a gate for the next.

## 0. Network

Connect the Mac to the controller's **ETHERNET** port (or USB → 192.168.7.2). On the Mac:
System Settings → Network → the USB-Ethernet adapter → Configure IPv4: Manually,
IP `192.168.0.10`, subnet `255.255.255.0`, no router.

```bash
ping -c 3 192.168.0.2
curl -s http://192.168.0.2:8000/health | head -c 400
```

## 1. Read-only probe (no motion, no writes)

```bash
cd backend
uv run vpi-probe --ip 192.168.0.2 --samples 5 --mqtt-seconds 10 --output ../plan/probe_report.json
```

Read the report. Expect: `health.version` 2.14.x, `async_supported` true, four positions, four
`complete_raw` replies containing `"complete"`, `mqtt["estop/status"]` and
`mqtt["smartDrives/areReady"]` populated, at least one `devices/io-expander/<id>/available`.

## 2. Reconcile

Compare `plan/probe_report.json` against `backend/tests/test_parsers.py` fixtures. Where the real
shape differs, change the parser (test first), and record the finding with the date in
`plan/notes.md` "Data-contract status".

## 3. First motion (ARMed, one gantry)

```bash
uv run vpi-serve --ip 192.168.0.2 --heater-io 1,0
# in another shell
curl -s -X POST localhost:8020/api/arm
curl -s -X POST localhost:8020/api/motion/home -H 'content-type: application/json' -d '{"axes":[3]}'
curl -s localhost:8020/api/status | python3 -m json.tool | grep -A6 positions
curl -s -X POST localhost:8020/api/motion/move -H 'content-type: application/json' -d '{"axis":3,"mode":"rel","mm":10}'
curl -s -X POST localhost:8020/api/motion/stop -H 'content-type: application/json' -d '{}'
```

Watch for the V1.py quirk: if `motion_complete` stays false after the axis has visibly stopped,
note the delay; the print settings engine (Plan 2) can use `drive/<n>/motionComplete` instead if the probe
showed it.

## 4. Heater IO pin (relay coil disconnected)

With the heater relay coil **disconnected**, try each candidate and listen for the relay click /
measure the output pin:

```bash
uv run vpi-serve --ip 192.168.0.2 --heater-io 1,0     # then POST /api/arm, /api/heater/on, /api/heater/off
```

Repeat for `1,1`, `1,2`, `1,3` (and other module ids the probe listed). Record the confirmed pair in
`plan/notes.md` with the date and make it the `--heater-io` default.

## 5. Two-layer dry run, heater disabled (Plan 2)

## 6. Full print settings with heater (Plan 2)
