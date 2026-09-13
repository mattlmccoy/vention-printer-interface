/** Pure UI logic for the layerwise-vision feature: stream URL, capture-manifest parsing, and
 *  per-view overview-panel visibility persisted under localStorage["vpi.vision.panels.v1"]
 *  (storage injected, guarded the same way console.ts guards localStorage — see console.ts). */
import type { View } from "./console.ts";

/** The overview camera's live MJPEG stream, same-origin ("") or against an explicit operator base. */
export function overviewStreamUrl(base: string): string {
  return `${base}/api/vision/overview/stream`;
}

export interface Capture { layer: number; stage: string; url: string }

// pre_jet < post_jet < post_heat — the order captures happen within a printing layer.
const STAGE_ORDER: Record<string, number> = { pre_jet: 0, post_jet: 1, post_heat: 2 };

/** Maps `GET /api/vision/captures?run=<run>` manifest records (see backend
 *  vision/capture.py's append_manifest call: {run_id, layer, stage, registered,
 *  host_timestamp_ns}) into sorted {layer, stage, url} entries. Records missing/malformed
 *  layer, stage, or a path field are dropped rather than guessed at. */
export function parseCaptures(manifest: unknown[]): Capture[] {
  const out: Capture[] = [];
  for (const rec of manifest) {
    if (!rec || typeof rec !== "object") continue;
    const r = rec as Record<string, unknown>;
    const layer = r.layer;
    const stage = r.stage;
    const url = r.registered ?? r.url;
    if (typeof layer !== "number" || typeof stage !== "string" || typeof url !== "string") continue;
    out.push({ layer, stage, url });
  }
  return out.sort((a, b) => a.layer - b.layer || (STAGE_ORDER[a.stage] ?? 99) - (STAGE_ORDER[b.stage] ?? 99));
}

const PANEL_KEY = "vpi.vision.panels.v1";

function loadPanels(storage: Storage | null): Partial<Record<View, boolean>> {
  try {
    const raw = storage?.getItem(PANEL_KEY);
    if (!raw) return {};
    const p = JSON.parse(raw) as Record<string, unknown>;
    const out: Partial<Record<View, boolean>> = {};
    for (const [k, v] of Object.entries(p)) if (typeof v === "boolean") out[k as View] = v;
    return out;
  } catch { return {}; }
}

/** Default visible = true; an unset or corrupt entry never hides the panel. */
export function panelVisible(view: View, storage: Storage | null): boolean {
  return loadPanels(storage)[view] ?? true;
}

export function setPanelVisible(view: View, visible: boolean, storage: Storage | null): void {
  try {
    const p = loadPanels(storage);
    p[view] = visible;
    storage?.setItem(PANEL_KEY, JSON.stringify(p));
  } catch { /* ignore */ }
}
