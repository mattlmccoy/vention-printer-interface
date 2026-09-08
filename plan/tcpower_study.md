# TC Power Interface — what it added to the family (condensed, 2026-09-08)

Repo: .../software/TC-POWER. Built explicitly to mirror FLIR ("so the two read as one family").

## Identical to FLIR (copy unchanged)
theme.css tokens (header: "Reused verbatim from the FLIR Research Interface..."), pyproject skeleton (hatchling, ruff/mypy/pytest blocks, `hardware` marker), `install_cross_origin_policy` (only header name differs: x-tcp-client), lib/operator.ts (normalizeBase/loadOperatorBase/apiUrl/wsUrl/checkHandshake; key tcp.operator.v1; DEFAULT_SITE_BASE http://localhost:8010), vite.config (ports only), no-test-framework `node --test` on lib/*.ts only, registry+factory (`@register_transport(name)` decorator, `create_transport(name, **kw)`), create_app factory + lifespan + app.state + StaticFiles mount, CI/Pages workflows (VITE_BASE=/tc-power-interface/), layout backend/ frontend/ docs/ plan/ docs/superpowers/{specs,plans}, `<tool>-probe` read-only commissioning CLI first, recorder integrity model (metadata.json at start; events.json + manifest.json w/ sha256 only on clean stop; missing manifest = crashed run).

## Port / prefix convention
FLIR 8000/5173 fri-/x-fri-client/fri.* ; TC-POWER 8010/5174 tcp-/x-tcp-client/tcp.* ; **Vention -> 8020/5175, vmm-serve/vmm-probe/vmm-monitor, x-vmm-client, localStorage vmm.*.v1, keyframes vmm-***.

## Backend patterns new in TC-POWER (the ones a controller tool needs)
- Layering: protocol/codec.py PURE (bytes only, no IO) -> device/base.py `Transport` ABC (write/read(n)/close) + registry (`simulated`, `serial`) -> device/cxn.py high-level wrapper (one method per capability; unsafe commands simply do not exist as methods) -> control/controller.py supervisory -> api.
- Simulator speaks the REAL wire protocol over a bytearray with device state + physics model + fault-injection knobs (`deny_control=True`, etc.). "A model of the CXN, not a capture of the physical unit."
- control/safety.py: `HARD_BOUNDS` tighten-only; `@dataclass(frozen=True) SafetyLimits.bounded(**)`; pure `evaluate(telemetry, limits, telemetry_age_s) -> SafetyDecision(trip, reasons, warnings)`. No IO.
- Controller: states DISCONNECTED/CONNECTED/FAULT/CLOSED; `_lock` for state + `_io_lock` serializing ALL transport calls; poll thread `_tick` (0.5 s) feeds listeners + protection every tick; any read exception -> FAULT; `clear_fault()` only if latest sample clean; `add_listener(cb)` fan-out (exceptions swallowed); ARM gate `_require_armed()`; `estop()` bypasses all gates; `attach_device/detach_device` runtime; guarded actions vs ungated safe-direction (disable/stop); single `snapshot() -> dict`.
- Feature-loop pattern (x5): `X_BOUNDS`, frozen `XPlan.bounded()`, pure step fn, `XController(controller, *, plan)` with start/stop/tick(dt)/snapshot, wired via `controller.add_listener(lambda _: x.tick(dt))`, routes `/api/<x>` GET/PUT (+bounds) and `/start` `/stop`, folded into status.
- Persistence sidecars: dotfile `.x.json` under experiments_root; load swallows FileNotFound/ValueError and re-clamps via `.bounded()`.
- API: `GET /api/status` and `/ws/telemetry` (JSON push every 100 ms) are the SAME `_status_payload()`. Routes: health, status, discovery, connect, disconnect, arm, disarm, estop, per-feature config+start/stop, recording start/stop/status, recordings list + csv (path-traversal guard), auto-log, flir-link. Middleware `Cache-Control: no-store` on text/html.
- `_stop_all_features()` on disconnect/disarm/estop.
- Recorder: telemetry.csv streamed + flushed per row; events.json/manifest.json on clean stop.
- integration/: pure parser + local `websockets` import (flir_client.py); best-effort daemon-thread POST with injectable `_post` and `last_result` (flir_link.py); edge-detector listener (rf_link_notifier.py); polling source with pure fail-safe selector returning valid=False on stale/missing (flir_roi_temps.py). Doctrine: separate programs over one HTTP contract; consumer owns policy; best-effort; never blocks or trips.
- CLIs: tcp-serve (`--backend none|simulated|serial`, `--serial` implies serial, `--poll-interval`, `--experiments-root`, `--site-origin`, `--flir-url`); tcp-probe (read-only, never requests control, `--samples --interval --output`); tcp-monitor (through the real controller).
- deploy/install-operator-service.sh LaunchAgent (KeepAlive) + uninstall.

## Frontend patterns new in TC-POWER
- App.tsx tabs (dashboard/settings/experimental) rather than Studio rails; components ErrorBoundary (keyed by view), Gauge (SVG), StatusLeds, TimePlot; lib/ api.ts (test locks method+URL+body per route), operator.ts, telemetry.ts (TS mirrors of payloads + TraceBuffer), format.ts, instrument.ts, settings_store.ts (pending offline sync).
- Gating: `connected = reachable && (state=="connected"||"fault")`, `armed = connected && ctrl.armed`, `controllable = connected && armed`; ~40 controls `disabled={!controllable}`; safe-direction (OFF/E-STOP/DISARM) gated only on `connected`; window.confirm on RF ON; server re-checks (409). Version handshake banner. Operator-address field only in SITE_MODE.
- theme.css additions: `--err-btn #cf3b2e` (WCAG for white text), `--rec var(--err-btn)`, domain traces `--trace-fwd/--trace-refl`, topbar 44px, keyframes tcp-*.

## Process discipline
plan/notes.md: `## Sources` w/ provenance+license; wire tables with line citations; `## Data-contract status` ("CAPTURED FROM reference, NOT from our physical unit... reconcile with probe... do not silently trust"); `## FLIR conventions to mirror` checklist. plan/task_plan.md per-branch: root-cause table (symptom | root cause file:line | fix kind), tasks ONE at a time w/ evidence embedded, verification gates with expected green counts. Confirmed facts inlined with date in code comments. docs/superpowers/specs: Status, Goal, Non-goals, Principles (firm), Safety model (firm), Grounding facts. docs/superpowers/plans: RED->GREEN TDD steps per task with test file listed.
