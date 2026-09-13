/** Pure UI logic for the layerwise-vision feature: stream URL, capture-manifest parsing, and
 *  per-view overview-panel visibility persisted under localStorage["vpi.vision.panels.v1"]
 *  (storage injected, guarded the same way console.ts guards localStorage — see console.ts). */
import type { View } from "./console.ts";

/** The overview camera's live MJPEG stream, same-origin ("") or against an explicit operator base. */
export function overviewStreamUrl(base: string): string {
  return `${base}/api/vision/overview/stream`;
}

export interface Capture { layer: number; stage: string; url: string; sidecarUrl?: string }

// pre_jet < post_jet < post_heat — the order captures happen within a printing layer.
const STAGE_ORDER: Record<string, number> = { pre_jet: 0, post_jet: 1, post_heat: 2 };

/** Maps `GET /api/vision/captures?run=<run>` manifest records (see backend
 *  vention_printer_interface/api/app.py's vision_captures, which enriches each
 *  {run_id, layer, stage, registered, host_timestamp_ns} manifest record with ready-to-use
 *  `url`/`sidecar_url` fields pointing at GET /api/vision/runs/{run}/file) into sorted
 *  {layer, stage, url, sidecarUrl} entries. The backend-provided `url` is used when present;
 *  a record without one (an older/un-enriched fixture) falls back to the bare `registered`
 *  path, matching prior behavior. Records missing/malformed layer, stage, or a path field are
 *  dropped rather than guessed at. */
export function parseCaptures(manifest: unknown[]): Capture[] {
  const out: Capture[] = [];
  for (const rec of manifest) {
    if (!rec || typeof rec !== "object") continue;
    const r = rec as Record<string, unknown>;
    const layer = r.layer;
    const stage = r.stage;
    const url = r.url ?? r.registered;
    if (typeof layer !== "number" || typeof stage !== "string" || typeof url !== "string") continue;
    const capture: Capture = { layer, stage, url };
    if (typeof r.sidecar_url === "string") capture.sidecarUrl = r.sidecar_url;
    out.push(capture);
  }
  return out.sort((a, b) => a.layer - b.layer || (STAGE_ORDER[a.stage] ?? 99) - (STAGE_ORDER[b.stage] ?? 99));
}

/** Pure formatting core for the capture browser's sidecar-metadata display: an absent value
 *  (null/undefined — the backend's sidecar template default for anything not populated) always
 *  renders as "—", never invented or silently blanked. Never throws on an object/array value. */
export function formatCaptureMetaValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
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
