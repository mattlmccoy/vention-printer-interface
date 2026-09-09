/** Mirror of backend estimate_duration_s(): constant-velocity moves, dwells, homing. */
import { compilePrint, type PrintSettings } from "./print_settings.ts";

const HOMING: Record<number, number> = { 1: 68.8, 2: 68.8, 3: 66.3, 4: 66.3 };
const TRAVEL: Record<number, number> = { 1: 145, 2: 145, 3: 840, 4: 930 };

export function estimateDurationS(plan: PrintSettings, minWaitS = 0.5): number {
  const speed: Record<number, number> = { 1: 5, 2: 5, 3: 100, 4: 100 };
  const pos: Record<number, number> = { 1: 0, 2: 0, 3: 0, 4: 0 };
  let total = 0, pending = 0;
  for (const s of compilePrint(plan)) {
    if (s.kind === "home_all") pending = Math.max(...Object.keys(speed).map((a) => TRAVEL[+a] / HOMING[+a])) * 0.5;
    else if (s.kind === "set_speed" && s.axis) speed[s.axis] = Math.max(s.value ?? 0.1, 0.1);
    else if ((s.kind === "move_abs" || s.kind === "move_rel") && s.axis) {
      const target = s.kind === "move_abs" ? (s.value ?? 0) : pos[s.axis] + (s.value ?? 0);
      pending = Math.max(pending, Math.abs(target - pos[s.axis]) / speed[s.axis]);
      pos[s.axis] = target;
    } else if (s.kind === "wait") { total += Math.max(pending, minWaitS); pending = 0; }
    else if (s.kind === "dwell") total += s.value ?? 0;
  }
  return Math.round((total + pending) * 10) / 10;
}

/** Heater on-time over the whole print: passes × (2 × heater travel / heater speed). */
export function heaterOnTimeS(plan: PrintSettings): number {
  if (!plan.heater_enabled) return 0;
  const per = (2 * (plan.heater_end_mm - plan.heater_home_mm)) / Math.max(plan.heater_speed, 0.1);
  return Math.round(plan.printing.n_layers * plan.n_heater_passes * per);
}
