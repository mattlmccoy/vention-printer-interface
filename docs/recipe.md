# Recipe engine

The recipe is the lab's print script (`vention/python/V1.py`) turned into data plus a step machine.

## Plan (`control/recipe.py`)
`RecipePlan` (frozen) = three `PhasePlan`s (`precoat`, `printing`, `postcoat`: layer thickness,
layer count, per-axis speed/accel) + positions (`feed_end_mm` 145, `recoater_home/end` 5/930,
`heater_home/end` 5/600, `printhead_home/end` 5/840), heater pass settings, `heater_enabled`
(default **off** — V1.py never switched the heater), `settle_s` (V1.py's `time.sleep(1)`), and
the feed piston's setup speed (V1.py used 1000 mm/s; here bounded to the feed axis limit).
`RecipePlan.bounded(data, limits)` clamps every field into the safety limits (tighten-only);
`validate()` reproduces the V1.py printability check (total thickness ≤ feed travel) and checks
every position against axis travel.

## Compiler
`compile_recipe(plan)` → tuple of `Step(index, phase, layer, kind, axis, value, label,
part_height_mm)` in exactly V1.py order (unit-tested against the script):
setup (home all → feed piston to `feed_end`), then per phase: 8 speed/accel steps, then per layer
`mark layer_start` → part piston down → recoater out → feed piston up → dwell → recoater home →
[printing only: printhead out and back → heater speed → heater on? → N×(recoater to heater_end
and back) → heater off?] → `mark layer_end`. Print layers after the first re-assert the recoater
speed at the top of the layer, as V1.py does.

## Step machine (`control/recipe_controller.py`)
States: idle → running ⇄ paused → done | aborted | fault. Ticked from the Controller listener:
non-blocking steps go out back to back; a `wait` completes when every axis reports motion
complete AND `min_wait_s` (0.5 s) has passed since the move was issued; a `dwell` completes on
time; a wait longer than `step_timeout_s` (120 s) is a FAULT (stop all, heater off). Controller
FAULT or disarm aborts the recipe. `dry_run` skips heater steps; `single_step` pauses after every
blocking step until `step()`. Heater steps go through the ARM-gated `Controller.heater_on/off`.

## API
`GET/PUT /api/recipe` (plan + `bounds` + `validation` + `n_steps`), `POST /api/recipe/start
{dry_run, single_step, name, notes}` (409 if not armed or invalid), `pause`, `resume`, `step`,
`abort`. `status.recipe` = the step-machine snapshot. With `auto-log` on (default) a run is
opened on start and closed on done/abort/fault; `layers.csv` gets one row per completed layer.

## Commissioning
1. `POST /api/recipe/start {"dry_run": true, "single_step": true}` with `printing.n_layers = 2`
   and watch each move on the machine; `step` through it.
2. Same without `single_step`.
3. `heater_enabled = true` only after the heater IO pin is confirmed (docs/commissioning.md §4).
