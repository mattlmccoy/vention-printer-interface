# Motor data + finish screen — implementation plan

**Branch:** feat/restore-print-choreography  **Started:** 2026-09-15

## Goal
Better end-of-print/abort finishing screen with statistics; collect + plot full
motor data (pos/vel/accel, all axes) at high fidelity, with build-piston
commanded-vs-actual layer-height accuracy as the headline metrology.

## Verified reality (data-contract)
- `recorder.py` already writes `motion_profiles.csv` = pos/vel/accel for axes 1-4,
  vel/accel DERIVED from position by finite differences (5 Hz telemetry).
- `layers.csv` logs COMMANDED `part_height_mm` per layer + timestamp.
- MM2 native telemetry: `/smartDrives/position` (used) + `/smartDrives/get/actualSpeed`
  (`getActualSpeeds`, mm/s, NOT currently read). `readEncoder` NOT supported on MM2.
- Runs page plots recoater velocity only (`parseVel(csv, axis=4)`).
- Finish UI: `done` shows "complete", `aborted` shows a label. No stats.
- Telemetry poll ~5 Hz (poll_interval_s=0.2). A 0.2 mm drop @2.5 mm/s ~0.08 s < one sample.

## Tasks (TDD each; commit per task)
- [ ] T1 DONE: priming auto routine reorder (committed 4a7b2fe).
- [ ] T2 backend: `parse_actual_speed` for `/smartDrives/get/actualSpeed` JSON
      (`{"actual speed":{"1":v,...}}`). Pure, TDD.
- [ ] T3 backend: Telemetry struct + `read_telemetry` add `actual_speed: dict[int,float]`
      (native). Simulated device supplies a plausible value. Logic TDD; HW-validate later.
- [ ] T4 backend: telemetry.csv add `vspeed_1..4` (native). recorder + FIELDS. TDD.
- [ ] T5 backend: `motion_profiles.csv` prefer native speed when present (else finite-diff);
      accel = d(native speed)/dt. TDD `motion_profile_rows`.
- [ ] T6 backend: build-piston layer accuracy — new pure fn deriving per-layer
      {layer, commanded_mm, actual_mm (settled Δpos_1), deviation_mm} from telemetry+layers,
      + summary (mean/max/σ). Write `layer_accuracy.csv` at stop + include in run stats/endpoint. TDD.
- [ ] T7 backend: raise print-time poll rate (configurable; default finer during active print).
      Touches monitor/controller loop — HW-validate. Guard HTTP load (position+actualSpeed = 2 GETs/poll).
- [ ] T8 frontend: finish screen (done/aborted) with stats — outcome, layers done/planned,
      duration, commanded vs measured part height, build-piston accuracy, heater on-time,
      abort where/why, link to Runs.
- [ ] T9 frontend: Runs plotting refresh — per-axis select + pos/vel/accel metric toggle +
      dedicated build-piston commanded-vs-actual layer-height chart.

## Notes / risks
- Do NOT restart the live operator while a print runs. User restarts after.
- Native speed + poll rate need a real run to validate; pure logic is unit-tested.
- 2 HTTP GETs/poll at higher rate may bottleneck — measure on HW, back off if needed.
