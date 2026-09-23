// Camera-control helpers for the settings panel: which physical camera the operator-side (UVC)
// controls address for a role, and how a browser-side "reset to defaults" is built.

/** GET /api/vision/uvc camera (operator-side UVC controls; macOS). */
export interface UvcCamera { unique_id: string; name: string; science: boolean }

/** The UVC camera a role's controls address. A saved pick wins while that camera is still
 *  attached; science falls back to the bound science camera; overview takes "the other one" only
 *  when exactly one non-science camera is left. Otherwise null: two identical ELPs can't be told
 *  apart from their names, so the operator picks (the live preview shows which one moved). */
export function defaultUvcCamera(role: string, cams: UvcCamera[], saved: string | null): string | null {
  if (saved && cams.some((c) => c.unique_id === saved)) return saved;
  if (cams.length === 1) return cams[0].unique_id;
  if (role === "science") return cams.find((c) => c.science)?.unique_id ?? null;
  const others = cams.filter((c) => !c.science);
  return others.length === 1 && cams.some((c) => c.science) ? others[0].unique_id : null;
}

// Factory defaults read from the ELP 20MP U3 over UVC (GET_MIN/MAX/DEF, captured 2026-09-23 —
// backend/tests/fixtures/uvc/elp_20mp_controls.json). The browser's image-capture controls carry no
// default, so one is applied ONLY when the browser reports this exact range (same raw scale).
const ELP_DEFAULTS: Record<string, { min: number; max: number; def: number }> = {
  brightness: { min: 0, max: 255, def: 128 },
  contrast: { min: 0, max: 128, def: 65 },
  saturation: { min: 0, max: 128, def: 84 },
  sharpness: { min: 0, max: 255, def: 128 },
  colorTemperature: { min: 2800, max: 6500, def: 4650 },
  zoom: { min: 100, max: 200, def: 100 },
};
const AUTO_MODES = ["exposureMode", "whiteBalanceMode", "focusMode"];
// Exposure/focus values follow their auto mode (reset to "continuous" above); size/rate are the
// stream's shape, not image controls.
const NOT_RESET = new Set(["exposureTime", "focusDistance", "frameRate", "width", "height", "aspectRatio"]);

export interface BrowserResetPlan {
  constraints: Record<string, unknown>[]; // one applyConstraints({advanced:[c]}) each
  unknown: string[]; // numeric controls whose factory default the browser can't know
}

/** How to put a browser camera track back to defaults: every auto mode the browser offers goes
 *  back to "continuous", and each numeric control whose range matches the ELP's gets its factory
 *  default. Controls with a different scale are reported, never guessed. */
export function browserResetPlan(caps: Record<string, unknown>): BrowserResetPlan {
  const constraints: Record<string, unknown>[] = [];
  const unknown: string[] = [];
  for (const mode of AUTO_MODES) {
    const opts = caps[mode];
    if (Array.isArray(opts) && opts.includes("continuous")) constraints.push({ [mode]: "continuous" });
  }
  for (const [key, cap] of Object.entries(caps)) {
    if (AUTO_MODES.includes(key) || !cap || typeof cap !== "object" || Array.isArray(cap)) continue;
    const r = cap as { min?: unknown; max?: unknown };
    if (typeof r.min !== "number" || typeof r.max !== "number" || NOT_RESET.has(key)) continue;
    const d = ELP_DEFAULTS[key];
    if (d && d.min === r.min && d.max === r.max) constraints.push({ [key]: d.def });
    else unknown.push(key);
  }
  return { constraints, unknown };
}
