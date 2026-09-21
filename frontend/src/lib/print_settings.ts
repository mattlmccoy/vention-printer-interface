/** Mirror of backend/vention_printer_interface/control/print_settings.py: the same plan shape, the
 *  same defaults (V1.py constants) and the same step order, so the UI can preview a print_settings and
 *  show the printability verdict before asking the operator. The backend is the authority. */

export const PART = 1, FEED = 2, PRINTHEAD = 3, RECOATER = 4;
// The thick precoats now live in the priming routine (they fill the runway + part cavity with the
// build piston fixed). The print begins at the thin precoats, where the build piston first drops.
export const PHASES = ["thin_precoat", "printing", "postcoat"] as const;
// Usable build-piston travel FROM HOME with the piston ATTACHED (normal case) ~72 mm (= default
// part_max_mm). Bare actuator does ~130 mm (360 − 230), but the attached piston bottoms out ~72 mm;
// a deeper build silently under-builds. Mirrors backend print_settings.PART_USABLE_TRAVEL_MM.
export const PART_USABLE_TRAVEL_MM = 72;
export type Phase = (typeof PHASES)[number];

// Precoat-style phases lay a cover layer only (spread -> feed advance -> recoater return to 350);
// part-drop phases drop the build piston one layer (grow the part height). Mirrors the backend.
const PRECOAT_PHASES = new Set<string>(["thin_precoat", "postcoat"]);
const PART_DROP_PHASES = new Set<string>(["thin_precoat", "printing"]);
// Minimum build-piston up-seat for an imaged printing layer: mechanical slop couples piston
// direction to the print-plane position (<1 mm), so an imaged layer must end its drop moving UP
// (approach from below) — the same side the recoater/jet see — or the plane and image reference
// shift between layers. Used only as a floor when build_backlash_mm is below it. Mirrors the backend.
export const CAPTURE_SEAT_MM = 0.1;
// The feed piston's hard floor (script FEED_HOME_POS): an advance to/below it cannot supply a layer.
const FEED_FLOOR_MM = 0;

export interface PhasePlan {
  layer_thickness_mm: number;
  feed_thickness_mm: number;
  n_layers: number;
  part_speed: number;
  part_accel: number;
  feed_speed: number;
  feed_accel: number;
  printhead_speed: number;
  printhead_accel: number;
  recoater_speed: number;
  recoater_accel: number;
}

export interface PrintSettings {
  thin_precoat: PhasePlan;
  printing: PhasePlan;
  postcoat: PhasePlan;
  n_jet_passes: number;
  pre_heater_drop_mm: number;
  postcoat_enabled: boolean;
  feed_end_mm: number;
  recoater_home_mm: number;
  recoater_return_mm: number;
  recoater_end_mm: number;
  heater_home_mm: number;
  heater_start_mm: number;
  heater_end_mm: number;
  printhead_home_mm: number;
  printhead_end_mm: number;
  printhead_multipass_return_mm: number;
  printhead_start_mm: number;
  purge_dwell_s: number;
  purge_mode: string; // "every_pass" | "per_layer" | "every_n_layers"
  purge_every_n_layers: number;
  purge_position_mm: number | null;
  part_max_mm: number;
  build_piston_max_mm: number; // per-cylinder usable max travel from home (operator-set)
  feed_piston_max_mm: number;
  heater_speed: number;
  heater_accel: number;
  n_heater_passes: number;
  heater_enabled: boolean;
  settle_s: number;
  feed_backlash_mm: number;
  build_backlash_mm: number; // build-piston anti-backlash: overshoot the drop, return to target
  absolute_layer_seat: boolean; // opt-in: position the build piston by ABSOLUTE seat (no drift); false = relative
  feed_fast_speed: number;
  feed_fast_accel: number;
  capture_stages: boolean; // emit layerwise vision capture marks (OFF by default; no cameras yet)
  capture_stages_enabled: string[]; // which stages to capture when capture_stages is on (subset of CAPTURE_STAGES)
  capture_recoater_mm: number; // overhead science cam: recoater pose to centre it over the bed (0 = fixed cam)
  capture_settle_s: number; // dwell after moving to the capture pose before the shot
  capture_hold_s: number; // dwell after the trigger so the asynchronous browser exposure finishes
}

/** The three per-layer capture stages, in the canonical order the backend emits them. */
export const CAPTURE_STAGES = ["pre_jet", "post_jet", "post_heat"] as const;
export const CAPTURE_STAGE_LABEL: Record<string, string> = {
  pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat",
};

/** True when the slicer declared a multipass factor (#7) that the print is NOT currently set to —
 *  drives the "created with multipass Nx" warning. A missing/invalid slicer value never warns
 *  (data-contract: absence is not a mismatch). Pure. */
export function multipassMismatch(slicer: number | null | undefined, currentPasses: number): boolean {
  return slicer != null && slicer >= 1 && currentPasses !== slicer;
}

/** Toggle one stage in the enabled list, always returning the valid stages in canonical order.
 *  Pure so it can be unit-tested; the backend re-canonicalizes untrusted input regardless. */
export function toggleCaptureStage(enabled: readonly string[], stage: string): string[] {
  const has = enabled.includes(stage);
  const next = new Set(enabled.filter((s) => (CAPTURE_STAGES as readonly string[]).includes(s)));
  if (has) next.delete(stage); else if ((CAPTURE_STAGES as readonly string[]).includes(stage)) next.add(stage);
  return CAPTURE_STAGES.filter((s) => next.has(s));
}

const basePhase: PhasePlan = {
  layer_thickness_mm: 2, feed_thickness_mm: 2, n_layers: 1, part_speed: 2.5, part_accel: 15,
  feed_speed: 2.5, feed_accel: 15, printhead_speed: 100, printhead_accel: 500,
  recoater_speed: 100, recoater_accel: 500,
};

export const DEFAULT_PLAN: PrintSettings = {
  thin_precoat: { ...basePhase, layer_thickness_mm: 0.2, feed_thickness_mm: 0.4, n_layers: 2 },
  printing: { ...basePhase, layer_thickness_mm: 2, feed_thickness_mm: 0.4, n_layers: 10 },
  postcoat: { ...basePhase, layer_thickness_mm: 5, feed_thickness_mm: 0, n_layers: 1 },
  n_jet_passes: 1, pre_heater_drop_mm: 0, postcoat_enabled: true,
  feed_end_mm: 145, recoater_home_mm: 5, recoater_return_mm: 350, recoater_end_mm: 950,
  heater_home_mm: 5, heater_start_mm: 425, heater_end_mm: 600,
  printhead_home_mm: 5, printhead_end_mm: 900, printhead_multipass_return_mm: 250, printhead_start_mm: 250, part_max_mm: 72, build_piston_max_mm: 72, feed_piston_max_mm: 72,
  purge_dwell_s: 0, purge_mode: "per_layer", purge_every_n_layers: 5, purge_position_mm: null,
  heater_speed: 50, heater_accel: 250, n_heater_passes: 1,
  heater_enabled: false, settle_s: 1, feed_backlash_mm: 0, build_backlash_mm: 0, absolute_layer_seat: false, feed_fast_speed: 5, feed_fast_accel: 30,
  capture_stages: false, capture_stages_enabled: ["pre_jet", "post_jet", "post_heat"],
  capture_recoater_mm: 0, capture_settle_s: 0.5, capture_hold_s: 2,
};

export type StepKind = "home" | "set_speed" | "set_accel" | "move_abs" | "move_rel" | "seat_part" | "wait" | "dwell" | "heater" | "mark";
export interface Step {
  index: number;
  phase: string;
  layer: number;
  kind: StepKind;
  axis: number | null;
  value: number | null;
  label: string;
  part_height_mm: number;
}

const counts = (p: PrintSettings, ph: Phase): boolean => ph !== "postcoat" || p.postcoat_enabled;
export function totalThickness(p: PrintSettings): number {
  return PHASES.reduce((s, ph) => (counts(p, ph) ? s + p[ph].layer_thickness_mm * p[ph].n_layers : s), 0);
}
export function totalLayers(p: PrintSettings): number {
  return PHASES.reduce((s, ph) => (counts(p, ph) ? s + p[ph].n_layers : s), 0);
}

/** Same reasons as PrintSettings.validate() (travel window defaults to the axis extents). */
export function validate(p: PrintSettings, travelMax: Record<number, number> = { 2: 145, 3: 970, 4: 972 }): string[] {
  const reasons: string[] = [];
  const total = totalThickness(p);
  if (total > p.feed_end_mm)
    reasons.push(`total thickness ${total.toFixed(1)} mm exceeds feed travel ${p.feed_end_mm.toFixed(1)} mm (V1.py printability check)`);
  const deepestPart = Math.max(total, p.part_max_mm);
  if (deepestPart > p.build_piston_max_mm)
    reasons.push(`build reaches ${deepestPart.toFixed(1)} mm but the build piston's max travel is ${p.build_piston_max_mm.toFixed(1)} mm from home — it stops there, so the part would not finish (silent under-build)`);
  for (const ph of PHASES) if (p[ph].n_layers > 0 && p[ph].layer_thickness_mm <= 0) reasons.push(`${ph}.layer_thickness_mm must be > 0 when n_layers > 0`);
  const positions: Array<[string, number, number]> = [
    ["feed_end_mm", FEED, p.feed_end_mm], ["recoater_home_mm", RECOATER, p.recoater_home_mm],
    ["recoater_end_mm", RECOATER, p.recoater_end_mm], ["heater_home_mm", RECOATER, p.heater_home_mm],
    ["heater_end_mm", RECOATER, p.heater_end_mm], ["printhead_home_mm", PRINTHEAD, p.printhead_home_mm],
    ["printhead_end_mm", PRINTHEAD, p.printhead_end_mm],
  ];
  for (const [label, axis, v] of positions) {
    const hi = travelMax[axis] ?? Infinity;
    if (v < 0 || v > hi) reasons.push(`${label}=${v} outside axis ${axis} travel [0, ${hi}]`);
  }
  if (totalLayers(p) === 0) reasons.push("no layers to print");
  return reasons;
}

/** Exact mirror of compile_print(): the faithful async-lab-script step sequence (fidelity spec).
 *  Primed start homes the two gantries only; per printing layer the recoater retract and printhead
 *  jet run concurrently under ONE wait; precoat-style phases return the recoater to 350; the finish
 *  homes the gantries then drives the part to part_max; feed exhaustion is a terminal safety stop. */
export function compilePrint(plan: PrintSettings): Step[] {
  const out: Step[] = [];
  let height = 0;
  const add = (phase: string, layer: number, kind: StepKind, axis: number | null = null, value: number | null = null, label = "") =>
    out.push({ index: out.length, phase, layer, kind, axis, value, label, part_height_mm: height });

  // SETUP (primed start): home GANTRIES ONLY, then an initial safe profile for all four axes.
  add("setup", 0, "home", PRINTHEAD);
  add("setup", 0, "wait");
  add("setup", 0, "home", RECOATER);
  add("setup", 0, "wait");
  const base = plan.thin_precoat; // a representative base profile for all four axes
  add("setup", 0, "set_speed", PART, base.part_speed);
  add("setup", 0, "set_accel", PART, base.part_accel);
  add("setup", 0, "set_speed", FEED, base.feed_speed);
  add("setup", 0, "set_accel", FEED, base.feed_accel);
  add("setup", 0, "set_speed", RECOATER, base.recoater_speed);
  add("setup", 0, "set_accel", RECOATER, base.recoater_accel);
  add("setup", 0, "set_speed", PRINTHEAD, base.printhead_speed);
  add("setup", 0, "set_accel", PRINTHEAD, base.printhead_accel);
  // No printhead park: after homing it stays home (5). Parking it mid-bed (250) would sit it right
  // in the recoater's spread path and block coating. The pistons stay at the primed bed.

  let feedPos = plan.feed_end_mm; // running feed column top; drops by each feed advance
  let layerNo = 0;
  let printLayer = 0; // 1-based printing-layer index (for the nozzle-purge schedule)
  let exhausted = false;
  for (const name of PHASES) {
    if (name === "postcoat" && !plan.postcoat_enabled) continue;
    const ph = plan[name];
    if (ph.n_layers === 0) continue;
    // Per-phase speeds/accels for all four axes (order: PART, FEED, PRINTHEAD, RECOATER).
    add(name, layerNo, "set_speed", PART, ph.part_speed);
    add(name, layerNo, "set_accel", PART, ph.part_accel);
    add(name, layerNo, "set_speed", FEED, ph.feed_speed);
    add(name, layerNo, "set_accel", FEED, ph.feed_accel);
    add(name, layerNo, "set_speed", PRINTHEAD, ph.printhead_speed);
    add(name, layerNo, "set_accel", PRINTHEAD, ph.printhead_accel);
    add(name, layerNo, "set_speed", RECOATER, ph.recoater_speed);
    add(name, layerNo, "set_accel", RECOATER, ph.recoater_accel);
    for (let idx = 0; idx < ph.n_layers; idx++) {
      // Feed-exhaustion guard: if this layer's feed advance would reach/cross the floor, stop.
      if (ph.feed_thickness_mm > 0 && feedPos - ph.feed_thickness_mm <= FEED_FLOOR_MM) {
        add(name, layerNo + 1, "move_abs", RECOATER, plan.recoater_home_mm);
        add(name, layerNo + 1, "wait");
        add(name, layerNo + 1, "mark", null, null, "feed_exhausted");
        exhausted = true;
        break;
      }
      layerNo++;
      if (PART_DROP_PHASES.has(name)) height += ph.layer_thickness_mm;

      add(name, layerNo, "mark", null, null, "layer_start");
      // 1) PART DROP — thin_precoat & printing only (postcoat holds the part fixed). V1.py drops the
      // build piston FIRST, before the recoater repositions or the feed supplies powder.
      // Anti-backlash: overshoot the drop DOWN by build_backlash_mm, then return UP to the target
      // (net descent = layer_thickness), so the drop is approached one-sided. Mirrors the backend.
      if (PART_DROP_PHASES.has(name)) {
        // An imaged printing layer must end the drop on an UP move so the plane seats from the same
        // side the recoater/jet see (capture plane == jetting plane). Force at least CAPTURE_SEAT_MM
        // of up-seat for those layers even when backlash is 0. Net descent stays layer_thickness.
        const capturesOn = plan.capture_stages && plan.capture_stages_enabled.length > 0;
        const seat = name === "printing" && capturesOn
          ? Math.max(plan.build_backlash_mm, CAPTURE_SEAT_MM)
          : plan.build_backlash_mm;
        if (plan.absolute_layer_seat) {
          // ABSOLUTE: seat_part carries the cumulative commanded height; the controller moves to
          // (primed datum + height). Overshoot to height+seat (down), return to height (up). Mirrors backend.
          add(name, layerNo, "seat_part", PART, height + seat);
          add(name, layerNo, "wait");
          add(name, layerNo, "seat_part", PART, height, "build seat");
          add(name, layerNo, "wait");
        } else {
          add(name, layerNo, "move_rel", PART, ph.layer_thickness_mm + seat);
          add(name, layerNo, "wait");
          if (seat > 0) {
            add(name, layerNo, "move_rel", PART, -seat, "build backlash return");
            add(name, layerNo, "wait");
          }
        }
      }

      // 2) REPOSITION — recoater past the feed piston out to the far end, so it can spread on the way
      // back. Optional anti-backlash: drop the feed a little BEFORE this move (keeps the nozzles clear
      // of powder, and lets the feed-up below approach from below, taking up mechanical slop).
      const preload = ph.feed_thickness_mm > 0 ? plan.feed_backlash_mm : 0;
      if (preload > 0) {
        add(name, layerNo, "move_rel", FEED, preload, "feed backlash preload down");
        add(name, layerNo, "wait");
      }
      add(name, layerNo, "move_abs", RECOATER, plan.recoater_end_mm);
      add(name, layerNo, "wait");

      // 3) FEED ADVANCE — every phase incl. printing (the feed piston is the powder supply).
      // Net advance stays feed_thickness; the up move also undoes the preload drop.
      if (ph.feed_thickness_mm > 0) {
        add(name, layerNo, "move_rel", FEED, -(ph.feed_thickness_mm + preload), "feed up");
        add(name, layerNo, "wait");
        add(name, layerNo, "dwell", null, plan.settle_s);
        feedPos -= ph.feed_thickness_mm;
      }

      // 4) PRECOAT RETURN vs PRINT.
      if (PRECOAT_PHASES.has(name)) {
        add(name, layerNo, "move_abs", RECOATER, plan.recoater_return_mm);
        add(name, layerNo, "wait");
        add(name, layerNo, "mark", null, null, "layer_end");
        continue;
      }

      // ---- printing ----
      printLayer += 1;
      const capStages = plan.capture_stages ? plan.capture_stages_enabled : [];
      const addCapture = (stage: string) => {
        if (plan.capture_recoater_mm > 0) {
          add(name, layerNo, "move_abs", RECOATER, plan.capture_recoater_mm);
          add(name, layerNo, "wait");
          if (plan.capture_settle_s > 0) add(name, layerNo, "dwell", null, plan.capture_settle_s, "camera settle");
        }
        add(name, layerNo, "mark", null, null, `capture:${stage}`);
        if (plan.capture_hold_s > 0) add(name, layerNo, "dwell", null, plan.capture_hold_s, "camera capture hold");
      };
      if (capStages.includes("pre_jet")) addCapture("pre_jet");
      // Nozzle-purge schedule (firing is external; we only DWELL at the start position so the
      // printhead can fire): every pass, once per layer, or every N printing layers.
      const purgeOn = plan.purge_dwell_s > 0;
      const purgeEveryPass = purgeOn && plan.purge_mode === "every_pass";
      const purgeFirstPass = purgeOn && (plan.purge_mode === "per_layer"
        || (plan.purge_mode === "every_n_layers"
            && (printLayer - 1) % Math.max(plan.purge_every_n_layers, 1) === 0));
      // Concurrent jet + retract: recoater home WHILE the printhead jets; ONE wait covers both.
      // Multipass shuttles the printhead back only to printhead_multipass_return_mm between passes
      // (saves travel), and home on the LAST pass to clear the next recoat.
      add(name, layerNo, "move_abs", RECOATER, plan.recoater_home_mm);
      for (let j = 0; j < plan.n_jet_passes; j++) {
        if (purgeEveryPass || (purgeFirstPass && j === 0)) {
          add(name, layerNo, "move_abs", PRINTHEAD, plan.printhead_start_mm);
          add(name, layerNo, "wait");
          add(name, layerNo, "dwell", null, plan.purge_dwell_s, "nozzle purge");
        }
        add(name, layerNo, "move_abs", PRINTHEAD, plan.printhead_end_mm);
        add(name, layerNo, "wait");
        const last = j === plan.n_jet_passes - 1;
        const back = last ? plan.printhead_home_mm : plan.printhead_multipass_return_mm;
        add(name, layerNo, "move_abs", PRINTHEAD, back);
        add(name, layerNo, "wait");
      }
      if (capStages.includes("post_jet")) addCapture("post_jet");
      if (plan.pre_heater_drop_mm > 0) {
        add(name, layerNo, "move_rel", PART, plan.pre_heater_drop_mm, "pre-heater drop");
        add(name, layerNo, "wait");
      }
      if (plan.heater_enabled) {
        // Heater sweep 425 -> 600 with a slow-follow recoater profile, then restore.
        add(name, layerNo, "move_abs", RECOATER, plan.heater_start_mm);
        add(name, layerNo, "wait");
        add(name, layerNo, "heater", null, 1);
        add(name, layerNo, "set_speed", RECOATER, plan.heater_speed);
        add(name, layerNo, "set_accel", RECOATER, plan.heater_accel);
        add(name, layerNo, "move_abs", RECOATER, plan.heater_end_mm);
        add(name, layerNo, "wait");
        add(name, layerNo, "heater", null, 0);
        add(name, layerNo, "set_speed", RECOATER, ph.recoater_speed);
        add(name, layerNo, "set_accel", RECOATER, ph.recoater_accel);
      }
      if (plan.absolute_layer_seat && PART_DROP_PHASES.has(name) && plan.pre_heater_drop_mm > 0) {
        // Absolute re-seat to the layer plane after the clearance drop/heat (from below). Mirrors backend.
        add(name, layerNo, "seat_part", PART, height, "raise to layer (re-seat)");
        add(name, layerNo, "wait");
      } else if (plan.pre_heater_drop_mm > 0) {
        add(name, layerNo, "move_rel", PART, -plan.pre_heater_drop_mm, "raise to layer");
        add(name, layerNo, "wait");
      }
      if (capStages.includes("post_heat")) addCapture("post_heat");
      // NO end-of-layer recoater reposition. The recoater stays where the spread (home) or the heater
      // sweep (600) left it and moves out to the spread start (950) only at the NEXT layer's start,
      // AFTER that layer's feed preload. Parking it at 950 here made the next preload land too late.
      add(name, layerNo, "mark", null, null, "layer_end");
    }
    if (exhausted) break;
  }

  if (exhausted) return out; // terminal stop: recoater parked home, fault marked, no part->max

  // FINISH: home the gantries, then drive the part cylinder to its max travel.
  add("finish", layerNo, "home", PRINTHEAD);
  add("finish", layerNo, "wait");
  add("finish", layerNo, "home", RECOATER);
  add("finish", layerNo, "wait");
  add("finish", layerNo, "move_abs", PART, plan.part_max_mm);
  add("finish", layerNo, "wait");
  return out;
}

/** Human label for a step, for the print_settings cursor. */
export function describeStep(s: Step | null | undefined): string {
  if (!s) return "—";
  const ax = s.axis ? ({ 1: "build", 2: "feed", 3: "printhead", 4: "recoater" } as Record<number, string>)[s.axis] : "";
  switch (s.kind) {
    case "home": return ax ? `home ${ax}` : "home";
    case "set_speed": return `${ax} speed ${s.value} mm/s`;
    case "set_accel": return `${ax} accel ${s.value} mm/s²`;
    case "move_abs": return `${ax} → ${s.value} mm`;
    case "move_rel": return `${ax} ${s.value! >= 0 ? "+" : ""}${s.value} mm`;
    case "seat_part": return `${ax} seat → ${s.value} mm (abs)`;
    case "wait": return "wait for motion";
    case "dwell": return `dwell ${s.value}s`;
    case "heater": return s.value ? "heater ON" : "heater off";
    case "mark": return s.label === "layer_start" ? `layer ${s.layer} start` : s.label === "feed_exhausted" ? "feed exhausted — stopped" : `layer ${s.layer} done`;
  }
}
