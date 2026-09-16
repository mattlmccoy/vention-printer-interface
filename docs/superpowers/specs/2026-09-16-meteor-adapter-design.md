# Meteor printhead-firing adapter — design

**Date:** 2026-09-16
**Status:** Slice 1 (readiness/arm) — implementing.

## Problem

The Vention operator drives the MachineMotion axes and the print choreography. The **printhead
firing** (jetting binder in each layer's pattern) is done by **Meteor MetPrint** (Xaar 2001 heads)
on a Windows PC. The operator has no way to know, before it starts sweeping the printhead, whether
Meteor actually has a complete job loaded for this build. If it doesn't, the operator spreads powder
and sweeps the printhead over a bed that receives **no binder** — a silent, wasted build.

## Reality (probed 2026-09-16, not assumed)

- The firing path is **entirely hot-folder based**. `meteor_rip.py` / `fgm_to_rip.py`
  (`software/meteor/tools/`) render per-layer TIFFs (`<job>_PageN_Clr1.tif`, WhiteIsZero) into the
  **MetPrint Hot Folder**; MetPrint picks up the job and fires it, advancing pages on each print
  trigger (encoder / product-detect).
- There is **no** code anywhere that calls `PrinterInterface.dll` / the PCMD_* control API. The
  control-DLL path ("Option 2" in the `meteor-nozzle-purge-options` memory) was never built and
  needs Windows + the Meteor SDK + a dev licence.
- The operator already models firing as **external**: the choreography just moves the printhead
  start→end (Meteor fires during that sweep, encoder-clocked) and dwells for nozzle purge.
- Two hardware facts for the precise per-sweep trigger (Option B: MM digital-output → Meteor
  external PD) are **still open**: (1) is a spare MM output pin free (heater uses device 1 / pin 0)?
  (2) can Meteor be set to external PD? Until both are confirmed, no IO pulse is wired.

## Design

A small `MeteorAdapter` protocol with two concrete implementations. This matches the approved design
(interface + real Meteor impl + simulated) but grounds the "real" impl in the hot-folder architecture
that Meteor actually uses, rather than an unverified DLL contract.

```
MeteorStatus(frozen):
  backend: str            # "hot_folder" | "simulated"
  available: bool         # the firing backend is reachable (hot folder exists)
  ready: bool             # a complete job is loaded and armable for THIS build
  job_name: str | None
  layers_ready: int       # pages present
  layers_expected: int    # job.layer_count
  detail: str             # human-readable reason, never a false "ready"

MeteorAdapter (Protocol):
  name: str
  status(job: JobInfo | None) -> MeteorStatus   # arm / pre-flight readiness
  fire_layer(layer: int) -> None                # notify: printhead about to sweep layer N
  end_job() -> None
```

- **HotFolderMeteorAdapter** (real): `available` when the watched hot-folder root exists; `ready`
  when the selected job is `complete` (all pages present) and lives under a watched root.
  `fire_layer` / `end_job` are no-ops **by design** — MetPrint auto-advances pages from the hot
  folder — documented as such. Filesystem-only, so cross-platform and fully testable.
- **SimulatedMeteorAdapter** (tests / dry runs): always `available`; `ready` iff the job is complete;
  records fired layers so the choreography hook can be tested without hardware.

### False-green discipline
`ready` is **false** whenever the job is missing, incomplete, or not under a watched root, each with
a distinct `detail`. "No job loaded" must never read as "ready to fire".

## Slice 1 (this change)
- `control/meteor.py`: `MeteorStatus`, `MeteorAdapter`, `HotFolderMeteorAdapter`,
  `SimulatedMeteorAdapter`. TDD.
- `GET /api/meteor/status` — read-only readiness for the selected job (`app.state.job`), using a
  hot-folder adapter built from the jobs roots. Safe (no motion, no firing).

## Deferred (YAGNI until needed / unblocked)
- Choreography `fire_layer` hook per printing pass (real firing is auto-advance; add when a control
  adapter or PD trigger exists).
- Option B IO pulse (blocked on the two open hardware facts).
- `MeteorControlAdapter` (PCMD_* DLL) — blocked on Windows + SDK + licence; not stubbed, to avoid a
  dead contract that can't be verified.
