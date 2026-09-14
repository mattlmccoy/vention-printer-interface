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
- [x] **Slice 1**: wordmark → VENTION PRINTER INTERFACE; grouped "Build" tabs; Toggle component; replace confusing heater/postcoat checkboxes. (commit 1d42734; wordmark finalized in slice 2/3 commit)
- [x] Slice 2: Control readability — tune rows pack left; cards size to content height (no tall-empty modules). Grouping kept.
- [x] Slice 3: RoutinePanel → grouped cards (powder handling / multipass / heat / nozzle purge / carbon&exposure) + toggles.
- [x] Slice 5: light theme — :root[data-theme=light] override + header ☀/☾ toggle (commit 1ac7eb6).
- [x] Slice 6: persistent resizable machine dock (Elevation + axis chips + overview + heater/health +
      pause/abort); shell .bodywrap; deduped ControlView overview (commit 549132b).
- [ ] Slice 4: Print state-aware (command strip + state bodies + routine drawer); dedupe Print's
      machine module + overview into the dock (do the Print dedupe here).
- [ ] Slice 7: Priming / Runs / Setup(Cameras) polish to match the approved mockup designs
      (user loved them). Runs rich page needs backend: per-run zip endpoint + motion_profiles.csv.
- [ ] Final: full verification (pytest, node --test, tsc+vite build), review, merge to main.

## Verified this session
Fixed a wedged vite dev server (was 503-ing, serving stale JS). Restarted clean on :5175.
Dock renders across views; Control deduped + grouped + dock all render correctly live.

## Verification gate
UI is not unit-testable → gate = `npm run build` (tsc+vite) clean + live browser check at :5175. lib/*.ts changes keep node --test green.

## Status
Slice 1 in progress.
