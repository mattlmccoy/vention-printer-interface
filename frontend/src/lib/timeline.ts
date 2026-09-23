import { cleanNum } from "./format.ts";
import { describeStep, type PrintSettings, type Step } from "./print_settings.ts";

/** Bookkeeping steps hidden from the operator-facing timeline (they carry no visible action). */
export const TIMELINE_NOISE = new Set<Step["kind"]>(["set_speed", "set_accel", "wait"]);

/** Friendly phase names for the current-stage readout. */
export const PHASE_LABEL: Record<string, string> = {
  thin_precoat: "precoat", printing: "printing", postcoat: "postcoat", setup: "setup", finish: "finishing",
};

/** Plain-language description of one compiled step, for the timeline and the current-stage readout. */
export function phrase(step: Step | null, plan: PrintSettings | null): string {
  if (!step || !plan) return "";
  const v = step.value ?? 0;
  switch (step.kind) {
    case "home": return step.axis ? `homing ${({ 1: "build", 2: "feed", 3: "printhead", 4: "recoater" } as Record<number, string>)[step.axis]}` : "homing";
    case "move_rel": return step.axis === 1 ? `build piston down ${cleanNum(v, 3)} mm` : `feed piston up ${cleanNum(Math.abs(v), 3)} mm`;
    case "move_abs":
      if (step.axis === 4) return v === plan.recoater_end_mm ? "spreading powder" : v === plan.heater_end_mm ? "heater pass" : "recoater returning";
      if (step.axis === 3) return v === plan.printhead_end_mm ? "printhead pass" : "printhead returning";
      if (step.axis === 2) return `feed piston to ${cleanNum(v, 3)} mm`;
      return `build piston to ${cleanNum(v, 3)} mm`;
    case "dwell": return "settling";
    case "heater": return v ? "heater on" : "heater off";
    case "wait": return "waiting for motion";
    default: return describeStep(step);
  }
}

/** The `index` of the timeline row that is currently active — the last row at or before the running
 *  step — or -1 when none has started yet. */
export function currentTimelineIndex(rows: Step[], activeStepIdx: number): number {
  let cur = -1;
  for (const s of rows) {
    if (s.index <= activeStepIdx) cur = s.index;
    else break;
  }
  return cur;
}

export interface CurrentStage {
  /** Friendly phase + layer, e.g. "printing · layer 12". */
  group: string;
  /** Plain-language action, e.g. "spreading powder". */
  action: string;
  /** The compiled-step index of the active row (for scroll/highlight anchoring). */
  stepIndex: number;
}

/** Summarize the currently-active timeline row for the "now" readout under the timeline. Null when
 *  no row is active yet (before the first meaningful step, or no rows). */
export function currentStage(rows: Step[], activeStepIdx: number, plan: PrintSettings | null): CurrentStage | null {
  const idx = currentTimelineIndex(rows, activeStepIdx);
  if (idx < 0) return null;
  const s = rows.find((r) => r.index === idx);
  if (!s) return null;
  return {
    group: `${PHASE_LABEL[s.phase] ?? s.phase}${s.layer ? ` · layer ${s.layer}` : ""}`,
    action: phrase(s, plan) || describeStep(s),
    stepIndex: s.index,
  };
}
