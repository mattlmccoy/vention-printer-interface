# Print Routine — Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn the print routine into the real four-phase async build with the new mechanics from spec §7–§8: **thick precoats** (build piston fixed, feed supplies, recoater backfills) → **thin precoats** → **printing** (spread → multi-pass jet → build-piston pre-heater drop → heater sweep) → **postcoats**, plus an **IPA heater-exposure** model. Keep the existing `PrintSettings → compile_print → PrintController` architecture.

**Architecture:** Extend `PrintSettings` and `compile_print` (`control/print_settings.py`) in small, separately-tested increments (multi-pass, then pre-heater drop, then the thick-precoat phase) so no single change rewrites everything. Add a pure `control/heater_model.py` for the IPA exposure math. Surface the new fields + exposure readout through `/api/print-settings` and the Print view. Pure logic is TDD'd; UI is browser/build-gated.

**Tech Stack:** Python 3.13 + uv + pytest + ruff + mypy; Vite + React + TS, `node --experimental-strip-types --test`.

Spec: `docs/superpowers/specs/2026-09-09-binderjet-console-redesign-design.md` §7–§8. Branch: `redesign/print-routine`.

**Piston sign conventions:** part/feed `move_rel` + = DOWN, − = UP.

---

## Reference: the intended four-phase sequence (confirm before executing)

Setup: home gantries (NOT pistons — pistons are positioned by priming), set feed to a start.

1. **Thick precoats** (`thick_precoat` phase, `n_layers` = count, `layer_thickness_mm` = thick, e.g. 3 × 5 mm): build piston **does not move**; per layer: recoater spread to `recoater_end_mm`, feed **up** by the thick thickness, recoater return to `recoater_home_mm`, dwell. (Backfills the runway + fills the part cavity.)
2. **Thin precoats** (`thin_precoat` phase, e.g. a few × 0.2 mm): per layer: build piston **down** by the layer, recoater spread, feed **up** by the layer, recoater return, dwell. (Nominal layering, no jetting.)
3. **Printing** (`printing` phase, N × layer): per layer: build **down** by layer, recoater spread, feed **up** by layer, dwell, recoater return; then **jet `n_jet_passes` times** (printhead to `printhead_end_mm` and back, no piston move between passes); then **build piston down `pre_heater_drop_mm`**; then heater sweep at the exposure-derived speed (heater on if enabled); then **build piston back UP `pre_heater_drop_mm`** so the net descent for the layer is exactly one layer thickness (ends one layer below the previous). The exposure that sets the sweep speed accounts for **all `n_jet_passes`** worth of IPA evaporated in the single heating pass.
4. **Postcoats** (`postcoat` phase): run after the job to cover the parts for even thermal insulation. Gated by `postcoat_enabled` (default on, toggleable off). Like thin precoats when on.

This replaces today's 3-phase `(precoat, printing, postcoat)`: `precoat` is renamed to `thin_precoat` and a new `thick_precoat` phase is prepended; `printing` gains multi-pass, the pre-heater drop AND its return-up; `postcoat` gains an enable toggle.

---

## Task 1: Extend PrintSettings (fields only, no compiler change yet)

**Files:** Modify `backend/vention_printer_interface/control/print_settings.py`; Modify `backend/tests/test_print_settings.py`, `backend/tests/test_print_settings_store.py`, and the frontend mirror `frontend/src/lib/print_settings.ts` + `frontend/src/lib/print_settings.test.ts`.

- [ ] **Step 1: Failing test** — add to `test_print_settings.py` a test asserting the new defaults:
```python
def test_new_fields_defaults() -> None:
    p = PrintSettings()
    assert p.thick_precoat.n_layers == 3 and p.thick_precoat.layer_thickness_mm == 5.0
    assert p.thin_precoat.n_layers == 2 and p.thin_precoat.layer_thickness_mm == 0.2
    assert p.n_jet_passes == 1 and p.pre_heater_drop_mm == 0.0
```
(Also: any existing test referencing `p.precoat` must be updated to `p.thin_precoat` — search and update. `PHASES` becomes `("thick_precoat", "thin_precoat", "printing", "postcoat")`.)

- [ ] **Step 2: Run, watch fail.** `cd backend && uv run pytest tests/test_print_settings.py::test_new_fields_defaults -v` → FAIL.

- [ ] **Step 3: Implement** in `print_settings.py`:
  - `PHASES = ("thick_precoat", "thin_precoat", "printing", "postcoat")`.
  - In `PrintSettings`: rename the `precoat` field to `thin_precoat` (default `PhasePlan(layer_thickness_mm=0.2, n_layers=2)`); add `thick_precoat: PhasePlan = field(default_factory=lambda: PhasePlan(layer_thickness_mm=5.0, n_layers=3))`; add `n_jet_passes: int = 1`, `pre_heater_drop_mm: float = 0.0`, and `postcoat_enabled: bool = True`.
  - Update `total_thickness_mm`, `total_layers`, `phase()`, `validate()`, `from_dict()`, `bounded()` to include `thick_precoat` and `thin_precoat` (mirror how `precoat` was handled; clamp `n_jet_passes` to `[1, 10]`, `pre_heater_drop_mm` via `_clamp(..., 0.0, 50.0)`; `postcoat_enabled` = `bool(...)`). `total_layers`/`total_thickness_mm` should treat postcoat as 0 when `postcoat_enabled` is False.
  - Add `postcoat_enabled == True` to the `test_new_fields_defaults` assertions in Step 1.
  - Keep `MAX_HEATER_PASSES`/`n_heater_passes`/`heater_enabled` as-is.

- [ ] **Step 4: Run** the new test (PASS) + the FULL `test_print_settings.py` and `test_print_settings_store.py` — update every assertion that used `precoat`/the old `PHASES`/`total_layers` counts to the new 4-phase shape (the implementer updates these to match the intended new defaults). `uv run ruff check` + `uv run mypy vention_printer_interface/control/print_settings.py` clean.

- [ ] **Step 5: Mirror the frontend types** — in `frontend/src/lib/print_settings.ts`, update `PHASES`, the `PrintSettings` type (rename `precoat`→`thin_precoat`, add `thick_precoat`, `n_jet_passes`, `pre_heater_drop_mm`), `DEFAULT_PLAN`, `totalThickness`/`totalLayers`/`validate`, and `compilePrint` mirror as needed; update `frontend/src/lib/print_settings.test.ts` + `format.test.ts` fixtures. Run `node --experimental-strip-types --test src/lib/*.test.ts` (pass) + `npm run build` (tsc clean). NOTE: the backend `compile_print` still emits the OLD sequence until Tasks 2–3; the frontend `compilePrint` mirror should be updated in lockstep with Task 3, so for THIS task only match the new fields/types, and if `compilePrint`/`compile_print` step-order tests break, defer those specific step-order assertions to Task 3 (mark them skipped with a `// TODO Task 3` and re-enable there) rather than faking output.

- [ ] **Step 6: Commit** — `feat(print-settings): 4-phase model (thick/thin precoat), multi-pass, pre-heater drop fields` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Task 2: compile_print — multi-pass jet + pre-heater piston drop (printing phase)

Incremental change to the printing phase only.

**Files:** Modify `print_settings.py` (`compile_print`), `tests/test_print_settings.py`; mirror `frontend/src/lib/print_settings.ts` (`compilePrint`) + tests.

- [ ] **Step 1: Failing test** — in `test_print_settings.py`, a printing layer with `n_jet_passes=2` and `pre_heater_drop_mm=0.1` must emit two printhead jet passes and a `move_rel PART 0.1` (down) immediately before the heater passes:
```python
def test_printing_layer_multipass_and_pre_heater_drop() -> None:
    import dataclasses
    from vention_printer_interface.control.print_settings import PhasePlan
    p = dataclasses.replace(PrintSettings(),
        thick_precoat=PhasePlan(n_layers=0), thin_precoat=PhasePlan(n_layers=0),
        printing=PhasePlan(layer_thickness_mm=0.2, n_layers=1), postcoat=PhasePlan(n_layers=0),
        n_jet_passes=2, pre_heater_drop_mm=0.1, heater_enabled=True)
    ks = [(s.kind, s.axis, s.value) for s in compile_print(p)]
    jet = [i for i, k in enumerate(ks) if k == ("move_abs", PRINTHEAD, p.printhead_end_mm)]
    assert len(jet) == 2  # two jet passes
    i_drop = ks.index(("move_rel", PART, p.pre_heater_drop_mm))
    i_heater_on = next(i for i, k in enumerate(ks) if k[0] == "heater" and k[2] == 1.0)
    i_up = next(i for i, k in enumerate(ks) if k == ("move_rel", PART, -p.pre_heater_drop_mm) and i > i_heater_on)
    assert max(jet) < i_drop < i_heater_on < i_up  # drop after jets → heat → raise back up
```
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** in `compile_print`'s printing branch: wrap the existing single printhead jet (`move_abs PRINTHEAD end` → wait → `move_abs PRINTHEAD home` → wait) in `for _ in range(plan.n_jet_passes):`. After the jet passes and before the heater block, if `plan.pre_heater_drop_mm > 0`: `add(..., "move_rel", PART, plan.pre_heater_drop_mm, "pre-heater drop")` + `wait`. After the heater block (heater off / last heater pass), if `plan.pre_heater_drop_mm > 0`: `add(..., "move_rel", PART, -plan.pre_heater_drop_mm, "raise back to layer")` + `wait` — so the net part descent for the layer is exactly the layer thickness (ends one layer below the previous). Leave the heater-pass block otherwise intact.
- [ ] **Step 4: Run** the new test + the existing printing-layer step-order test (update its expected sequence to include the pass loop + drop). Full `test_print_settings.py` green; ruff/mypy clean.
- [ ] **Step 5: Mirror** in `frontend/src/lib/print_settings.ts` `compilePrint` + re-enable/adjust the frontend step tests. `npm run build` clean.
- [ ] **Step 6: Commit** — `feat(print): multi-pass jetting + pre-heater build-piston drop`.

---

## Task 3: compile_print — the thick-precoat phase (build fixed)

**Files:** Modify `print_settings.py` (`compile_print`), `tests/test_print_settings.py`; mirror frontend.

- [ ] **Step 1: Failing test** — a thick-precoat layer must NOT move the part piston, must spread the recoater, and must raise the feed by the thick thickness:
```python
def test_thick_precoat_layer_holds_part_and_spreads() -> None:
    import dataclasses
    from vention_printer_interface.control.print_settings import PhasePlan
    p = dataclasses.replace(PrintSettings(),
        thick_precoat=PhasePlan(layer_thickness_mm=5.0, n_layers=1),
        thin_precoat=PhasePlan(n_layers=0), printing=PhasePlan(n_layers=0), postcoat=PhasePlan(n_layers=0))
    steps = [s for s in compile_print(p) if s.phase == "thick_precoat"]
    ks = [(s.kind, s.axis, s.value) for s in steps]
    assert not any(k == "move_rel" and a == PART for (k, a, v) in ks)  # part piston fixed
    assert ("move_abs", RECOATER, p.recoater_end_mm) in ks             # spread
    assert ("move_rel", FEED, -5.0) in ks                              # feed up by the thick layer
```
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** — in `compile_print`, handle the `thick_precoat` phase with a distinct per-layer body (build piston fixed): `mark layer_start`; `move_abs RECOATER recoater_end_mm` + wait (spread); `move_rel FEED -(layer_thickness)` + wait (feed up); `dwell settle_s`; `move_abs RECOATER recoater_home_mm` + wait (return); `mark layer_end`. The `thin_precoat`, `printing`, `postcoat` phases keep the part-piston-down body (thin/postcoat = the old precoat body; printing from Task 2). Drive this off the phase name. **Skip the `postcoat` phase entirely when `plan.postcoat_enabled` is False** (emit no postcoat steps). Add a test `test_postcoat_toggle_off_emits_no_postcoat_steps` asserting `postcoat` phase steps are absent when disabled.
- [ ] **Step 4: Run** the new test + update the compile step-order/`total_*` tests for the full 4-phase sequence; full `test_print_settings.py` + `test_print_controller.py` green (the controller runs compiled prints); ruff/mypy clean.
- [ ] **Step 5: Mirror** frontend `compilePrint` + tests; `npm run build` clean.
- [ ] **Step 6: Commit** — `feat(print): thick-precoat phase (build piston fixed, feed supplies, recoater backfills)`.

---

## Task 4: IPA heater-exposure model (pure)

**Files:** Create `backend/vention_printer_interface/control/heater_model.py` + `backend/tests/test_heater_model.py`; mirror `frontend/src/lib/heater_model.ts` + `frontend/src/lib/heater_model.test.ts`.

- [ ] **Step 1: Failing test** (backend) `test_heater_model.py`:
```python
from vention_printer_interface.control.heater_model import HeaterExposure, exposure

def test_ipa_exposure_energy_and_time() -> None:
    # 0.2 mm layer, 30x30 mm doped, 15 wt% carbon, Nylon-12 1.01 g/cm^3, ink 25 wt% carbon,
    # IPA dHvap 663 J/g, heater 75 W over the 30 mm section.
    e: HeaterExposure = exposure(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15,
                                 powder_density_g_cm3=1.01, ink_carbon_wt=0.25,
                                 ipa_dhvap_j_g=663.0, section_power_w=75.0)
    # powder mass = 1.01 g/cm^3 * (900*0.2 mm^3 = 180 mm^3 = 0.18 cm^3) = 0.1818 g
    # carbon = 0.1818 * 0.15/0.85 = 0.03208 g ; ink = /0.25 = 0.12831 g ; IPA = *0.75 = 0.09623 g
    # energy = 0.09623 * 663 = 63.8 J ; time = /75 = 0.85 s
    assert round(e.powder_mass_g, 4) == 0.1818
    assert round(e.ipa_mass_g, 4) == 0.0962
    assert round(e.energy_j, 1) == 63.8
    assert round(e.time_s, 2) == 0.85

def test_sweep_speed_from_pass_length() -> None:
    e = exposure(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15, powder_density_g_cm3=1.01,
                 ink_carbon_wt=0.25, ipa_dhvap_j_g=663.0, section_power_w=75.0)
    assert round(e.sweep_speed_mm_s(pass_length_mm=30.0), 1) == round(30.0 / e.time_s, 1)

def test_multipass_scales_energy_and_time() -> None:
    kw = dict(layer_mm=0.2, area_mm2=900.0, carbon_wt=0.15, powder_density_g_cm3=1.01,
              ink_carbon_wt=0.25, ipa_dhvap_j_g=663.0, section_power_w=75.0)
    e1 = exposure(**kw)
    e2 = exposure(**kw, passes=2)  # two jet passes' ink evaporated in one heating pass
    assert round(e2.energy_j, 3) == round(e1.energy_j * 2, 3)
    assert round(e2.time_s, 3) == round(e1.time_s * 2, 3)
```
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** `heater_model.py`:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class HeaterExposure:
    powder_mass_g: float
    carbon_mass_g: float
    ink_mass_g: float
    ipa_mass_g: float
    energy_j: float
    time_s: float

    def sweep_speed_mm_s(self, pass_length_mm: float) -> float:
        return pass_length_mm / self.time_s if self.time_s > 0 else 0.0


def exposure(*, layer_mm: float, area_mm2: float, carbon_wt: float, powder_density_g_cm3: float,
             ink_carbon_wt: float, ipa_dhvap_j_g: float, section_power_w: float,
             passes: int = 1) -> HeaterExposure:
    """IPA-only heater exposure (spec §8). Ink is `ink_carbon_wt` carbon / the rest IPA.
    powder_mass = density * volume (per layer); carbon deposited = powder * wt/(1-wt) * `passes`
    (multi-pass stacks `passes` layers of ink evaporated in ONE heating pass); ink = carbon /
    ink_carbon_wt; IPA = ink * (1 - ink_carbon_wt); energy = IPA * dHvap; time = energy / power."""
    volume_cm3 = (area_mm2 * layer_mm) / 1000.0
    powder = powder_density_g_cm3 * volume_cm3
    carbon = (powder * carbon_wt / (1.0 - carbon_wt) if carbon_wt < 1.0 else 0.0) * max(passes, 1)
    ink = carbon / ink_carbon_wt if ink_carbon_wt > 0 else 0.0
    ipa = ink * (1.0 - ink_carbon_wt)
    energy = ipa * ipa_dhvap_j_g
    time = energy / section_power_w if section_power_w > 0 else 0.0
    return HeaterExposure(round(powder, 6), round(carbon, 6), round(ink, 6), round(ipa, 6),
                          round(energy, 3), round(time, 3))
```
- [ ] **Step 4: Run** (PASS); ruff/mypy clean.
- [ ] **Step 5: Mirror** `frontend/src/lib/heater_model.ts` (same math, returning `{powderMassG, ipaMassG, energyJ, timeS, sweepSpeed(passLenMm)}`) + `heater_model.test.ts` with the same example numbers; run + `npm run build`.
- [ ] **Step 6: Commit** — `feat(heater): IPA exposure model (energy → time → sweep speed)`.

---

## Task 5: Expose heater-exposure inputs on PrintSettings + payload

**Files:** Modify `print_settings.py` (add exposure inputs) + `api/app.py` (`print_settings_payload` includes an `exposure` block) + tests.

- [ ] **Step 1: Failing test** — `test_print_settings.py`: `PrintSettings()` has `target_carbon_wt == 0.15`, `part_area_mm2 == 900.0`, `powder_density_g_cm3 == 1.01`, `ink_carbon_wt == 0.25`, `ipa_dhvap_j_g == 663.0`, `heater_section_power_w == 75.0`. And an API test (`test_api.py` or a new `test_api_print.py`): `GET /api/print-settings` returns an `exposure` object with numeric `energy_j`, `time_s`, `sweep_speed_mm_s` for the printing layer thickness.
- [ ] **Step 2: Run, watch fail.**
- [ ] **Step 3: Implement** — add those six fields to `PrintSettings` (bounded/validate as scalars, sensible clamps). In `app.py` `print_settings_payload`, compute `HeaterExposure` from the printing phase's `layer_thickness_mm` + these fields, passing `passes=plan.n_jet_passes` (so multi-pass ink is accounted for) and pass length = `printhead_end_mm - printhead_home_mm`; include `"exposure": {"energy_j":..., "time_s":..., "sweep_speed_mm_s":...}`.
- [ ] **Step 4: Run** full backend suite (exit 0), ruff/mypy clean.
- [ ] **Step 5: Commit** — `feat(print): heater-exposure inputs + exposure readout in the print-settings payload`.

---

## Task 6: Print view — expose the new params + exposure readout

**Files:** Modify `frontend/src/components/views/PrintView.tsx` (and/or a settings sub-panel it uses) + `frontend/src/lib/api.ts` (`PrintSettingsPayload` gains `exposure`).

- [ ] **Step 1** — READ `PrintView.tsx` and how it currently reads/edits `api.printSettings()` / `api.setPrintSettings()`. Add editable controls for `thick_precoat`/`thin_precoat` (layers × thickness), `n_jet_passes`, `pre_heater_drop_mm`, a **`postcoat_enabled` toggle** (checkbox), and the heater-exposure inputs (`target_carbon_wt`, `part_area_mm2`, `heater_section_power_w`, etc.), plus a read-only **exposure readout** (energy J, time s, sweep speed) from the payload's `exposure` block. Keep the existing run/pause/step/abort controls.
- [ ] **Step 2** — Update `PrintSettingsPayload` in `api.ts` to include `exposure: { energy_j: number; time_s: number; sweep_speed_mm_s: number }`.
- [ ] **Step 3** — Verify `npm run build` tsc-clean + full lib suite; browser-smoke on `--backend simulated`: Print view shows the new params + a live exposure readout that changes when you edit the printing layer thickness.
- [ ] **Step 4: Commit** — `feat(print-view): edit the 4-phase routine + multi-pass/pre-heater + live IPA exposure`.

---

## Task 7: Priming as its own page (nav restructure)

Spec §3 puts Priming on its own tab; it currently lives as a module inside Control. Give it a page.

**Files:** `frontend/src/lib/console.ts` (VIEWS), `frontend/src/App.tsx` (route the new view), create `frontend/src/components/views/PrimingView.tsx`, modify `frontend/src/components/views/ControlView.tsx` (remove the priming module).

- [ ] **Step 1** — In `console.ts`, add `"priming"` to `VIEWS` (order per spec §3: `["control","priming","print","job","runs"]`, or keep `print` first if that's the current landing — match the existing default sensibly). Ensure `DEFAULT_CONSOLE.view` still valid.
- [ ] **Step 2** — Create `PrimingView.tsx`: a `view` wrapper that renders the existing `<PrimingPanel gates=... call=... printState=... />` (reuse it verbatim — it already has the setup params, plain-language sequence, RUN/RESUME/ABORT). Give it the same `status/gates/call` props signature as the other views so `App.tsx` can render it.
- [ ] **Step 3** — In `ControlView.tsx`, REMOVE the `priming` module from the `modules` array (and the `PrimingPanel` import if now unused). Control is manual driving only.
- [ ] **Step 4** — In `App.tsx`, render `<PrimingView .../>` when `ui.view === "priming"` (mirror how `control`/`runs` are routed, passing `status`, `gates`, `call`, and the print state for resume).
- [ ] **Step 5** — Verify `npm run build` tsc-clean + full lib suite; browser-smoke: a **Priming tab** appears, opens the priming page, and Control no longer shows a priming module.
- [ ] **Step 6: Commit** — `feat(nav): priming is its own page (spec §3 page structure)`.

## Self-review notes
- Spec §7 (4 phases, multi-pass, pre-heater drop) → Tasks 1–3; §8 (IPA exposure) → Tasks 4–6.
- Highest-risk task is Task 3 (thick-precoat phase) and the step-order test updates in Tasks 2–3 — the implementer must update the exact expected sequences to match the intended mechanics in the "Reference" section above; if the intended mechanics are wrong, that's a spec issue to escalate, not a test to force green.
- The backend `compile_print` and the frontend `compilePrint` mirror must stay in lockstep (Task 1 flags the interim skip; Tasks 2–3 re-enable).
- Calibration-pending values (thick-precoat count/thickness, `part_area_mm2`, `target_carbon_wt`) ship as editable defaults per spec §13.
