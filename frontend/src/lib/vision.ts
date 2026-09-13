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

/** Camera auto-connect + quick-start (A7): the minimal shape read off `GET /api/vision/status`
 *  (see backend vention_printer_interface/api/app.py's vision_status) — kept local rather than
 *  imported from api.ts so this pure module has no dependency on the fetch layer. */
export interface VisionStatusLike { roles_resolved: boolean; unresolved: string[] }

const QUICKSTART_DISMISS_KEY = "vpi.vision.quickstart_dismissed.v1";

/** A stable, order-independent signature for a set of unresolved roles, used as the "device-set"
 *  a dismissal is recorded against — so a dismissal survives while nothing changes, but a later
 *  camera swap that leaves a *different* role unresolved re-opens the wizard instead of being
 *  silently swallowed by a stale dismissal. */
function unresolvedSignature(unresolved: string[]): string {
  return [...unresolved].sort().join(",");
}

/** True when the first-run camera-role wizard should be shown: roles are not fully resolved
 *  AND the operator has not already dismissed the wizard for this exact unresolved set. `null`
 *  status (not loaded yet, or the endpoint failed) never shows it — showing a setup wizard on
 *  missing data would be a false prompt, not a real gap (data-contract-verification). */
export function shouldShowQuickStart(status: VisionStatusLike | null, storage: Storage | null): boolean {
  if (!status || status.roles_resolved) return false;
  let dismissedSig: string | null = null;
  try { dismissedSig = storage?.getItem(QUICKSTART_DISMISS_KEY) ?? null; } catch { dismissedSig = null; }
  return dismissedSig !== unresolvedSignature(status.unresolved);
}

/** Record that the operator dismissed the wizard for the current unresolved set. Reopening it
 *  from Settings is a separate, explicit action (component-local state) — this only suppresses
 *  the automatic on-connect prompt for this exact device-set going forward. */
export function dismissQuickStart(status: VisionStatusLike, storage: Storage | null): void {
  try { storage?.setItem(QUICKSTART_DISMISS_KEY, unresolvedSignature(status.unresolved)); } catch { /* ignore */ }
}
