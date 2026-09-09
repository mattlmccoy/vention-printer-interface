# Vention Printer Interface — Plan 2: recipe engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the V1.py precoat/print/postcoat loop as a pausable, resumable, abortable step machine on top of the Plan 1 controller, with layer events in the run record and a `/api/recipe*` surface.

**Architecture:** `control/recipe.py` holds a frozen `RecipePlan` (seeded from V1.py constants) with `bounded()`/`validate()` and a pure `compile_recipe(plan) -> tuple[Step, ...]` whose order is asserted against V1.py. `control/recipe_controller.py` is a feature loop in the TC-POWER shape: `RecipeController(controller)` with `start/pause/resume/abort/step/tick/snapshot`, ticked from the controller listener, one step in flight, advancing on motion-complete, per-step timeout → FAULT. The recorder gains `layers.csv`. The API exposes `/api/recipe` (GET/PUT with bounds + validation) and `/api/recipe/{start,pause,resume,abort,step}`, and folds `recipe` into the status payload.

**Tech Stack:** as Plan 1.

**Spec:** `docs/superpowers/specs/2026-09-08-vention-printer-interface-design.md` §4, §5.

---

## File structure
```
backend/vention_printer_interface/control/recipe.py            RecipePlan, PhasePlan, Step, compile_recipe, ROLE axes
backend/vention_printer_interface/control/recipe_controller.py RecipeController, RecipeState
backend/vention_printer_interface/control/recipe_store.py      load_recipe / save_recipe (.recipe.json, re-bounded on load)
backend/vention_printer_interface/recording/recorder.py        + layers.csv, record_layer()
backend/vention_printer_interface/api/app.py                   + recipe routes, status["recipe"], auto-log
backend/tests/test_recipe.py, test_recipe_controller.py, test_recipe_store.py, test_api_recipe.py, test_recorder.py (+layers)
```

Axis roles (from configuration.json / V1.py): PART=1, FEED=2, PRINTHEAD=3, RECOATER=4 (the recoater gantry carries the heater).

### Task 1: RecipePlan + compile_recipe (pure)
Tests (`tests/test_recipe.py`): defaults equal V1.py constants; `total_thickness_mm` = 5·1 + 2·10 + 5·1 = 20; `validate()` returns `[]` for defaults and a reason when total thickness > feed_end or a position exceeds travel; `bounded(limits)` clamps `feed_fast_speed=1000` (V1.py's value) to `limits.max_speed[2]`; `compile_recipe` with `n_layers=(0,1,0)` yields the exact V1.py order for one print layer: `home_all, wait, set_speed feed, set_accel feed, move_abs feed→145, wait, [8 speed/accel steps], mark layer_start, move_rel part +2, wait, move_abs recoater 930, wait, move_rel feed −2, wait, dwell 1.0, move_abs recoater 5, wait, move_abs printhead 840, wait, move_abs printhead 5, wait, set_speed recoater 50, set_accel recoater 250, heater on, move_abs recoater 600, wait, move_abs recoater 5, wait, heater off, mark layer_end`; total layers counted; steps are frozen and indexed 0..n-1; `from_dict(to_dict())` round-trips.

### Task 2: RecipeController
Tests (`tests/test_recipe_controller.py`, against `SimulatedTransport(realtime=True)` + `Controller(poll_interval_s=0.05)`): start requires armed (RuntimeError otherwise); a 1-layer recipe runs to DONE and the layer_start/layer_end events fire with `part_height_mm=2.0`; pause after the current wait then resume; abort stops motion and forces heater off; controller FAULT/disarm mid-run → ABORTED; `dry_run=True` never calls heater_on; `single_step=True` waits for `step()`; a wait step that never completes (`stall_axis=4`) → FAULT with reason "timeout" and stop_all issued; `snapshot()` shape.

### Task 3: recipe_store + recorder layers.csv
### Task 4: API routes + status + auto-log
Tests (`tests/test_api_recipe.py`): GET has `plan`, `bounds`, `validation`, `steps`; PUT re-bounds and persists; start 409 when not armed or invalid; start → status.recipe.state running → done; pause/resume/abort; auto-log opens a run on start and closes it on done/abort; `layers.csv` served.

### Task 5: docs/recipe.md + README rows + plan update
