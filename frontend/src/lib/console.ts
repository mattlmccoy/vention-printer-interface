/** Console UI state persisted under localStorage["vpi.console.v1"]: active view, jog steps,
 *  module order per view, read-only-connect preference. */
export const VIEWS = ["control", "priming", "print", "job", "runs"] as const;
export type View = (typeof VIEWS)[number];
export const JOG_STEPS = [0.1, 1, 10, 100] as const;
export interface ModuleSize { w: number; h: number }
export interface ConsoleState {
  view: View;
  gantryStep: number;
  pistonStep: number;
  order: Partial<Record<View, string[]>>;
  /** Per-view, per-module pixel overrides set by dragging the resize handle. */
  sizes: Partial<Record<View, Record<string, ModuleSize>>>;
  readOnlyConnect: boolean;
}
export const DEFAULT_CONSOLE: ConsoleState = Object.freeze({ view: "print", gantryStep: 10, pistonStep: 1, order: {}, sizes: {}, readOnlyConnect: false }) as ConsoleState;
export const MODULE_MIN = { w: 240, h: 120 } as const;
export const MODULE_MAX = { w: 1400, h: 900 } as const;

/** Clamp a dragged module size into sane bounds. Pure. */
export function clampSize(w: number, h: number): ModuleSize {
  return {
    w: Math.round(Math.min(MODULE_MAX.w, Math.max(MODULE_MIN.w, w))),
    h: Math.round(Math.min(MODULE_MAX.h, Math.max(MODULE_MIN.h, h))),
  };
}
const KEY = "vpi.console.v1";
const isView = (v: unknown): v is View => typeof v === "string" && (VIEWS as readonly string[]).includes(v);
const isStep = (v: unknown): v is number => typeof v === "number" && (JOG_STEPS as readonly number[]).includes(v);

/** Order of module ids for a view: persisted order first (only known ids), then any new ids. */
export function moduleOrder(saved: string[] | undefined, known: string[]): string[] {
  const kept = (saved ?? []).filter((id) => known.includes(id));
  return [...kept, ...known.filter((id) => !kept.includes(id))];
}

/** Move `id` so it sits before `beforeId` (or at the end when beforeId is null). Pure. */
export function moveModule(order: string[], id: string, beforeId: string | null): string[] {
  if (id === beforeId) return order;
  const rest = order.filter((x) => x !== id);
  if (beforeId === null) return [...rest, id];
  const i = rest.indexOf(beforeId);
  return i < 0 ? [...rest, id] : [...rest.slice(0, i), id, ...rest.slice(i)];
}

export function loadConsole(storage: Storage | null): ConsoleState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_CONSOLE;
    const p = JSON.parse(raw) as Record<string, unknown>;
    const order: Partial<Record<View, string[]>> = {};
    const po = (p.order ?? {}) as Record<string, unknown>;
    for (const v of VIEWS) if (Array.isArray(po[v])) order[v] = (po[v] as unknown[]).filter((x): x is string => typeof x === "string");
    const sizes: Partial<Record<View, Record<string, ModuleSize>>> = {};
    const ps = (p.sizes ?? {}) as Record<string, unknown>;
    for (const v of VIEWS) {
      const m = ps[v];
      if (m && typeof m === "object") {
        const out: Record<string, ModuleSize> = {};
        for (const [id, sz] of Object.entries(m as Record<string, unknown>)) {
          const o = sz as Record<string, unknown>;
          if (typeof o?.w === "number" && typeof o?.h === "number") out[id] = clampSize(o.w, o.h);
        }
        if (Object.keys(out).length) sizes[v] = out;
      }
    }
    return {
      view: isView(p.view) ? p.view : DEFAULT_CONSOLE.view,
      gantryStep: isStep(p.gantryStep) ? p.gantryStep : DEFAULT_CONSOLE.gantryStep,
      pistonStep: isStep(p.pistonStep) ? p.pistonStep : DEFAULT_CONSOLE.pistonStep,
      order,
      sizes,
      readOnlyConnect: p.readOnlyConnect === true,
    };
  } catch { return DEFAULT_CONSOLE; }
}
export function saveConsole(storage: Storage | null, s: ConsoleState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* ignore */ }
}
