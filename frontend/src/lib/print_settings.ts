/** Mirror of backend/vention_printer_interface/control/print_settings.py: the same plan shape, the
 *  same defaults (V1.py constants) and the same step order, so the UI can preview a print_settings and
 *  show the printability verdict before asking the operator. The backend is the authority. */

export const PART = 1, FEED = 2, PRINTHEAD = 3, RECOATER = 4;
export const PHASES = ["thick_precoat", "thin_precoat", "printing", "postcoat"] as const;
export type Phase = (typeof PHASES)[number];

export interface PhasePlan {
  layer_thickness_mm: number;
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
  thick_precoat: PhasePlan;
  thin_precoat: PhasePlan;
  printing: PhasePlan;
  postcoat: PhasePlan;
  n_jet_passes: number;
  pre_heater_drop_mm: number;
  postcoat_enabled: boolean;
  feed_end_mm: number;
  recoater_home_mm: number;
  recoater_end_mm: number;
  heater_home_mm: number;
  heater_end_mm: number;
  printhead_home_mm: number;
  printhead_end_mm: number;
  heater_speed: number;
  heater_accel: number;
  n_heater_passes: number;
  heater_enabled: boolean;
  settle_s: number;
  feed_fast_speed: number;
  feed_fast_accel: number;
}

const basePhase: PhasePlan = {
  layer_thickness_mm: 2, n_layers: 1, part_speed: 2.5, part_accel: 15, feed_speed: 2.5, feed_accel: 15,
  printhead_speed: 100, printhead_accel: 500, recoater_speed: 100, recoater_accel: 500,
};

export const DEFAULT_PLAN: PrintSettings = {
  thick_precoat: { ...basePhase, layer_thickness_mm: 5, n_layers: 3 },
  thin_precoat: { ...basePhase, layer_thickness_mm: 0.2, n_layers: 2 },
  printing: { ...basePhase, layer_thickness_mm: 2, n_layers: 10 },
  postcoat: { ...basePhase, layer_thickness_mm: 5, n_layers: 1 },
  n_jet_passes: 1, pre_heater_drop_mm: 0, postcoat_enabled: true,
  feed_end_mm: 145, recoater_home_mm: 5, recoater_end_mm: 930, heater_home_mm: 5, heater_end_mm: 600,
  printhead_home_mm: 5, printhead_end_mm: 840, heater_speed: 50, heater_accel: 250, n_heater_passes: 1,
  heater_enabled: false, settle_s: 1, feed_fast_speed: 5, feed_fast_accel: 30,
};

export type StepKind = "home_all" | "set_speed" | "set_accel" | "move_abs" | "move_rel" | "wait" | "dwell" | "heater" | "mark";
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

/** Exact mirror of compile_print(); tested to produce the same kinds/count as the backend. */
export function compilePrint(plan: PrintSettings): Step[] {
  const out: Step[] = [];
  let height = 0;
  const add = (phase: string, layer: number, kind: StepKind, axis: number | null = null, value: number | null = null, label = "") =>
    out.push({ index: out.length, phase, layer, kind, axis, value, label, part_height_mm: height });
  add("setup", 0, "home_all");
  add("setup", 0, "wait");
  add("setup", 0, "set_speed", FEED, plan.feed_fast_speed);
  add("setup", 0, "set_accel", FEED, plan.feed_fast_accel);
  add("setup", 0, "move_abs", FEED, plan.feed_end_mm);
  add("setup", 0, "wait");
  let layerNo = 0;
  for (const name of PHASES) {
    const ph = plan[name];
    if (ph.n_layers === 0) continue;
    add(name, layerNo, "set_speed", PART, ph.part_speed);
    add(name, layerNo, "set_accel", PART, ph.part_accel);
    add(name, layerNo, "set_speed", FEED, ph.feed_speed);
    add(name, layerNo, "set_accel", FEED, ph.feed_accel);
    add(name, layerNo, "set_speed", PRINTHEAD, ph.printhead_speed);
    add(name, layerNo, "set_accel", PRINTHEAD, ph.printhead_accel);
    add(name, layerNo, "set_speed", RECOATER, ph.recoater_speed);
    add(name, layerNo, "set_accel", RECOATER, ph.recoater_accel);
    for (let idx = 0; idx < ph.n_layers; idx++) {
      layerNo++;
      const t = ph.layer_thickness_mm;
      height += t;
      if (name === "printing" && idx > 0) {
        add(name, layerNo, "set_speed", RECOATER, ph.recoater_speed);
        add(name, layerNo, "set_accel", RECOATER, ph.recoater_accel);
      }
      add(name, layerNo, "mark", null, null, "layer_start");
      add(name, layerNo, "move_rel", PART, t);
      add(name, layerNo, "wait");
      add(name, layerNo, "move_abs", RECOATER, plan.recoater_end_mm);
      add(name, layerNo, "wait");
      add(name, layerNo, "move_rel", FEED, -t);
      add(name, layerNo, "wait");
      add(name, layerNo, "dwell", null, plan.settle_s);
      add(name, layerNo, "move_abs", RECOATER, plan.recoater_home_mm);
      add(name, layerNo, "wait");
      if (name === "printing") {
        for (let j = 0; j < plan.n_jet_passes; j++) {
          add(name, layerNo, "move_abs", PRINTHEAD, plan.printhead_end_mm);
          add(name, layerNo, "wait");
          add(name, layerNo, "move_abs", PRINTHEAD, plan.printhead_home_mm);
          add(name, layerNo, "wait");
        }
        if (plan.pre_heater_drop_mm > 0) {
          add(name, layerNo, "move_rel", PART, plan.pre_heater_drop_mm, "pre-heater drop");
          add(name, layerNo, "wait");
        }
        add(name, layerNo, "set_speed", RECOATER, plan.heater_speed);
        add(name, layerNo, "set_accel", RECOATER, plan.heater_accel);
        if (plan.heater_enabled) add(name, layerNo, "heater", null, 1);
        for (let k = 0; k < plan.n_heater_passes; k++) {
          add(name, layerNo, "move_abs", RECOATER, plan.heater_end_mm);
          add(name, layerNo, "wait");
          add(name, layerNo, "move_abs", RECOATER, plan.heater_home_mm);
          add(name, layerNo, "wait");
        }
        if (plan.heater_enabled) add(name, layerNo, "heater", null, 0);
        if (plan.pre_heater_drop_mm > 0) {
          add(name, layerNo, "move_rel", PART, -plan.pre_heater_drop_mm, "raise back to layer");
          add(name, layerNo, "wait");
        }
      }
      add(name, layerNo, "mark", null, null, "layer_end");
    }
  }
  return out;
}

/** Human label for a step, for the print_settings cursor. */
export function describeStep(s: Step | null | undefined): string {
  if (!s) return "—";
  const ax = s.axis ? ({ 1: "part", 2: "feed", 3: "printhead", 4: "recoater" } as Record<number, string>)[s.axis] : "";
  switch (s.kind) {
    case "home_all": return "home all";
    case "set_speed": return `${ax} speed ${s.value} mm/s`;
    case "set_accel": return `${ax} accel ${s.value} mm/s²`;
    case "move_abs": return `${ax} → ${s.value} mm`;
    case "move_rel": return `${ax} ${s.value! >= 0 ? "+" : ""}${s.value} mm`;
    case "wait": return "wait for motion";
    case "dwell": return `dwell ${s.value}s`;
    case "heater": return s.value ? "heater ON" : "heater off";
    case "mark": return s.label === "layer_start" ? `layer ${s.layer} start` : `layer ${s.layer} done`;
  }
}
