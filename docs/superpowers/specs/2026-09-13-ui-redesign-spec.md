# Operator Console UI Redesign — Design Spec

**Date:** 2026-09-13
**Status:** Draft (mockups approved in direction; spec drives the rebuild)
**Scope:** Full visual + layout + workflow overhaul of the Vention binder-jet operator console. No loss of existing functionality. Backend behavior unchanged except where noted (camera on-demand already merged).

Mockups: detailed screens `94ba7d61`, layout study `f997cdbc`, visual directions `5895d399`.

## 1. Goals
- Logical, **technically dense but usable**, with a flow that makes sense.
- Reclaim wasted space; nothing sprawls on a wide (1900–2560px) monitor.
- Preserve every current feature (see §9 inventory).
- Support **dark (default) + light** themes.

## 2. Design system (Instrument)
**Type:** UI text in a humanist sans (system stack: `-apple-system, "Segoe UI", Roboto, sans-serif`). **Monospace only for numeric telemetry / values** (`ui-monospace, "SF Mono", Menlo`), `font-variant-numeric: tabular-nums`. Scale: page-title 18–20/600, section-label 10.5px/700 uppercase tracked (.11em) used sparingly, body 13.5–14, numeric 14–16 mono. `text-wrap: balance` on headings.

**Color tokens** (define light on `:root`; dark under `@media (prefers-color-scheme: dark):root:not([data-theme=light])` and `:root[data-theme=dark]`; light under `:root[data-theme=light]`; body sets an explicit background):
- Dark: bg `#0e1116`, surface `#161b22`, surface-2 `#1c232d`, surface-3 `#222b36`, border `#2a323d`, text `#e6edf3`, dim `#9aa7b3`, faint `#6b7681`, accent `#f0a92b`, accent-ink `#1b1200`, ok `#3fb950`, warn `#d29922`, fault `#f85149`, pip `#05070a`.
- Light: bg `#f6f8fb`, surface `#fff`, surface-2 `#eef1f4`, surface-3 `#e6eaee`, border `#d5dbe1`, text `#1b2229`, dim `#5b6672`, faint `#8a94a0`, accent `#b9761c`, ok `#1a7f37`, warn `#9a6700`, fault `#cf222e`, pip `#0e1116`.
- Axis colors (consistent everywhere): build = ok/green, feed = accent/amber, printhead = fault/red, recoater = `#58a6ff` blue. Semantic (ok/warn/fault) is separate from accent.

**Spacing/shape:** 8px grid; radius 10px (cards) / 6–7px (controls); border 1px; subtle shadow (dark: low-alpha; light: soft). One `Panel` component: header (uppercase micro-label + optional action) + body (16px pad).

## 3. Layout rules (the two hard rules)
1. **Measure cap.** Prose, key/value rows, and forms live in a **capped column (~640–760px)** — never stretched full-viewport. Wide panels use **internal columns**, not one full-width label↔value pair.
2. **Size to content + cap sections.** Controls (buttons, inputs) size to their content — **never stretch a button edge-to-edge across a wide card** (use flex/auto width, not `1fr`). Sections are **width-capped and left-aligned** (e.g. axis grid = 2×~420px capped ~864px); leftover space is intentional margin. Full-width is reserved for **primary/danger actions only** (STOP, Pause/Abort, Start).
- Visual content (machine schematic, camera, chips, filmstrips, charts) MAY use full width.
- Responsive: relative units, flex/grid + gap; wide content scrolls in its own `overflow-x:auto`; body never scrolls sideways.

## 4. Shell (tabbed + pop-out machine dock)
- **Top bar (~52px):** brand ▸ **Workflow group** [Job · Priming · Print] (visually grouped, accent-active) ▸ secondary tabs [Control · Runs · Setup] ▸ spacer ▸ connect pill ▸ theme toggle ▸ **E-STOP** (red, always visible).
- **Pop-out machine dock (right, ~320px, toggleable + RESIZABLE):** the persistent **monitor** — machine schematic with **drag-to-jog** (draggable gantries/pistons, constrained to travel, snap to jog step/speed, gated armed & not-printing), 4 axis chips (live mm), **overview PIP (on-demand)**, heater + health mini, Pause/Abort during a print. Toggling it OFF **releases** the overview camera. Dock has a left-edge drag handle that **snaps to preset widths** (~288/322/400/460, min 262 / max 540). Page main area = the **task**; the **Control page** is the exception — it shows a larger live machine schematic + overview inline (drag-to-jog surface), since manual jogging is its whole purpose.
- **Alert ribbon (shell chrome, always present):** a persistent full-width strip **between top bar and body** for warnings/faults (NOT-HOMED, spill, limits). Because it's a fixed shell row, alerts appearing/clearing **never reflow page content** — this replaces the old in-page banners that pushed everything down. Level-colored (ok/warn/fault); horizontally scrolls if multiple; acknowledge collapses to "all clear".
- **Control page jog:** step size is a **segmented preset selector** (not a free-text input) on **every** axis — gantries e.g. 0.1/1/10/50 mm, pistons 0.01/0.05/0.1/1 mm.
- **Status bar (bottom):** operator / controller / e-stop / drives / heater; version at right.

## 5. Page layouts
Each page's main = its task; the dock is the live monitor.

**Print (Layout B):** main = imaging left (CAD-slice vs captured compare: side-by-side + overlay/diff, stage selector pre/**post_jet**/post_heat, layer scrub, Δ metrics, recent-layers filmstrip) | narrow right column (This-print progress + **grouped routine-params cards**, always visible). Advanced: dry-run / single-step / seek. Source toggle job/manual.

**Routine parameters — ground truth is `frontend/src/components/RoutinePanel.tsx` (do not invent/rename).** Real editable fields, grouped for the redesign:
- *Powder handling*: `thin_precoat` (n_layers × layer_thickness_mm, feed_thickness_mm), `printing_feed_thickness_mm` (feed/layer), `recoater_return_mm`, `feed_backlash_mm` (anti-backlash), `postcoat_enabled`. (Thick precoats live in the **Priming** routine, not here.)
- *Multipass*: `n_jet_passes` = **"passes / layer" (multipass language)**, `printhead_multipass_return_mm` ("multipass return"), `printhead_start_mm` = printhead park position before layer 1 (needs the explainer — users don't know the term).
- *Heat*: `heater_start_mm`, `heater_speed` (manual sweep-speed override), `pre_heater_drop_mm`.
- *Nozzle purge*: purge **position** (mm) + `purge_dwell_s` + `purge_mode` segmented (every pass / per layer / every N) + `purge_every_n_layers` (N). Keep the existing per-layer/per-N selector.
- *Finish*: `part_max_mm` = **absolute** part drop-to position (move_abs in compile_print:526, "spill-safe depth") — a POSITION, never a relative move.
- *Carbon & exposure*: `target_carbon_wt`, `part_area_mm2`, `heater_section_power_w`, + read-only IPA exposure (energy J / dwell s / sweep mm/s).
- *Layer capture* (vision, new via `capture_stages`): pre-jet / post-jet / post-heat stills.
Optional explainers (ⓘ) on non-obvious fields. "Set routine" saves via `api.setPrintSettings`.

**Control (Layout B):** main = one **card per axis** (printhead / recoater / build / feed), each with jog (home/away or up/down, buttons content-sized) + speed/accel + go-to; then an ops row (Motion: home PH/RC + STOP; Heater on/off + relay/watchdog; Controller: drives/health/e-stop). Live positions read from the dock.

**Job:** choose-job strip + manual-print toggle; then **Job→Motion** summary (layers, slicer layer height, part height, footprint, print_settings, MetPrint note) + **Powder Stack** (stacked precoat/print/postcoat viz + mm-of-travel/layers/heater; inputs: precoat count×mm, postcoat on/mm, layer-height presets, heater on/passes; printable indicator) → Send to priming / Go to print.

**Priming:** guided **6-step stepper** (Amount → Build up → Open feed → Load powder(hold) → Thick precoats → Finish→capture&go-to-Print); current step content in a capped column; Run priming (automatic) / Abort; dock shows the machine you're loading.

**Runs:** run list (left) + run detail (right): summary chips, **⬇ Download run (.zip)** = everything (raw+registered stills + sidecars, telemetry.csv, **motion_profiles.csv**, events, manifest, calibration), science-cam stills grid (layer × stage), motor **velocity/accel profile** chart, zip-contents list.

**Setup & Calibration:** guided stepper (Connect → Identify/assign roles → Camera settings [res/fps/format/exposure per camera] → Generate & print board → Calibrate intrinsics → Set bed plane → Validate → Done). Camera-permission surfacing + Rescan; board download (ChArUco/checkerboard SVG/DXF); validation (checkerboard default 17×17 / 4.5 mm, ±0.1 mm gate). Reopenable from Settings anytime.

## 6. Components
Panel; grouped-param card (`<h4>` accent label + `label:input` rows, input mono right-aligned ~92px); chip (uppercase micro-label + mono number); kv row (capped width); button (content-sized; `.wide` only for primary/danger); segmented control; frame/compare (pip bg, mm labels); stepper rail; dock. All theme-token-driven.

## 7. Camera behavior (on-demand — merged to main `94b5471`)
Nothing opens at startup. Overview = viewer-ref-counted (opens on first viewer, releases ~2.5s after last). Science = open per-capture then close. `POST /api/vision/deactivate` force-releases. Setup surfaces macOS permission state + Rescan. Per-camera settings persisted per role (ELP AR2020 defaults; camera-agnostic UVC; C920 is a test stand-in).

## 8. Data / Runs
Recorder already writes per-run dir with telemetry.csv + events + manifest + nested `vision/`. Add **motion_profiles.csv** (commanded speed/accel setpoints + velocity derived from position telemetry) and a **per-run zip** endpoint + Runs UI to browse/download.

## 9. Feature inventory (nothing dropped)
Preserve: per-axis jog + speed/accel set + go-to; home PH/RC; Motion STOP; heater on/off + relay/watchdog/io; controller e-stop/drives/health; RoutinePanel (all knobs: precoats, feed, heater speed, multipass return, printhead start, feed backlash, jet passes, nozzle purge dwell/mode, build-drop-at-done); manual print + job selection/preview; priming 6-step flow + feed-cavity calc + set-as-feed-cavity + run/abort + capture→go-to-print; dry-run/single-step/seek; recording start/stop + Runs history/export; NOT-HOMED/reference banners; spill warnings; macro banners; event log; overview + science cameras; calibration + validation; board generation. **Deliberately removed:** free-form panel drag/reorder/resize → replaced by intentional designed layouts (+ collapse/show-hide, dock pop-out).

## 10. MetPrint / loop (context)
Jetting is external (MetPrint jets TIFFs from a watched hot folder). Operator-side automation = per-layer sync (#2) + provenance logging (#3) only; staging stays slicer→hot-folder. A unifying slicer↔operator↔analysis "close-the-loop" tool is a separate future initiative.

## 11. Build plan (phased, TDD where testable)
1. Design tokens + theme (dark/light) + Panel/button/chip/kv/segmented components (frontend lib logic TDD via node --test; components via `npm run build`).
2. Shell: top bar + workflow grouping + status bar + the pop-out dock (dock content wired to telemetry; drag-to-jog interaction).
3. Per-page rebuild against Layout B + rules, wiring each to the existing backend endpoints (Control, Print incl. layer compare + grouped params, Job, Priming, Setup).
4. Runs: motion_profiles.csv + per-run zip endpoint + Runs UI.
5. Full verification (backend pytest, frontend node --test + build), review, merge.
Apply the two layout rules (§3) everywhere. Pull each page into a Claude-design artifact for the user's direct feedback before/while wiring.
