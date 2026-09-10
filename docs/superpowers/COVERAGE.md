# Redesign coverage & roadmap

Living map of the redesign spec (`specs/2026-09-09-binderjet-console-redesign-design.md`) to the
plan/task that owns each requirement, so nothing falls between plans again. Update on every plan
merge. **Rule: every spec section must name an owner here; a section with owner "—" is unowned and
must be assigned before we call the redesign done.**

Legend: ✅ done & merged · 🔨 in progress · 📋 planned (plan written) · 🗒️ queued (named, plan NOT
yet written) · ⛔ was lost, now assigned · ⏸ deferred by user decision.

| Spec § | Requirement | Owner | Status |
|---|---|---|---|
| §3 | 5-page structure: **Priming its own page** | Plan 3 Task 7 | ✅ done & deployed |
| §3 | Print/Job/Control/Runs as pages | already exist | ✅ |
| §4 | Digital move-preview: **visual layer (live vs model)** | Plan 4 Task 4 | 🔨 |
| §4 | Digital move-preview: **animation playback** | Plan 5 | 🗒️ queued |
| §5 | Control cleanup: per-axis speed/accel, per-gantry homing, drop park macros | Plan 1 | ✅ |
| §6 | Priming = position-load-level setup routine | Plan 2 | ✅ |
| §7 | Print: 4 phases, multi-pass, pre-heater drop+return | Plan 3 T1–T3 | ✅ merged |
| §7 | Print page exposes all params + run controls | Plan 3 T6 | ✅ merged |
| §8 | IPA heater-exposure model + readout | Plan 3 T4–T5 | ✅ merged |
| §9 | Humanized event log | Plan 1 Task 3 | ✅ |
| §9 | Job page (minimal) | already exists | ✅ |
| §10 | printhead travel 970 | Plan 1 Task 1 | ✅ |
| §10 | connect dedupe (only reachable MM) | Plan 1 Task 2 | ✅ |
| §10 | e-stop honesty (software stop can't turn MM red) | baseline | ✅ |
| §10 | e-stop **software reset** — probe :8000 HTTP for a reset route | Plan 6 | 🗒️ queued |
| §10 | **Readability / full visual re-skin to the mockup** | **Plan 4** | 🔨 in progress (+ module space-fill, Control overflow, Priming full-page, live-vs-model) |
| §10 | GH Pages static hosting → localhost | Plan 6 | 🗒️ queued |
| §10 | Wireframe machine image | — | ⏸ built then reverted (needs image-registration work) |
| §13 | Calibration values (thick-precoat count, feed cavity, level spread, carbon wt, part area) | editable defaults shipped; physical calibration | ⏸ open by design |

## Roadmap (updated 2026-09-10 — autonomous finish run, branch `redesign/ux-visual`)

1. **Plan 3 — Print routine** — ✅ merged (`5c479e4`), later superseded by Plan 7.
2. **Plan 4 — UX / visual re-skin** — ✅ tokens→theme.css, module space-fill (`9317675`), Control overflow (`7f5cc08`), live-vs-model markers (`2dd10df`), blinking piston arrows (`8bd9363`), on-diagram nudge controls (`ff9011f`); Print/Job/Runs/StatusBar re-skin = final task in flight.
3. **Plan 5 — Priming walkthrough** — ✅ powder calc (`d912223`), pistonArrow (`bfc9440`), stepped walkthrough (`970d491`), primed-state capture API (`d3fa92c`). A stepped powder-load + level flow with on-diagram ▲/▼ + ◀/▶, job/manual feed-cavity depth, and "Bed is primed — finish" → server-side position capture.
4. **Plan 7 — Faithful print routine** — ✅ (`d4a7f30`/`5f4bc9e`/`8dc6790`). `compile_print` mirrors the async lab script (350 return, concurrent jet+retract, heater 425→600, feed-exhaustion, part→max finish, primed-start) with the user override that feed advances in printing; a print REQUIRES a primed bed (409); frontend mirror + estimate + RoutinePanel reconciled. Step-count parity verified.
5. **Hosting (GH Pages → localhost)** — ✅ ALREADY BUILT (SITE_MODE, operator.ts, vite base, backend CORS + X-VPI-Client, `.github/workflows/pages.yml`+`ci.yml`). REMAINING = deploy: create the public repo `mattlmccoy/vention-printer-interface`, push main, enable Pages, verify the live URL. `gh` is authenticated (repo+workflow scopes).
6. **Deferred**: digital move-preview ANIMATION (spec §4; Task-4 model layer exists), e-stop HTTP reset probe, wireframe image registration.

## Remaining to finish the tool
- Plan 4 Task 6 (re-skin Print/Job/Runs/StatusBar) — in flight.
- Verify end-to-end in **site mode** (site build + `vpi-serve --site-origin`, browser→localhost, exercise priming + a primed print).
- Merge `redesign/ux-visual` → main.
- Deploy to GH Pages (push + enable Pages) and confirm the live site loads + connects to a local operator.

## How loss is prevented now
- This file is the single source of truth for "what's left / what's lost."
- Plan self-review must reverse-check: walk every spec § and confirm an owner here (not just "does this plan cover its section").
- "Named but unwritten" plans (🗒️) are explicitly flagged as at-risk until their plan doc exists.
