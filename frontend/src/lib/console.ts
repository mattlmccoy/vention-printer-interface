/** Console UI state persisted under localStorage["vpi.console.v1"]: active view and jog steps. */
export const VIEWS = ["print", "prepare", "control", "runs"] as const;
export type View = (typeof VIEWS)[number];
export const JOG_STEPS = [0.1, 1, 10, 100] as const;
export interface ConsoleState { view: View; gantryStep: number; pistonStep: number; plotWindowS: number }
export const DEFAULT_CONSOLE: ConsoleState = Object.freeze({ view: "print", gantryStep: 10, pistonStep: 1, plotWindowS: 120 }) as ConsoleState;
const KEY = "vpi.console.v1";
const isView = (v: unknown): v is View => typeof v === "string" && (VIEWS as readonly string[]).includes(v);
const isStep = (v: unknown): v is number => typeof v === "number" && (JOG_STEPS as readonly number[]).includes(v);

export function loadConsole(storage: Storage | null): ConsoleState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_CONSOLE;
    const p = JSON.parse(raw) as Record<string, unknown>;
    return {
      view: isView(p.view) ? p.view : DEFAULT_CONSOLE.view,
      gantryStep: isStep(p.gantryStep) ? p.gantryStep : DEFAULT_CONSOLE.gantryStep,
      pistonStep: isStep(p.pistonStep) ? p.pistonStep : DEFAULT_CONSOLE.pistonStep,
      plotWindowS: typeof p.plotWindowS === "number" && p.plotWindowS > 0 ? p.plotWindowS : DEFAULT_CONSOLE.plotWindowS,
    };
  } catch { return DEFAULT_CONSOLE; }
}
export function saveConsole(storage: Storage | null, s: ConsoleState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ }
}
