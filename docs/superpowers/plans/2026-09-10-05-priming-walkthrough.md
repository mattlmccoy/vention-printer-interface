# Priming Walkthrough — Implementation Plan (Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Pure helpers are red-green TDD'd; UI/layout is verified by tsc-clean `npm run build` + full suite green (incl. `theme.test.ts`) + a coordinator browser check (the TDD-substitution gate).

**Goal:** Replace the static full-page Priming view with a guided, stepped **powder-loading + leveling walkthrough** that computes the feed-cavity fill depth from the print it will feed, exposes bounded recoater + piston controls, runs each move on operator command, and shows blinking directional arrows on the pistons while they move.

**Architecture:** Driven by discrete `api.move(axis,"abs"|"rel",mm)` calls per step (no new backend step-engine); targets come from the saved `PrimingSettings` (persisted via the existing `api.setPriming`). The fill-depth calc is a new pure `powder.ts` (TDD). Piston direction is a new pure `pistonArrow` in `diagram.ts` (TDD). The live `Elevation` (Task 4 markers) stays the centerpiece; a new bounded `ControlStrip` gives per-axis correction. Spec: `docs/superpowers/specs/2026-09-10-priming-walkthrough-design.md`.

**Tech Stack:** Vite + React + TS. Branch: `redesign/ux-visual` (current). Tokens: theme.css is the single source; **styles.css stays no-`:root` / no-color-literal** (enforced by `src/lib/theme.test.ts`).

**Baseline facts (verified in code):** pistons PART=1/FEED=2 travel 0–145 mm; `move_abs` large=DOWN (open cavity), small=UP/flush; `PrintSettingsPayload.total_thickness_mm` already sums thick+thin+print(+post); `api.move`, `api.printSettings`, `api.setPriming`, `api.primingRun`, `api.printResume`, `api.printAbort` all exist.

---

## Task 1: `powder.ts` — fill-depth calculation (pure, TDD)

**Files:** Create `frontend/src/lib/powder.ts`, `frontend/src/lib/powder.test.ts`.

- [ ] **Step 1 — Write the failing test** `frontend/src/lib/powder.test.ts`:
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { fillDepthMm, cavityFillPct } from "./powder.ts";

test("job source: total thickness + margin, clamped to feed travel", () => {
  assert.equal(fillDepthMm({ source: "job", totalThicknessMm: 24, marginMm: 5 }), 29);
  // clamps to feedTravelMm (default 145)
  assert.equal(fillDepthMm({ source: "job", totalThicknessMm: 200, marginMm: 5 }), 145);
});
test("manual layers x thickness + margin", () => {
  assert.equal(fillDepthMm({ source: "layers", nLayers: 40, layerThicknessMm: 0.5, marginMm: 3 }), 23);
});
test("manual depth passes through, clamped to >= 0", () => {
  assert.equal(fillDepthMm({ source: "depth", manualDepthMm: 31.5 }), 31.5);
  assert.equal(fillDepthMm({ source: "depth", manualDepthMm: -4 }), 0);
});
test("cavity fill percent of feed travel", () => {
  assert.equal(cavityFillPct(29), 20);        // 29/145 → 20%
  assert.equal(cavityFillPct(300), 100);      // clamps at 100
});
```

- [ ] **Step 2 — Run it, see it fail** — `cd frontend && node --experimental-strip-types --test src/lib/powder.test.ts`. Expected: FAIL — `Cannot find module './powder.ts'`.

- [ ] **Step 3 — Implement** `frontend/src/lib/powder.ts`:
```ts
export const FEED_TRAVEL_MM = 145; // safety.TRAVEL_MM[FEED]; the feed cavity can open at most this far.

export type FillSource = "job" | "layers" | "depth";
export interface FillInput {
  source: FillSource;
  totalThicknessMm?: number;   // source "job": PrintSettingsPayload.total_thickness_mm
  nLayers?: number;            // source "layers"
  layerThicknessMm?: number;   // source "layers"
  manualDepthMm?: number;      // source "depth"
  marginMm?: number;           // safety extra added to job/layers (calibration-pending default)
  feedTravelMm?: number;       // default FEED_TRAVEL_MM
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** Feed-piston fill depth (mm) = how far DOWN to open the feed cavity so a print has enough powder.
 *  "job"    → total print thickness consumed from the feed piston + margin (exact; incl. thick precoats).
 *  "layers" → nLayers × layerThickness + margin (operator must include the precoat layers).
 *  "depth"  → operator's direct mm.
 *  Clamped to [0, feedTravel].
 *  FUTURE (calibration): a "volume" source computing depth from the powder volume needed to fill the
 *  part-piston cavity + runway backfill — needs the feed/part cylinder cross-section areas, which are
 *  NOT in the codebase yet. Do not wire that path until those areas are measured. */
export function fillDepthMm(i: FillInput): number {
  const margin = i.marginMm ?? 0;
  const travel = i.feedTravelMm ?? FEED_TRAVEL_MM;
  let raw: number;
  if (i.source === "job") raw = (i.totalThicknessMm ?? 0) + margin;
  else if (i.source === "layers") raw = (i.nLayers ?? 0) * (i.layerThicknessMm ?? 0) + margin;
  else raw = i.manualDepthMm ?? 0;
  return clamp(raw, 0, travel);
}

/** What fraction of the feed travel the cavity uses, 0–100 (a fill gauge). */
export function cavityFillPct(depthMm: number, feedTravelMm: number = FEED_TRAVEL_MM): number {
  return clamp(Math.round((100 * depthMm) / feedTravelMm), 0, 100);
}
```

- [ ] **Step 4 — Run it, see it pass** — same command. Expected: PASS (4 tests).

- [ ] **Step 5 — Commit** — `git add frontend/src/lib/powder.ts frontend/src/lib/powder.test.ts && git commit` → `feat(powder): fill-depth calc from job/manual (feed-cavity seam)` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Task 2: `pistonArrow` — direction from position delta (pure, TDD)

**Files:** Modify `frontend/src/lib/diagram.ts`; modify `frontend/src/lib/diagram.test.ts` (add a test — do not remove the existing `markerClass` test).

- [ ] **Step 1 — Add the failing test** to `frontend/src/lib/diagram.test.ts`:
```ts
import { markerClass, pistonArrow } from "./diagram.ts";
test("piston arrow direction from position delta", () => {
  assert.equal(pistonArrow(10, 12), "down");  // position grows → piston descends → down
  assert.equal(pistonArrow(12, 10), "up");    // position shrinks → piston rises → up
  assert.equal(pistonArrow(10, 10), null);    // no movement
  assert.equal(pistonArrow(null, 10), null);  // unknown prev → no arrow
});
```
(Keep the existing `import { markerClass }` test working — merge the import to `import { markerClass, pistonArrow } from "./diagram.ts";`.)

- [ ] **Step 2 — Run it, see it fail** — `node --experimental-strip-types --test src/lib/diagram.test.ts`. Expected: FAIL — `pistonArrow is not a function` (or export missing).

- [ ] **Step 3 — Implement** in `frontend/src/lib/diagram.ts` (append):
```ts
export type ArrowDir = "up" | "down";
/** Piston travel direction from consecutive positions: position GROWS = piston descends ("down"),
 *  SHRINKS = rises ("up"); equal or unknown prev = null (no arrow). Threshold guards float jitter. */
export function pistonArrow(prev: number | null, curr: number | null, eps = 0.05): ArrowDir | null {
  if (prev === null || curr === null) return null;
  const d = curr - prev;
  if (Math.abs(d) < eps) return null;
  return d > 0 ? "down" : "up";
}
```

- [ ] **Step 4 — Run it, see it pass** — same command. Expected: PASS (both tests).

- [ ] **Step 5 — Commit** — `feat(diagram): pistonArrow direction helper` + trailer.

## Task 3: Blinking piston arrows in `Elevation.tsx`

**Files:** Modify `frontend/src/components/Elevation.tsx`; add styles in `frontend/src/styles.css` (tokens only).

- [ ] **Step 1** — In `Elevation.tsx`, track previous positions across renders with a ref, and render a directional arrow on each piston that is in motion:
  - Add `import { useRef } from "react";` and `import { markerClass, pistonArrow, type DiagramMode } from "../lib/diagram.ts";`.
  - Near the top of the component: `const prev = useRef<Record<number, number | null>>({ 1: null, 2: null });`.
  - Inside the two-piston `.map(...)` (axes 2 feed, 1 build), compute `const dir = pistonArrow(prev.current[axis], mm); const moving = mv(axis);` then AFTER computing, update `prev.current[axis] = mm;`.
  - When `moving && dir`, render an arrow glyph beside the piston rect: a small SVG `<path>` or `<text>` triangle just above (`dir==="up"`) or below (`dir==="down"`) the piston bar at `x = r.x + r.w/2`, class `el-arrow ${dir==="up" ? "up" : "down"}`. Use a `<polygon>`/`<path>` triangle (crisp at any scale), `aria-hidden`.
  - The arrow only renders while `moving` is true; it is the ONLY new visual — do not change the existing rects/markers.

- [ ] **Step 2 — Style** in `styles.css` (append near the elevation rules, tokens only — NO hex/rgb): `.el-arrow { fill: var(--accent); }` and a blink: `@media (prefers-reduced-motion: no-preference) { .el-arrow { animation: vpi-arrow-blink .6s steps(1,end) infinite; } } @keyframes vpi-arrow-blink { 50% { opacity: 0; } }`. (Steady arrow under reduced-motion.) Colour via `var(--accent)` or `var(--live)` — pick one existing token; no literal.

- [ ] **Step 3 — Verify** — `cd frontend && npm run build` (tsc clean + vite) and `npm test` (whole suite green, incl. theme no-literal check). Browser check by coordinator: a moving piston shows a blinking arrow pointing in its travel direction.

- [ ] **Step 4 — Commit** — `feat(diagram): blinking directional arrows on moving pistons` + trailer.

## Task 4: On-diagram nudge controls (▲/▼ at each piston, ◀/▶ at the recoater)

> **Design pivot (user, 2026-09-10):** the controls live **on the diagram itself**, right next to the
> thing they move — a **▲ (up) / ▼ (down)** pair at each piston, and **◀ / ▶** arrows at the recoater
> gantry — each issuing a bounded relative nudge. This replaces a separate control panel. Direct
> manipulation; no free jog; the backend clamps every target to travel.

**Files:** Modify `frontend/src/components/Elevation.tsx` (add optional in-SVG control clusters); styles in `frontend/src/styles.css` (tokens only). In-SVG (not an HTML overlay) so the buttons scale with the diagram's `viewBox`.

- [ ] **Step 1** — Give `Elevation` optional interactive controls. Add props:
```ts
onNudge?: (axis: number, deltaMm: number) => void; // undefined = read-only (Print/Job views): render no buttons
nudgeStepMm?: number;                              // default 1
enabled?: boolean;                                 // default true; false = greyed, non-interactive
```
  - When `onNudge` is provided, render an in-SVG control cluster as a real, accessible control:
    each button is a `<g class="el-nudge" role="button" tabIndex={0} aria-label="feed piston up 1 mm">`
    wrapping a `<rect>` hit-target + a glyph (`▲`/`▼` for pistons, `◀`/`▶` for the recoater), with
    `onClick`/`onKeyDown`(Enter/Space) → `onNudge(axis, delta)`.
  - **Pistons** (build axis 1, feed axis 2): a **▲** just ABOVE the piston rect → `onNudge(axis, -nudgeStepMm)` (up/flush = negative mm), and a **▼** just BELOW → `onNudge(axis, +nudgeStepMm)` (down/open cavity = positive mm). Place them at `x = r.x + r.w/2` using the existing `r` geometry.
  - **Recoater** (axis 4): a **◀** and **▶** flanking the recoater carriage → `onNudge(4, -nudgeStepMm*?)` toward home / away. Use a larger recoater step (see Step 2). Place at the carriage's `gantryX(4, rc)`.
  - When `enabled === false`, render the clusters greyed and ignore clicks (mirror the disabled look). Do NOT render clusters at all when `onNudge` is undefined — Print/Job/Runs keep the read-only diagram exactly as-is.
  - Keep everything else in `Elevation` unchanged (markers, arrows from Task 3, legend, heater).

- [ ] **Step 2 — Style** in `styles.css` (tokens only, no literals): `.el-nudge rect` = a subtle hit target (`fill: var(--panel); stroke: var(--line-control);` small radius) with a `:hover`/`:focus-visible` accent (`stroke: var(--accent)`); `.el-nudge text` = `fill: var(--fg); font: var(--font-mono);` centered; `.el-nudge[aria-disabled="true"]` = `opacity:.35; pointer-events:none;`. Give the cluster a comfortable tap size.

- [ ] **Step 3 — Verify** — `cd frontend && npm run build` (tsc clean + vite) + `npm test` (whole suite green, incl. theme no-literal check). Coordinator browser check: ▲/▼ appear at each piston and ◀/▶ at the recoater in the Priming view; clicking issues a bounded move; Print/Job diagrams show NO buttons.

- [ ] **Step 4 — Commit** — `feat(diagram): on-diagram piston ▲/▼ + recoater ◀/▶ nudge controls` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

**PrimingView wires it** (in Task 5): `<Elevation ... onNudge={(axis, d) => call("nudge", () => api.move(axis, "rel", d))} enabled={ok} nudgeStepMm={step} />`, where `step` is an operator-chosen nudge size (a small selector: 0.5 / 1 / 5 mm). The recoater arrows may use a coarser step internally (e.g. `step*20`) since the gantry travels ~972 mm — implement that scaling inside `Elevation`'s recoater handler or pass a separate `recoaterStepMm`; keep it simple and documented.

## Task 5: Rebuild `PrimingView` as the stepped walkthrough

**Files:** Modify `frontend/src/components/views/PrimingView.tsx`; reuse `usePriming`/`PrimingFields` (`PrimingPanel.tsx`), `powder.ts`, `ControlStrip.tsx`, `Elevation.tsx`, `primingSteps`.

- [ ] **Step 1** — Rebuild `PrimingView` as a full-page layout: a **stepper column** (the 6 steps) + a persistent **live `Elevation` (mode="live")** centerpiece + the **`ControlStrip`**. Keep the existing props `{ status, gates, call }` and `usePriming(call)`; keep `ok = gates.controllable && !gates.printActive`, `r = status?.print`, `paused`, etc.

  **Amount step (Step 1 of the flow):** local state `source: "job"|"layers"|"depth"`, `marginMm`, `nLayers`, `layerThicknessMm`, `manualDepthMm`. On mount / when source==="job", fetch `api.printSettings()` once and read `total_thickness_mm`. Compute `depth = fillDepthMm({...})` and `pct = cavityFillPct(depth)`. Show the source picker, the relevant inputs, the resulting **fill depth (mm)** and a **fill gauge** (`pct`% of 145 mm feed travel — reuse the `.bar`/`.bar i` classes). A **“Set as feed cavity”** button calls the existing `save` path to PUT `{ feed_cavity_mm: depth }` (extend `usePriming.save` or call `api.setPriming({ feed_cavity_mm: depth })` then refresh). Show a reminder under "layers": “include the precoat layers (runway + part-piston fill)”.

  **Position steps (build up / open cavity):** each step shows its target (from saved settings: `part_top_mm`, `feed_cavity_mm`) and a **“Run this step”** button that issues that one move via `api.move` (build → `api.move(1,"abs",part_top_mm)`; feed → `api.move(2,"abs",feed_cavity_mm)`), gated by `ok`. Show the live diagram; the moving piston will blink its arrow (Task 3).

  **Load powder (HOLD) step:** instruction to pour powder into the open cavity; a **“Powder loaded — next”** button advances the stepper (this is a manual gate, no motor move). (If a macro run is in progress and `paused`, also surface the existing `api.printResume` "resume" — keep that path working.)

  **Level step:** a **“Spread”** button (recoater → `level_recoat_end_mm`) and **“Return”** (→ `level_recoat_start_mm`) — **operator-repeatable**: they press Spread/Return as many times as needed until level (per the approved design; NOT a fixed pass count). The `ControlStrip` recoater buttons cover this too.

  **Ready step:** a **"Bed is primed — finish"** button calls `api.primedCapture()`
  (`POST /api/primed/capture`, added in Task 7a) which snapshots the controller's live piston
  positions server-side as the print's starting positions; show the captured part/feed positions +
  `captured_at` on success, and a hint that the Print tab now uses these as its start. Summary + link
  to Print. (Do NOT send client-side position numbers — the endpoint reads them from the controller.)

  Track the active step in local state (`const [step, setStep] = useState(0)`), with Back/Next between steps and each step’s primary action. Keep **RUN PRIMING (auto)** and **ABORT** available (the existing `api.primingRun` macro as an "auto-run everything" escape hatch, `api.printAbort`).

- [ ] **Step 2 — Verify** — `npm run build` clean + `npm test` green (48+; theme invariant holds). Coordinator browser check against `vpi-serve --backend simulated`: the Priming tab is a stepped walkthrough; the Amount step computes a fill depth from job/manual and sets the feed cavity; each position step runs its move on click; the level step spreads repeatably; the diagram shows live motion + blinking piston arrows; the ControlStrip nudges work.

- [ ] **Step 3 — Commit** — `feat(priming): stepped powder-loading + leveling walkthrough` + trailer.

## Task 6: Styles + COVERAGE + polish

**Files:** `frontend/src/styles.css` (walkthrough/stepper classes, tokens only), `docs/superpowers/COVERAGE.md`.

- [ ] **Step 1** — Style the stepper (`.priming-page`, `.stepper`, `.step-item`, active/done states) with the re-skin tokens filling the page; no horizontal overflow; the diagram stays the visual centerpiece. Verify the Amount fill-gauge and ControlStrip read cleanly at narrow + wide widths.
- [ ] **Step 2** — Update `COVERAGE.md`: mark spec §6 as the walkthrough (this plan), and add a Plan 5 row; note the deferred grams/volume + computed-depth-from-part-volume as calibration hooks.
- [ ] **Step 3 — Verify** — `npm run build` clean + `npm test` green.
- [ ] **Step 4 — Commit** — `style(priming): walkthrough/stepper layout + COVERAGE` + trailer.

## Task 7a: `PrimedState` store + capture/get API (backend, TDD)

**Files:** Create `backend/vention_printer_interface/control/primed_state.py`, `.../tests/test_primed_state.py`; modify `backend/vention_printer_interface/api/app.py` + a test `.../tests/test_api_primed.py`. Follow the existing `priming_store.py` / `test_api_priming.py` patterns (READ them first).

- [ ] **Step 1 (RED)** — `test_primed_state.py`: a `PrimedState` frozen dataclass with `part_mm: float`, `feed_mm: float`, `captured_at: float`; `save_primed(root, state)` then `load_primed(root)` round-trips; `load_primed` on an empty root returns `None`. Write the test, run `uv run pytest .../test_primed_state.py`, SEE it fail (module missing).
- [ ] **Step 2 (GREEN)** — implement `primed_state.py` (dataclass + JSON save/load under the same data root the priming store uses). Run the test → pass.
- [ ] **Step 3 (RED)** — `test_api_primed.py` (mirror `test_api_priming.py`'s app fixture): `POST /api/primed/capture` on a connected simulated controller returns `{part_mm, feed_mm, captured_at}` read from the controller's live telemetry positions (axis 1 = part, axis 2 = feed) and persists them; `GET /api/primed` returns the saved state (or `{"primed": null}` when none). Add a test that capture with no controller/telemetry returns a clear 409. Run → fail.
- [ ] **Step 4 (GREEN)** — add the routes to `app.py`: `capture_primed()` reads `ctrl().status()`/telemetry positions server-side (do NOT accept positions from the request body), builds `PrimedState`, `save_primed(...)`, returns it; `get_primed()` returns the stored state or `{"primed": null}`. Wire `app.state.primed = load_primed(root)` at startup like priming. Run → pass.
- [ ] **Step 5** — full suite `uv run pytest` + `ruff check` + `mypy` clean (per repo config). Frontend: add `api.primedCapture()` / `api.primed()` to `src/lib/api.ts` (`req("POST","/api/primed/capture")`, `req("GET","/api/primed")`) — build stays green.
- [ ] **Step 6 — Commit** — `feat(primed): capture primed piston positions (server-side snapshot) + API` + trailer.

## Task 7b: `compile_print` primed setup + require-primed guard (backend, TDD)

**Files:** Modify `backend/vention_printer_interface/control/print_settings.py` (`compile_print`) + `.../tests/test_print_settings.py`; modify the print run guard in `api/app.py` + `test_api*.py`. READ `compile_print` (setup lines ~295-301) and the existing print-settings tests first — several assert the current setup order (home_all, feed→feed_end); those assertions must be UPDATED to the primed setup, not left stale.

- [ ] **Step 1 (RED)** — in `test_print_settings.py`, replace/adjust the setup-order assertions to the PRIMED setup and add a test: the first steps of `compile_print(plan)` **home the printhead and recoater only** (per-axis `home` for axes 3 and 4), and contain **no `home_all`** and **no piston (`FEED`/`PART`) move in setup** — the pistons start where priming left them. Run → fail (current compiler still emits `home_all` + feed→feed_end).
- [ ] **Step 2 (GREEN)** — change `compile_print`'s setup block: emit `home` for `PRINTHEAD` then `home` for `RECOATER` (each + `wait`), and DELETE the `home_all` and the `set_speed/set_accel/move_abs FEED → feed_end` setup steps. Leave the per-phase layer loops unchanged. Run → the whole `test_print_settings.py` green (fix any other assertions that counted setup steps — e.g. `estimate_duration_s` expectations, total step counts). 
- [ ] **Step 3 (RED)** — print-run guard test: `POST /api/print/run` (or the existing start route) returns **409 "prime the bed first"** when `load_primed(root)` is `None`, and proceeds when a `PrimedState` exists. Run → fail.
- [ ] **Step 4 (GREEN)** — in the print start handler, refuse with 409 when `app.state.primed` is `None`; otherwise proceed. Run → pass.
- [ ] **Step 5** — full `uv run pytest` + ruff + mypy clean; note that `estimate_duration_s` and any step-count-dependent tests were updated. Frontend: the Print/Job view's start button should surface the 409 message ("prime the bed first") via the existing `call`/error path — no new UI needed, but confirm the error text reaches the banner.
- [ ] **Step 6 — Commit** — `feat(print): primed start — home gantries only, require a primed bed (no piston home)` + trailer.

> **Coupling note:** Task 7b changes the print's step list, so the frontend recipe mirror / any test asserting the compiled print's setup (e.g. `estimate.ts`, a step-count test) must be updated in the same task. Grep for `home_all` and `feed_end` across `frontend/src` and reconcile.

---

## Self-review notes
- **Spec coverage:** Amount calc (Task 1), manual/job sources incl. thick precoats (Task 1 `fillDepthMm` job uses `total_thickness_mm` which already includes thick_precoat), bounded controls (Task 4), operator-triggered moves + repeatable level (Task 5), blinking piston arrows (Tasks 2–3), full-page live diagram (Task 5, baseline already full-page). Grams/computed-depth explicitly deferred (spec non-goals) — documented seam in `powder.ts`.
- **No backend change:** the walkthrough reuses `api.move` / `api.setPriming` / `api.printSettings`; the piston sign convention and compiler are untouched. This is deliberate (the design chose operator-triggered discrete moves), avoiding a per-step engine.
- **Type consistency:** `fillDepthMm`/`cavityFillPct`/`pistonArrow` signatures are fixed in Tasks 1–2 and consumed unchanged in Tasks 3/5. `FEED=2/PART=1/RECOATER=4` match `print_settings.py`.
- **Invariant:** every task keeps `styles.css` tokens-only; `theme.test.ts` stays green.
