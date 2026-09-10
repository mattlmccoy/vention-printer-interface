# Binder Jet Console — redesign design

Date: 2026-09-09 · Status: approved-in-brainstorm, pending written-spec review
Supersedes the layout decisions in `2026-09-08-vention-printer-interface-design.md`; the backend
control model (Steps → PrintController → guarded Controller) carries forward unchanged.

## 1. Why

The tool works and connects to the real MachineMotion, but it is not yet organized around the way
an operator actually runs a print, and it is hard to read. This redesign reorganizes the UI into
task pages, adds a digital move-preview, exposes the print routine as its own adjustable page,
splits priming (setup) from the print (build), and adds an IPA heater-exposure model. It upgrades
what exists rather than replacing it.

## 2. Scope

In: page restructure, digital preview, Control cleanup + per-axis speed/accel, Priming setup
routine, Print routine page + new mechanics, IPA heater-exposure model, humanized log, connect
dedupe, wireframe diagram, printhead travel 970, GH Pages hosting, e-stop honesty.
Out (later passes): Meteor hot-folder per-layer page sync; full Job workflow; e-stop hardware-red
(firmware-limited, see §10).

## 3. Pages

`Control · Priming · Print · Job · Runs`. Job stays but minimal.

## 4. Cross-cutting: Digital Preview ("dry-run on the diagram")

A **"preview big moves"** toggle (ON by default). It applies to the multi-step / multi-axis
operations — **home-all-axes, priming, a full print** — not to a single jog/go-to.

When ON, issuing one of those operations first **plays the planned motion on the wireframe diagram**:
ghost markers sweep through the planned positions (from the compiled Step list), scrubbable, with a
clear "nothing sent to machine" badge. The operator then hits **RUN** to commit or **CANCEL**.
Toggle OFF to go straight to real motion.

Implementation: pure frontend animation of compiled Step positions using the existing diagram
geometry (`elevation.ts` / the calibrated wireframe). No hardware command is issued during a
preview, so it carries zero risk. The backend already produces the Step lists (`compile_print`,
the priming compiler); the preview consumes them.

## 5. Control

Manual driving only.
- **Per-axis independent speed + accel** for all four axes (revert the shared/module-level control).
  Backend already supports `PUT /api/axes/{n}/motion`.
- Jog (step selector) + absolute go-to (previewed when the move is large).
- **Homing is per gantry**, one at a time, each with a one-line confirm. **No "home all gantries."**
  Pistons are never auto-homed (homing a piston drives it fully up/flush and ejects powder).
- **Load Cart and Clear Bed removed** until their real behavior is defined.
- The calibrated wireframe diagram lives here.

## 6. Priming (setup routine — its own page)

Priming is **job setup**, not a layer loop. It gets the machine ready to print.

Sequence:
1. **Build / part piston → TOP** (flush, ~0 mm).
2. **Feed piston → DOWN** to open a powder cavity (depth is a calibrated / job-derived parameter).
3. **Operator loads powder** into the feed cavity (manual, the routine prompts and waits).
4. **Recoater leveling spread** across the runway between the cylinders to level the powder.
   *The spread parameters need physical calibration — flagged as a calibration task, not a guess.*
5. End in the exact handoff state the print expects (build at top, feed charged with powder).

Deterministic and short. Page shows editable params, a **plain-language sequence preview**, the
**digital dry-run** on the diagram, and run/pause/abort through the same guarded step engine.

Note: the existing `priming.py` thick-precoat loop is **NOT** this — it moves into the Print routine
(§7). Priming is rebuilt as the position-load-level setup above.

## 7. Print (async routine — its own page, the centerpiece)

Keep the operator's `async_print_routine` as the core; make targeted adjustments. Four phases:

1. **Thick precoats** — the build piston **stays put**; the recoater spreads repeatedly to backfill
   the runway between the cylinders and fill the part-piston cavity; the feed piston raises to supply
   powder. (This is the loop currently mislabeled as priming.)
2. **Thin precoats** — nominal layers (build drops slightly, feed raises, spread).
3. **Printing** — per layer: spread → **jet, multi-pass** (N printhead passes with no piston move) →
   **build piston drops X mm as the heater comes by** → heater sweep at the exposure-derived speed.
4. **Postcoats** — finishing layers.

New mechanics vs the original script:
- **Multi-pass**: N printhead jet passes per layer, pistons unmoved.
- **Piston-down-before-heater**: build piston drops a set X mm before the heater sweep.
- **Thin-precoat phase** distinct from thick precoats.
- **IPA heater exposure** drives the heater sweep speed (§8).

Fully adjustable params on the page; sequence preview + digital dry-run + real dry-run +
run/pause/step/abort; live cross-section + wireframe when running.

## 8. Heater exposure / power model (IPA)

Ink is **25 wt% carbon black / ~75 wt% IPA** (treat the balance as IPA — worst-case). Layer
thickness is a **live input** (100 / 150 / 200 µm, set by the print). Per printed layer:

```
carbon_mass = powder_mass_in_layer × target_carbon_wt% / (1 − target_carbon_wt%)
ink_mass    = carbon_mass / 0.25
IPA_mass    = ink_mass × 0.75
energy      = IPA_mass × ΔH_vap(IPA ≈ 663 J/g)
time        = energy / heater_section_power        # 500 W / 200 mm ⇒ 75 W per 30 mm section
sweep_speed = pass_length / time                   # recoater speed for that dwell
```

Editable inputs with defaults from the proposal (Appendix B): **target carbon 15 wt%**,
powder Nylon-12 **1.01 g/cm³**, doped area **30×30 mm**, layer thickness from the print.
Recomputes live. Numbers shown in the mockup are placeholders pending confirmation of these values.

## 9. Job / Runs

- **Job** — pick a sliced Meteor job → sets the Print routine's layer count and thickness. Per-layer
  TIFF page-sync to the printhead is a later pass.
- **Runs** — recorded-run history + a **humanized event log** (axis numbers → names:
  "Recoater gantry homed", not "axis 4 homed").

## 10. Cross-cutting fixes (folded into the build)

- Printhead soft-travel **840 → 970 mm** (measured end stop); recoater already 972.
- **Connect dedupe** — show only the reachable MachineMotion; drop the phantom second IP.
- **Wireframe** — wire in `dissertation_materials/proposal/writing/figures/machine_sketch_bw.png`
  as the diagram and calibrate rail/piston markers to it.
- **GH Pages** static host that talks to the localhost backend (site mode already exists in
  `operator.ts` / `VITE_SITE_MODE`), same pattern as FLIR / T&C.
- **Readability** — larger base type, higher-contrast text, larger labels across the tool.
- **E-STOP** — the software E-STOP halts all motion (M410) + heater and faults the console; it
  **cannot** turn the MM red — this firmware rejects every software e-stop MQTT command
  (trigger/release/systemreset all return false, verified live). It is labeled honestly. For a
  software **reset**, probe the `:8000` HTTP API for a reset route the HMI may use; if none works,
  recovery stays "twist out the physical E-STOP + Clear Fault" (the physical reset does clear
  `estop/status`, verified live).

## 11. Already landed on this branch (keep)

Telemetry-stale false-fault fix (`stale_fault_s`), 972/970 travel, home-direction jog arrows +
diagram flip, heater-confirm removal, diagram label fix. The `priming.py`/`/api/priming` work is
kept but **repurposed into the Print precoat phases**.

## 12. Architecture

Everything runs through the existing model: parameterized settings dataclass → `compile_*` to a
`Step` tuple → `PrintController.start_*` → guarded `Controller`. The Print routine becomes a
`PrintSettings`/`compile_print` extended with the four phases + multi-pass + pre-heater drop +
heater exposure. Priming becomes a new small `compile_priming_setup`. The digital preview is a
frontend consumer of the compiled Step positions. Pure logic (compilers, the IPA model) is
unit-tested (TDD); UI is browser-verified.

## 13. Open / calibration items

- Priming leveling-spread parameters (physical calibration).
- Feed-cavity depth derivation (job-derived vs set per run).
- Confirm target carbon 15 wt% and treating the ink balance as pure IPA.
- Whether an HTTP e-stop reset route exists on `:8000`.

## 14. Testing

TDD for every compiler and the IPA model (fail → pass). Browser verification for each page against
`--backend simulated`, then a live check on the real controller. No routine touches hardware in a
preview or dry-run.
