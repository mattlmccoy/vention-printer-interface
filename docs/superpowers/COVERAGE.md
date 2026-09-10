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

## Roadmap (reprioritized 2026-09-09 per user: visual redesign ahead of preview/hosting)

1. **Plan 3 — Print routine** — ✅ merged & deployed (`5c479e4`).
2. **Plan 4 — UX / visual redesign** — 🔨 IN PROGRESS. Full re-skin to the mockup + module space-fill + Control overflow fix + **Priming full-page with the live diagram** + **active-vs-model movement distinction** (live solid / model violet ghost).
3. **Plan 5 — Digital move-preview animation** (spec §4): play the compiled steps through the diagram before big moves; drives the model layer Plan 4 establishes.
4. **Plan 6 — Hosting + e-stop reset probe + wireframe** (spec §10): GH Pages serving localhost like FLIR/T&C; investigate an HTTP e-stop reset route; revisit the wireframe with proper image registration.

## How loss is prevented now
- This file is the single source of truth for "what's left / what's lost."
- Plan self-review must reverse-check: walk every spec § and confirm an owner here (not just "does this plan cover its section").
- "Named but unwritten" plans (🗒️) are explicitly flagged as at-risk until their plan doc exists.
