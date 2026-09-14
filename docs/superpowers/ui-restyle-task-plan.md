# UI Restyle — Task Plan (improve the REAL app in place)

## Goal
Improve the real React app's readability + add polish, KEEPING its liked grouping/styling.
Base = the real app (not the mockup). Verify each slice live at http://localhost:5175.

## Decisions (locked)
- App name → **RFAM Binder Jet** (literal; ties to lab + process). Wordmark replaces "BINDER JET CONSOLE".
- Primary tab group [Job · Priming · Print] label → **Build** (grouped + accent-active). Control · Runs · Cameras separate.
- KEEP the real module grouping (Gantries / Pistons / Motion / Heater / Controller on Control, etc.) — user likes it.
- Booleans → **toggle switch** whose position IS the state. NO "checkbox + ON/OFF" text (confusing).
- Print → state-aware (idle/printing × job/manual); routine params → collapsible drawer. (later slice)
- Add: light theme, resizable+snapping dock, ribbon (later slices).
- Readability: fix `.tune` spread, measure-cap kv rows, size-to-content buttons.

## Phases
- [ ] **Slice 1 (now)**: wordmark rename; grouped "Build" tabs; Toggle component + CSS; replace confusing heater/postcoat checkboxes in Job/Print/Routine. Build + verify live.
- [ ] Slice 2: Control readability (tune rows, button sizing) — keep grouping.
- [ ] Slice 3: RoutinePanel → grouped cards w/ proper packing + toggles + drawer.
- [ ] Slice 4: Print state-aware (command strip + state bodies + routine drawer).
- [ ] Slice 5: light theme tokens + toggle in header.
- [ ] Slice 6: dock (resizable machine monitor) + ribbon.
- [ ] Slice 7: Job / Priming / Runs / Cameras polish pass.
- [ ] Final: full verification (pytest, node --test, tsc+vite build), review, merge.

## Verification gate
UI is not unit-testable → gate = `npm run build` (tsc+vite) clean + live browser check at :5175. lib/*.ts changes keep node --test green.

## Status
Slice 1 in progress.
