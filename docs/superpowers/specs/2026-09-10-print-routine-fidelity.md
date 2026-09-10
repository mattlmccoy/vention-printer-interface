# Print routine fidelity to the async lab script (2026-09-10)

The user re-sent the canonical async print script and flagged that `compile_print`
(`backend/vention_printer_interface/control/print_settings.py`) is NOT faithful to it. This records
the ground-truth sequence and the discrepancies, so the rewrite (Plan 7) is verifiable.

## Ground truth = the async script (`vention/python/*` V-series). Structure:

**Setup:** home recoater, printhead, part (NOT feed); set profiles; `moveToPosition(part, 10)`;
feed pre-positioned by the operator (`FEED_START_POS`). — **NOTE:** superseded by the primed-start
decision (2026-09-10): home GANTRIES ONLY; part+feed START from the captured `PrimedState`.

**Single cycle loop (up to 300), stage by index:**
- `cycle < THICK_PRECOAT_COUNT` → **THICK PRECOAT**, `feed_move = THICK_PRECOAT_LAYER` (7.0)
- `< THICK+NOMINAL_PRECOAT_COUNT` → **NOMINAL PRECOAT**, `feed_move = NOMINAL_FEED_THICKNESS` (0.4)
- else → **PRINTING**, feed not advanced

Per cycle:
1. **Spread**: recoater → `RECOATER_END_POS` (925).
2. **Feed advance — ONLY when stage ≠ PRINTING**: `next = feed - feed_move`; if `next ≤ FEED_HOME_POS(0)`
   → home recoater and STOP (feed exhausted); else `moveRelative(feed, -feed_move)` (feed up).
3. **Precoat return (THICK or NOMINAL)**: if NOMINAL, `moveRelative(part, +NOMINAL_LAYER_THICKNESS(0.2))`
   (part down); recoater → `RECOATER_RETURN_POS` (350); next cycle.
4. **PRINTING** (count-limited by `PRINT_LAYER_COUNT`):
   a. part drop `+NOMINAL_LAYER_THICKNESS` (0.2).
   b. recoater → `RECOATER_HOME_POS` (5) **concurrent with** printhead → `PRINTHEAD_END_POS` (900);
      one wait for both.
   c. printhead → `PRINTHEAD_HOME_POS` (5).
   d. heater (if enabled): recoater → `RECOATER_HEATER_STRT_POS` (425); heater ON; set SLOW recoater;
      recoater → `RECOATER_HEATER_END_POS` (600); heater OFF; restore recoater profile.
   e. recoater → `RECOATER_END_POS` (925).

**Final:** home printhead, home recoater, `moveToPosition(part, MAX_TRAVEL(75))`.

**Toggles:** `FEED_ENABLED`, `PART_DROP_ENABLED`, `PRINTHEAD_ENABLED`, `HEATER_ENABLED`.

## USER OVERRIDE of the script (2026-09-10)
The script SKIPS the feed advance during printing. **The user overrides this: the feed piston MUST
advance during printing too** — it is the powder supply that feeds the build/part piston, so it keeps
advancing every layer. So the current code was correct on this point; keep feed advancing in printing
(`printing.feed_thickness_mm > 0`), with the same feed-exhaustion safety applied.

## Discrepancies in the current `compile_print` (all to fix)
1. ~~Feed advances during PRINTING~~ — NOT a discrepancy; per the user override above, feed advancing
   during printing is CORRECT. (The script's skip is overridden.)
2. **Precoat recoater return** → current uses recoater HOME (5); script uses `RECOATER_RETURN_POS` (350).
3. **Feed vs part thickness** — script nominal feed 0.4 ≠ part drop 0.2; current uses one `t` for both.
4. **Concurrency** — script jets printhead→end WHILE recoater retracts home (one wait); current is
   sequential and jets after returning the recoater.
5. **Heater motion** — script: 425→600 slow-follow; current: heater_home→heater_end ×n passes.
6. **Feed-exhaustion safety** — script homes recoater and stops when the feed can't supply another
   layer; current has no guard.
7. **Finish** — script homes gantries + drives part → MAX_TRAVEL; current runs a postcoat phase.
8. **Setup** — now primed-start (home gantries only; pistons from `PrimedState`), NOT home_all+feed→145.

## Approved enhancements to LAYER ON (keep — user-confirmed earlier)
- Multi-pass jetting (`n_jet_passes`) in the printing stage.
- Pre-heater part drop before heating + raise back so the NET descent is one layer
  (`pre_heater_drop_mm`), applied after the jet passes and before the heater.
- Postcoat phase AFTER the job, toggleable (`postcoat_enabled`) — reconcile with the script's
  "final part→max" finish (postcoat runs, then the part→max drop).
- IPA heater-exposure model + readout (unchanged; informs heater sweep speed).

## Verification (Plan 7)
Rewrite `compile_print` and TDD the compiled `Step` sequence against THIS script cycle-by-cycle:
a thick-precoat cycle, a nominal-precoat cycle (feed 0.4 / part 0.2 / return 350), a printing cycle
(no feed move; concurrent recoater-home + printhead-end; heater 425→600), the feed-exhaustion break,
and the part→max finish. Keep ruff + mypy strict clean; update every stale assertion + the frontend
estimate/mirror. This is safety-relevant motion code — the test IS the spec.
