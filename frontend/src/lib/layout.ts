/** Studio layout state: which panels are open, which rail sections, which tool. Pure reducer +
 *  validated persistence under localStorage["vpi.layout.v1"] (FLIR pattern, printer subset). */

export const TOOLS = ["jog", "home", "recipe", "measure"] as const;
export const SECTIONS = ["connection", "arm", "axes", "heater", "recipe", "recording"] as const;
export type Tool = (typeof TOOLS)[number];
export type Panel = "strip" | "rail" | "dock";
export type Section = (typeof SECTIONS)[number];
export interface FloatRect { x: number; y: number; w: number; h: number }

export interface LayoutState {
  strip: boolean;
  rail: boolean;
  dock: boolean;
  railW: number;
  dockH: number;
  tool: Tool;
  /** Plot window in seconds. */
  plotWindowS: number;
  floating: Partial<Record<Section, FloatRect>>;
  sections: Record<Section, boolean>;
}

export const RAIL_W = { min: 280, max: 760, default: 400, snap: 24 } as const;
export const DOCK_H = { min: 140, max: 620, default: 260, snap: 24 } as const;
export const PLOT_WINDOWS = [30, 120, 600, 3600] as const;
function snapClamp(v: number, cfg: { min: number; max: number; default: number; snap: number }): number {
  const snapped = Math.abs(v - cfg.default) <= cfg.snap ? cfg.default : v;
  return Math.min(cfg.max, Math.max(cfg.min, snapped));
}
export const clampRailW = (w: number): number => snapClamp(w, RAIL_W);
export const clampDockH = (h: number): number => snapClamp(h, DOCK_H);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
function clampRect(r: FloatRect): FloatRect {
  return { x: Math.max(0, r.x), y: Math.max(0, r.y), w: Math.max(260, r.w), h: Math.max(160, r.h) };
}
function parseFloating(v: unknown): Partial<Record<Section, FloatRect>> {
  const out: Partial<Record<Section, FloatRect>> = {};
  if (!v || typeof v !== "object") return out;
  for (const [k, r] of Object.entries(v as Record<string, unknown>)) {
    const q = r as Record<string, unknown> | null;
    if ((SECTIONS as readonly string[]).includes(k) && q && isNum(q.x) && isNum(q.y) && isNum(q.w) && isNum(q.h)) out[k as Section] = clampRect({ x: q.x, y: q.y, w: q.w, h: q.h });
  }
  return out;
}

export function studioClasses(
  layout: LayoutState,
  opts: { page: boolean; hasStrip: boolean; hasRail: boolean; hasDock: boolean },
): { className: string; showStrip: boolean; showRail: boolean; showDock: boolean } {
  const { page, hasStrip, hasRail, hasDock } = opts;
  const showStrip = !page && layout.strip && hasStrip;
  const showRail = layout.rail && hasRail;
  const showDock = !page && layout.dock && hasDock;
  const className = ["studio", page ? "page" : "", showStrip ? "" : "no-strip", showRail ? "" : "no-rail", showDock ? "" : "no-dock"].filter(Boolean).join(" ");
  return { className, showStrip, showRail, showDock };
}

export const DEFAULT_LAYOUT: LayoutState = {
  strip: true, rail: true, dock: true, railW: RAIL_W.default, dockH: DOCK_H.default, tool: "jog",
  plotWindowS: 120, floating: {},
  sections: { connection: true, arm: true, axes: true, heater: true, recipe: true, recording: false },
};
Object.freeze(DEFAULT_LAYOUT.sections);
Object.freeze(DEFAULT_LAYOUT);

export type LayoutAction =
  | { type: "toggle"; panel: Panel }
  | { type: "setRailW"; w: number }
  | { type: "setDockH"; h: number }
  | { type: "toggleSection"; section: Section }
  | { type: "openSection"; section: Section }
  | { type: "setTool"; tool: Tool }
  | { type: "setPlotWindow"; s: number }
  | { type: "popOut"; section: Section }
  | { type: "moveFloat"; section: Section; rect: FloatRect }
  | { type: "dockBack"; section: Section }
  | { type: "collapseAll" }
  | { type: "restoreAll" };

export function layoutReducer(s: LayoutState, a: LayoutAction): LayoutState {
  switch (a.type) {
    case "toggle": return { ...s, [a.panel]: !s[a.panel] };
    case "setRailW": return { ...s, railW: clampRailW(a.w) };
    case "setDockH": return { ...s, dockH: clampDockH(a.h) };
    case "toggleSection": return { ...s, sections: { ...s.sections, [a.section]: !s.sections[a.section] } };
    case "openSection": return { ...s, rail: true, sections: { ...s.sections, [a.section]: true } };
    case "setTool": return { ...s, tool: a.tool };
    case "setPlotWindow": return { ...s, plotWindowS: (PLOT_WINDOWS as readonly number[]).includes(a.s) ? a.s : s.plotWindowS };
    case "popOut": { const n = Object.keys(s.floating).length; return { ...s, floating: { ...s.floating, [a.section]: s.floating[a.section] ?? { x: 80 + n * 30, y: 80 + n * 30, w: 420, h: 360 } } }; }
    case "moveFloat": return { ...s, floating: { ...s.floating, [a.section]: clampRect(a.rect) } };
    case "dockBack": { const { [a.section]: _gone, ...rest } = s.floating; return { ...s, floating: rest }; }
    case "collapseAll": return { ...s, strip: true, rail: false, dock: false };
    case "restoreAll": return { ...s, strip: true, rail: true, dock: true };
  }
}

const KEY = "vpi.layout.v1";
const asRecord = (v: unknown): Record<string, unknown> => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const bool = (v: unknown, fb: boolean): boolean => (typeof v === "boolean" ? v : fb);
const num = (v: unknown, fb: number): number => (isNum(v) ? v : fb);
const isTool = (v: unknown): v is Tool => typeof v === "string" && (TOOLS as readonly string[]).includes(v);

export function loadLayout(storage: Storage | null): LayoutState {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const p = asRecord(JSON.parse(raw));
    const sec = asRecord(p.sections);
    return {
      strip: bool(p.strip, DEFAULT_LAYOUT.strip), rail: bool(p.rail, DEFAULT_LAYOUT.rail), dock: bool(p.dock, DEFAULT_LAYOUT.dock),
      railW: clampRailW(num(p.railW, DEFAULT_LAYOUT.railW)), dockH: clampDockH(num(p.dockH, DEFAULT_LAYOUT.dockH)),
      tool: isTool(p.tool) ? p.tool : DEFAULT_LAYOUT.tool,
      plotWindowS: (PLOT_WINDOWS as readonly number[]).includes(num(p.plotWindowS, 0)) ? (p.plotWindowS as number) : DEFAULT_LAYOUT.plotWindowS,
      floating: parseFloating(p.floating),
      sections: Object.fromEntries(SECTIONS.map((k) => [k, bool(sec[k], DEFAULT_LAYOUT.sections[k])])) as Record<Section, boolean>,
    };
  } catch { return DEFAULT_LAYOUT; }
}

export function saveLayout(storage: Storage | null, s: LayoutState): void {
  try { storage?.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable */ }
}
