# Task plan — Vention Printer Interface

Spec: `docs/superpowers/specs/2026-09-08-vention-printer-interface-design.md`.
Plans: `docs/superpowers/plans/2026-09-08-backend-core.md` (Plan 1), Plan 2 recipe engine, Plan 3 UI.

## Plan 1 — backend core (2026-09-08/09)
- [x] T1 scaffold · T2 routes · T3 parsers · T4 registry · T5 simulator · T6 real transport
- [x] T7 PrinterDevice · T8 safety · T9 controller · T10 limits store · T11 recorder
- [x] T12 API + CORS + WS · T13 vpi-serve · T14 vpi-probe/monitor · T15 docs/CI
- Verification: `uv run pytest` 102 passed (1 hardware test skipped); ruff + mypy strict clean;
  `vpi-serve --backend simulated` live: connect → arm → home → move 100 mm applied → 403 on
  cross-origin write without header.
- Findings during TDD: (a) `clear_fault` must refuse while the last read failed, not just when the
  stale sample looks clean; (b) a fault's heater-off can fail while the link is down, so FAULT
  re-enforces stop + heater-off on every successful poll.

## Blocked on the user (lab)
- [ ] Step 0-1: network + `vpi-probe --ip 192.168.0.2` → `plan/probe_report.json`
- [ ] Step 2: reconcile parsers/fixtures; update `plan/notes.md`
- [ ] Step 3-4: first ARMed motion; heater IO pin identification

## Open technical unknowns
- Reply JSON shapes (positions, complete, health) — SDK-derived only.
- `drive/+/motionComplete` payload and whether it fixes the V1.py completion quirk.
- Heater IO module id/pin (default `1,0` is a placeholder).
- Whether the controller's MQTT broker accepts external clients without auth (docs say yes).

## Next
- Plan 2: recipe engine (`control/recipe*.py`, `/api/recipe*`, `layers.csv`).
- Plan 3: Studio UI.
