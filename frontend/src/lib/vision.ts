/** Pure UI logic for the layerwise-vision feature: stream URL, capture-manifest parsing, and
 *  per-view overview-panel visibility persisted under localStorage["vpi.vision.panels.v1"]
 *  (storage injected, guarded the same way console.ts guards localStorage — see console.ts). */
import type { View } from "./console.ts";

/** The overview camera's live MJPEG stream, same-origin ("") or against an explicit operator base. */
export function overviewStreamUrl(base: string): string {
  return `${base}/api/vision/overview/stream`;
}

export interface Capture {
  layer: number; // absolute layer_no (includes precoats)
  cadLayer?: number; // 1-based PRINTING layer index (excludes precoats) — use for the CAD-slice lookup
  stage: string;
  url: string;
  sidecarUrl?: string;
}

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
    if (typeof r.cad_layer === "number") capture.cadLayer = r.cad_layer;
    if (typeof r.sidecar_url === "string") capture.sidecarUrl = r.sidecar_url;
    out.push(capture);
  }
  return out.sort((a, b) => a.layer - b.layer || (STAGE_ORDER[a.stage] ?? 99) - (STAGE_ORDER[b.stage] ?? 99));
}

/** Human label that distinguishes the PRINTING layer from the absolute build layer (which includes
 *  precoats) — so "build layer 6" is never mistaken for the 6th printing layer. Falls back to the
 *  bare layer for captures with no printing index (older runs). */
export function captureLayerFull(c: { layer: number; cadLayer?: number }): string {
  return c.cadLayer != null ? `printing layer ${c.cadLayer} · build layer ${c.layer}` : `layer ${c.layer}`;
}

/** Compact badge form: "P<printing>" when the printing index is known, else "L<build>". */
export function captureLayerShort(c: { layer: number; cadLayer?: number }): string {
  return c.cadLayer != null ? `P${c.cadLayer}` : `L${c.layer}`;
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

/** `camera_access` as reported by `GET /api/vision/devices` (see backend
 *  vention_printer_interface/vision/cameras.py's `camera_access_state`). */
export type CameraAccessStatus = "ok" | "unknown" | "denied" | "no_devices";

/** User-facing message for a camera-access state, shown in place of an empty/silent device list
 *  so a macOS Privacy & Security permission block reads as an actionable message instead of a
 *  confusing "no cameras" result (data-contract-verification: unknown/blocked must never render
 *  as healthy). `"ok"` returns "" — nothing to surface when access is fine. */
export function cameraAccessMessage(status: CameraAccessStatus): string {
  switch (status) {
    case "denied":
      return "Camera permission not granted — enable it in System Settings → Privacy & Security → Camera, then rescan";
    case "no_devices":
      return "No cameras detected — check the USB connection, then rescan";
    case "unknown":
      // Devices identified from OS metadata but not opened — access verified when a camera is used.
      return "";
    case "ok":
      return "";
  }
}

/** The guided calibration-capture session shape from GET/POST /api/vision/calibrate/session
 *  (see backend vention_printer_interface/api/app.py's `_calib_session_state`). */
export interface CalibSessionLike { n_views: number }

/** True once the accumulated session has enough views to finalize — mirrors the backend's own
 *  `_MIN_CALIB_VIEWS = 3` gate (app.py), computed here too so the UI can disable Finalize without
 *  waiting on a round trip. */
export function calibrationReady(session: CalibSessionLike): boolean {
  return session.n_views >= 3;
}

/** The POST /api/vision/validate result shape (see backend vention_printer_interface/api/app.py's
 *  vision_validate: {rms_mm, max_mm, per_point, scale_bias, n_points}) — only the three scored
 *  fields this formatter needs. */
export interface ValidationResultLike { rms_mm: number; max_mm: number; scale_bias: number }

export interface FormattedValidation { rmsMm: number; maxMm: number; scaleBias: number; pass: boolean }

/** Pure PASS/FAIL scoring for a validate result against a dimensional target (protocol default
 *  +/-0.1 mm). `tolMm` does double duty: an absolute-mm bound on `max_mm`, and (reused as a
 *  fraction) a bound on how far `scale_bias` may drift from 1 — the rigid, no-scale residual fit
 *  behind rms_mm/max_mm deliberately does NOT absorb a uniform scale error, so scale_bias is the
 *  only thing that catches it; without this second check a mis-scaled calibration could still
 *  report a deceptively tight rms/max. */
export function formatValidation(result: ValidationResultLike, tolMm = 0.1): FormattedValidation {
  const rmsMm = result.rms_mm;
  const maxMm = result.max_mm;
  const scaleBias = result.scale_bias;
  const pass = maxMm <= tolMm && Math.abs(scaleBias - 1) <= tolMm;
  return { rmsMm, maxMm, scaleBias, pass };
}

export interface IndexedCapture { cap: Capture; index: number }

/** Filter captures by stage for the Runs stills grid (#1) while preserving each capture's ORIGINAL
 *  index in `caps` — the lightbox indexes into the full `caps` array, so the grid must hand it the
 *  unfiltered index, not the post-filter position. `selectedStages` empty = nothing shown. Pure. */
export function visibleCaptures(caps: readonly Capture[], selectedStages: readonly string[]): IndexedCapture[] {
  const sel = new Set(selectedStages);
  const out: IndexedCapture[] = [];
  caps.forEach((cap, index) => { if (sel.has(cap.stage)) out.push({ cap, index }); });
  return out;
}
