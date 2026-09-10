# UX / Visual Redesign — Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Most tasks here are CSS/layout (not unit-testable) — the verification gate is a **tsc-clean `npm run build` + a browser check**, per the TDD-substitution rule.

**Goal:** Re-skin the whole console to the approved mockup's calm, high-contrast, readable look; make the draggable/resizable modules fill their space instead of leaving dead gaps; fix cramped/overflowing controls (the Control speed/accel row); turn the **Priming page into a real full page** with the live machine diagram; and establish a clear **active-vs-model movement** visual distinction (live = solid, model/preview = ghost).

**Architecture:** A shared token layer in `styles.css` drives the palette/type/spacing (light+dark aware). `Modules.tsx` (the ModuleGrid) gains real space-filling. Views get layout passes. The diagram (`Elevation.tsx`) gains a `mode: "live" | "model"` rendering distinction that the priming page uses now and the Plan 5 preview animation will drive later.

**Tech Stack:** Vite + React + TS. Reference: the approved **Binder Jet Console mockup** artifact (the design contract) + spec §3/§5/§6/§10 (readability).

Branch: `redesign/ux-visual`. Design tokens (from the mockup): ground `#0a0e14`, panel `#111823`, hairline `#212b38`, ink `#dce3ec`, dim `#98a5b3`, label `#adb9c6`; amber `#ffb454`, live-green `#5cff8a`, recoater-blue `#5cc8ff`, **model/preview violet `#b98cff`**, danger `#ff5f56`. Fonts IBM Plex Sans (UI) + IBM Plex Mono (data). Base 15px, line-height 1.5.

---

## Task 1: Shared visual token system (the re-skin foundation)

**Files:** `frontend/src/styles.css` (READ first — it holds the current theme).

- [ ] **Step 1** — Introduce/repoint CSS custom properties to the mockup tokens above at `:root`, keeping the app's existing class names but routing their colors/sizes through the tokens: bump base font to 15px / line-height 1.5, raise text contrast (ink `#dce3ec`, dim `#98a5b3`), enlarge uppercase mono labels to ~12px with `letter-spacing:.09em` and a lighter label color, and set a consistent panel/hairline/radius scale. Do NOT restructure components — only the shared style layer.
- [ ] **Step 2** — Verify readability at rest: `cd frontend && npm run build` (tsc clean); browser check against `--backend simulated` — text is legibly higher-contrast, labels larger, on every page. (Caller does the browser check.)
- [ ] **Step 3: Commit** — `style: re-skin shared tokens to the mockup (contrast, type scale, palette)` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Task 2: Module grid fills the space

**Files:** `frontend/src/components/Modules.tsx` (READ first — it renders the draggable/resizable module grid), and its styles in `styles.css`.

- [ ] **Step 1** — Make the grid responsive and space-filling: columns sized to fill the available width (e.g. `grid-template-columns: repeat(auto-fill, minmax(<min>, 1fr))` or a flex layout that grows), modules stretch to fill their track rather than sitting at a fixed small size with dead gaps, and a module set to size `m`/`l` spans proportionally. Preserve drag-reorder + the resize handle behavior (`onOrder`/`onResize`) and per-view size persistence. Ensure a `.module` grows to fill and its body scrolls internally (`overflow:auto`) rather than overflowing the page.
- [ ] **Step 2** — Verify: `npm run build` clean; browser — modules fill the viewport width with no large empty gaps; drag + resize still work.
- [ ] **Step 3: Commit** — `feat(layout): module grid fills available space (no dead gaps)`.

## Task 3: Fix the Control speed/accel overflow

**Files:** `frontend/src/components/views/ControlView.tsx` (the per-axis `.tune` row) + relevant styles.

- [ ] **Step 1** — The per-axis speed/accel row currently overflows/looks cramped. Rework it so it fits cleanly: a tidy 2-line grid (`spd [input] set  ≤cap` / `acc [input] set  ≤cap`) or a compact wrap that never overflows the module, with inputs sized to content and the `≤ cap` hints not colliding. Keep the same behavior (`api.setAxisMotion`). Ensure the axis block never causes horizontal overflow at the module's min width.
- [ ] **Step 2** — Verify: `npm run build` clean + full lib suite; browser — Control gantries/pistons: speed/accel inputs and caps lay out cleanly at narrow and wide module widths, no overflow.
- [ ] **Step 3: Commit** — `fix(control): clean speed/accel input layout (no overflow)`.

## Task 4: Active-vs-model movement distinction in the diagram

**Files:** `frontend/src/components/Elevation.tsx` (+ tiny pure helper `frontend/src/lib/diagram.ts` + `diagram.test.ts`).

- [ ] **Step 1: Failing test** `frontend/src/lib/diagram.ts` gets a pure `markerStyle(mode, moving)` → class/color mapping; `diagram.test.ts`:
```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { markerClass } from "./diagram.ts";
test("live vs model marker classes", () => {
  assert.equal(markerClass("live", false), "mk-live");
  assert.equal(markerClass("live", true), "mk-live mk-moving");
  assert.equal(markerClass("model", false), "mk-model");
});
```
- [ ] **Step 2** — implement `markerClass(mode: "live" | "model", moving: boolean): string` returning `"mk-live"`/`"mk-live mk-moving"`/`"mk-model"`; run test green.
- [ ] **Step 3** — In `Elevation.tsx`, accept a `mode: "live" | "model" = "live"` prop; render axis markers via `markerClass`. Style in `styles.css`: `.mk-live` = solid axis color; `.mk-live.mk-moving` = brighter + a subtle pulse (respect `prefers-reduced-motion`); `.mk-model` = violet `#b98cff`, dashed outline, semi-transparent. Add a small legend ("● live · ◍ model") and a state badge. `moving` comes from telemetry `motion_complete[axis] === false`.
- [ ] **Step 4** — Verify: `node --experimental-strip-types --test src/lib/diagram.test.ts` (pass) + `npm run build` clean; browser — a moving axis reads as live+pulsing; passing `mode="model"` renders ghost violet markers.
- [ ] **Step 5: Commit** — `feat(diagram): live vs model movement distinction (solid vs violet ghost)`.

## Task 5: Priming as a real full page

**Files:** `frontend/src/components/views/PrimingView.tsx` (rework from the single-module wrapper), reusing `PrimingPanel.tsx` and `Elevation.tsx`.

- [ ] **Step 1** — Rebuild `PrimingView` as a full-page 3-region layout that fills the page (not one small module): **left** — the priming params + the plain-language "what this will do" sequence (from `primingSteps`); **center** — the **live machine diagram** (`<Elevation status=... mode="live" />`) showing the pistons/recoater as the routine runs, with the legend; **right** — run controls (RUN · RESUME · ABORT) + status (state, current step, hold prompt). Use the re-skinned tokens. It must fill the viewport width/height with the diagram as the visual centerpiece.
- [ ] **Step 2** — Verify: `npm run build` clean + full lib suite; browser — the Priming tab is a full page with a large live diagram, params on one side, run controls on the other; running priming shows the pistons/recoater moving live.
- [ ] **Step 3: Commit** — `feat(priming): full-page layout with the live machine diagram`.

## Task 6: Apply the re-skin across Print / Job / Runs

**Files:** `frontend/src/components/views/PrintView.tsx`, `JobView.tsx`, `RunsView.tsx`, `RoutinePanel.tsx`, `StatusBar.tsx` — styling/layout only.

- [ ] **Step 1** — Pass over each remaining view so it uses the re-skinned tokens, fills its space (Task 2's grid), and reads cleanly at the new contrast/type scale. Fix any remaining overflow/cramping (e.g. RoutinePanel field rows, the RunsView tables, the StatusBar). Also resolve the `JobView.tsx` `// TODO Task 3` (draw `thin_precoat` in the powder-stack bar) if trivial. No behavior changes.
- [ ] **Step 2** — Verify: `npm run build` clean + full lib suite; browser — Print/Job/Runs match the mockup's look and fill space; no overflow anywhere.
- [ ] **Step 3: Commit** — `style: apply the re-skin + space-fill to Print/Job/Runs/StatusBar`.

---

## Self-review notes
- Covers spec §10 readability + the user's asks (full re-skin, module space-fill, Control overflow, Priming full-page + live diagram, active-vs-model distinction).
- The **model-movement ANIMATION** (playing a dry-run through the diagram) is Plan 5 (digital preview); Task 4 here establishes the `mode="model"` visual layer it will drive, and Task 5 shows the live view now.
- Verification is build + browser (CSS/layout is not unit-testable); the one pure helper (`markerClass`) is TDD'd. The caller (coordinator) does the browser checks and shows the user before merge.
