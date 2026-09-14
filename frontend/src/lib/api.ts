/** REST client. Every state-changing call carries X-VPI-Client: 1 (the operator's cross-origin
 *  guard). Method + path per call are locked by api.test.ts so a Save can never silently 405. */

import { apiUrl, loadOperatorBase } from "./operator.ts";
import type { StatusPayload } from "./telemetry.ts";

export const SITE_MODE = import.meta.env?.VITE_SITE_MODE === "1";
export const CLIENT_HEADER = "X-VPI-Client";
let base = loadOperatorBase(typeof localStorage === "undefined" ? null : localStorage, { siteMode: SITE_MODE });
export function operatorBase(): string { return base; }
export function setOperatorBase(b: string): void { base = b; }

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET" && method !== "HEAD") headers[CLIENT_HEADER] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(apiUrl(base, path), { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? String((data as { detail: unknown }).detail) : text || res.statusText;
    throw new ApiError(res.status, `${res.status} ${detail}`);
  }
  return data as T;
}

export interface Health { version: string; api_version: string; backend: string; platform: string }
export interface Discovery { candidates: Array<{ backend: string; ip: string | null; label?: string; reachable: boolean }>; connected: { backend: string } }
export interface PrintSettingsPayload { plan: Record<string, unknown>; validation: string[]; n_steps: number; estimated_duration_s: number; total_layers: number; total_thickness_mm: number; bounds: Record<string, unknown>; limits: Record<string, unknown>; exposure: { energy_j: number; time_s: number; sweep_speed_mm_s: number } }
export interface AxisMotion { max_speed: number | null; max_accel: number | null; bounds: { max_speed: [number, number]; max_accel: [number, number] }; limit_speed: number; limit_accel: number }
export interface PrimingPayload { settings: Record<string, number>; validation: string[]; n_steps: number; n_thick_precoats: number; limits: Record<string, unknown> }
export interface PrimedPayload { primed: { part_mm: number; feed_mm: number; captured_at: number } | null }
export interface VisionStatus { cameras: string[]; calibration: string | null; queue: { drops: number }; active: boolean; roles_resolved: boolean; unresolved: string[] }
export interface VisionCameraSpec { role: string; index: number; path: string | null; backend: number | null; width: number | null; height: number | null }
export interface VisionCameras { overview: VisionCameraSpec; science: VisionCameraSpec }
// GET /api/vision/devices (A7) — see backend vention_printer_interface/api/app.py's
// vision_devices: `role` is resolved via resolve_roles against the persisted role map (so an
// unmapped device sitting at a role's default index can still show that role — resolved, but
// not operator-confirmed, is exactly what `roles_resolved`/`unresolved` distinguish for).
// `has_frame` mirrors vision/cameras.py's enumerate_devices probe: whether a fresh read() off
// this device actually returned a frame (null when the enumerator didn't report it).
export interface VisionDevice { index: number; stable_id: string | null; name: string | null; role: string | null; preview_url: string | null; has_frame: boolean | null }
// Overall camera-permission signal aggregated across every enumerated device — see backend
// vention_printer_interface/vision/cameras.py's camera_access_state. "unknown" = cameras were
// IDENTIFIED from OS metadata (by name/USB id) but never opened, so access isn't verified yet —
// NOT an error; the devices are still listable/assignable. ok/denied/no_devices as before.
export interface VisionDevicesResponse { devices: VisionDevice[]; camera_access: "ok" | "unknown" | "denied" | "no_devices" }
// GET/PUT /api/vision/roles body/response shape: a stable_id -> role ("overview"/"science") map.
export interface RunMeta { run: string; complete: boolean; size_bytes: number; name?: string; notes?: string; started_at?: string | number | null; layer_count?: number | null; duration_s?: number | null }
// Lane A dimensional analysis — GET/POST /api/analysis/{run}/dimensional (see backend
// vention_printer_interface/analysis/dimensional.py DimensionalReport). Non-"ok" statuses are
// honest 200 reports with features:{} and compensation:null — never fabricated metrics.
export type AnalysisStatus = "ok" | "no_capture" | "no_calibration" | "roi_failed" | "not_run";
export interface Compensation { scale_x: number; scale_y: number; yaw_deg: number | null; human: string; notes: string[]; deadband_pct?: number }
export interface DimensionalReport {
  run: string; status: AnalysisStatus; generated_utc?: string; message?: string;
  captured_from?: { layer?: number; stage?: string } | null; px_per_mm?: number | null; mm_per_px?: number | null;
  rois?: Record<string, [number, number, number, number]> | null;
  features?: Record<string, Record<string, number | null>>;
  compensation?: Compensation | null;
  tool_provenance?: Record<string, unknown>;
}
export interface AnalysisRequest { layer?: number; stage?: string; rois?: Record<string, [number, number, number, number]>; nominals?: Record<string, unknown> }
export type VisionRoleMap = Record<string, string>;
export interface CameraSettings { resolution?: [number, number] | string | null; fps?: number | null; format?: string | null; exposure?: number | null }
export interface VisionRolesPutResult { mapping: VisionRoleMap; roles_resolved: boolean; unresolved: string[] }
// Raw manifest record shape from GET /api/vision/captures — see backend
// vention_printer_interface/vision/capture.py's append_manifest call (run_id..host_timestamp_ns)
// plus the url/sidecar_url fields vention_printer_interface/api/app.py's vision_captures adds,
// pointing at GET /api/vision/runs/{run}/file.
export interface VisionCaptureRecord {
  run_id: string; layer: number; stage: string; registered: string; host_timestamp_ns: number;
  url?: string; sidecar_url?: string;
}
export interface VisionCalibrateBody { image_points: [number, number][]; world_points_mm: [number, number][]; mm_per_px: number; bed_extent_mm: [number, number, number, number] }
export interface VisionCalibrateResult { reprojection_error: number; calibration_version: string }
// Board geometry shared by the calibration session and the validate endpoint — mirrors backend
// vention_printer_interface/api/app.py's BoardSpecBody (both ChArUco and checkerboard fields;
// unused fields for a given `kind` are left at their zero-value default and ignored server-side).
export interface VisionBoardSpecBody {
  kind: "charuco" | "checkerboard";
  squares_x?: number;
  squares_y?: number;
  square_length_mm?: number;
  marker_length_mm?: number;
  aruco_dict?: string;
  cols?: number;
  rows?: number;
  square_size_mm?: number;
}
// GET/POST /api/vision/calibrate/session — see backend app.py's `_calib_session_state`.
export interface VisionCalibSession { n_views: number; spec: Record<string, unknown> | null; ready: boolean }
// POST /api/vision/calibrate/capture — see backend app.py's `vision_calibrate_capture`.
export interface VisionCalibCaptureResult { captured: boolean; count?: number; corners_found?: number; reason?: string }
// POST /api/vision/calibrate/finalize body — see backend app.py's CalibFinalizeBody.
export interface VisionCalibFinalizeBody {
  mm_per_px: number;
  bed_extent_mm: [number, number, number, number];
  image_size?: [number, number];
  use_last_capture_as_bed?: boolean;
  bed_image_points?: [number, number][];
  bed_world_points_mm?: [number, number][];
}
// POST /api/vision/calibrate/finalize result — see backend app.py's `vision_calibrate_finalize`.
export interface VisionCalibFinalizeResult {
  corrected: boolean;
  intrinsics_rms: number;
  reprojection_error: number;
  calibration_version: string;
  n_views: number;
}
// POST /api/vision/validate result — see backend app.py's `vision_validate`.
export interface VisionValidateResult { rms_mm: number; max_mm: number; per_point: unknown; scale_bias: number; n_points: number }
// The capture sidecar JSON served at a record's sidecar_url — see backend
// vention_printer_interface/vision/store.py's _SIDECAR_TEMPLATE. Every leaf is optional/nullable:
// a field the backend never populated for a given capture is absent or null, never invented.
export interface VisionCaptureSidecar {
  layer?: number | null;
  stage?: string | null;
  axis_positions_mm?: Record<string, number> | null;
  capture?: { requested?: unknown; actual?: unknown } | null;
  controls?: { exposure?: number | null; gain?: number | null } | null;
  calibration?: { version?: string | null } | null;
}

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  status: () => req<StatusPayload>("GET", "/api/status"),
  discovery: () => req<Discovery>("GET", "/api/discovery"),
  connect: (body: { backend: string; ip?: string | null; heater_io?: [number, number] | null }) => req<StatusPayload>("POST", "/api/connect", body),
  disconnect: () => req<StatusPayload>("POST", "/api/disconnect"),
  arm: () => req<StatusPayload>("POST", "/api/arm"),
  disarm: () => req<StatusPayload>("POST", "/api/disarm"),
  estop: () => req<{ ok: boolean; steps: Record<string, string> }>("POST", "/api/estop"),
  estopRelease: () => req<StatusPayload>("POST", "/api/estop/release"),
  estopResetDrives: () => req<StatusPayload>("POST", "/api/estop/reset-drives"),
  clearFault: () => req<StatusPayload>("POST", "/api/clear-fault"),
  home: (axes: number[]) => req<StatusPayload>("POST", "/api/motion/home", { axes }),
  move: (axis: number, mode: "abs" | "rel", mm: number) => req<{ applied_mm: number }>("POST", "/api/motion/move", { axis, mode, mm }),
  stop: () => req<StatusPayload>("POST", "/api/motion/stop", {}),
  axisMotion: (n: number) => req<AxisMotion>("GET", `/api/axes/${n}/motion`),
  setAxisMotion: (n: number, body: { max_speed?: number; max_accel?: number }) => req<AxisMotion>("PUT", `/api/axes/${n}/motion`, body),
  limits: () => req<Record<string, unknown>>("GET", "/api/safety-limits"),
  setLimits: (body: Record<string, unknown>) => req<Record<string, unknown>>("PUT", "/api/safety-limits", body),
  heaterOn: () => req<StatusPayload>("POST", "/api/heater/on"),
  heaterOff: () => req<StatusPayload>("POST", "/api/heater/off"),
  printSettings: () => req<PrintSettingsPayload>("GET", "/api/print-settings"),
  setPrintSettings: (patch: Record<string, unknown>) => req<PrintSettingsPayload>("PUT", "/api/print-settings", patch),
  printStart: (body: { dry_run: boolean; single_step: boolean; name?: string; notes?: string }) => req<StatusPayload["print"]>("POST", "/api/print/start", body),
  printPause: () => req<StatusPayload["print"]>("POST", "/api/print/pause"),
  printResume: () => req<StatusPayload["print"]>("POST", "/api/print/resume"),
  printStep: () => req<StatusPayload["print"]>("POST", "/api/print/step"),
  printAbort: () => req<StatusPayload["print"]>("POST", "/api/print/abort"),
  setSingleStep: (on: boolean) => req<StatusPayload["print"]>("POST", "/api/print/single-step", { on }),
  printSteps: () => req<{ steps: Array<{ index: number; phase: string; layer: number; kind: string; axis: number | null; value: number | null; label: string }> }>("GET", "/api/print/steps"),
  printSeek: (index: number) => req<StatusPayload["print"]>("POST", "/api/print/seek", { index }),
  recordingStart: (body: { name: string; notes: string }) => req<{ run: string }>("POST", "/api/recording/start", body),
  recordingStop: () => req<{ run: string | null; stopped: boolean }>("POST", "/api/recording/stop"),
  recordings: () => req<{ runs: RunMeta[] }>("GET", "/api/recordings"),
  analysisGet: (run: string) => req<DimensionalReport>("GET", `/api/analysis/${encodeURIComponent(run)}/dimensional`),
  analysisRun: (run: string, body: AnalysisRequest = {}) => req<DimensionalReport>("POST", `/api/analysis/${encodeURIComponent(run)}/dimensional`, body),
  recordingSetMeta: (run: string, body: { name?: string; notes?: string }) => req<{ name: string; notes: string }>("PUT", `/api/recordings/${encodeURIComponent(run)}/meta`, body),
  recordingDelete: (run: string) => req<{ run: string; deleted: boolean }>("DELETE", `/api/recordings/${encodeURIComponent(run)}`),
  jobs: () => req<{ jobs: Array<Omit<StatusPayload["job"] & object, "current_layer">>; roots: string[] }>("GET", "/api/jobs"),
  selectJob: (path: string) => req<{ job: StatusPayload["job"]; print_settings: PrintSettingsPayload }>("POST", "/api/jobs/select", { path }),
  clearJob: () => req<{ job: null }>("POST", "/api/jobs/clear"),
  jobLayerUrl: (layer: number, jobFolder = "") => `${base}/api/jobs/current/layers/${layer}.png?job=${encodeURIComponent(jobFolder)}`,
  // serve a specific job folder's layer (incl. archived jobs), regardless of the selected job
  jobLayerByFolderUrl: (layer: number, folder: string) => `${base}/api/jobs/by-folder/${encodeURIComponent(folder)}/layers/${layer}.png`,
  macro: (name: string) => req<StatusPayload["print"]>("POST", `/api/macro/${name}`),
  priming: () => req<PrimingPayload>("GET", "/api/priming"),
  setPriming: (patch: Record<string, number>) => req<PrimingPayload>("PUT", "/api/priming", patch),
  primingRun: () => req<StatusPayload["print"]>("POST", "/api/priming/run"),
  primed: () => req<PrimedPayload>("GET", "/api/primed"),
  // per-camera settings (res/fps/format/exposure), persisted per role; applied on next open.
  primedCapture: () => req<PrimedPayload>("POST", "/api/primed/capture"),
  events: () => req<{ events: StatusPayload["events"] }>("GET", "/api/events"),
  autoLog: () => req<{ enabled: boolean }>("GET", "/api/auto-log"),
  setAutoLog: (enabled: boolean) => req<{ enabled: boolean }>("PUT", "/api/auto-log", { enabled }),
  visionStatus: () => req<VisionStatus>("GET", "/api/vision/status"),
  visionCameras: () => req<VisionCameras>("GET", "/api/vision/cameras"),
  visionDevices: () => req<VisionDevicesResponse>("GET", "/api/vision/devices"),
  visionGetRoles: () => req<VisionRoleMap>("GET", "/api/vision/roles"),
  visionSetRoles: (mapping: VisionRoleMap) => req<VisionRolesPutResult>("PUT", "/api/vision/roles", { mapping }),
  visionGetSettings: () => req<Record<string, CameraSettings>>("GET", "/api/vision/settings"),
  visionSetSettings: (body: Record<string, CameraSettings>) => req<Record<string, CameraSettings>>("PUT", "/api/vision/settings", body),
  visionCaptures: (run: string) => req<VisionCaptureRecord[]>("GET", `/api/vision/captures?run=${encodeURIComponent(run)}`),
  visionCalibrate: (body: VisionCalibrateBody) => req<VisionCalibrateResult>("POST", "/api/vision/calibrate", body),
  visionCalibrateSessionStart: (spec?: VisionBoardSpecBody) => req<VisionCalibSession>("POST", "/api/vision/calibrate/session", { spec: spec ?? null }),
  visionCalibrateSessionGet: () => req<VisionCalibSession>("GET", "/api/vision/calibrate/session"),
  visionCalibrateCapture: () => req<VisionCalibCaptureResult>("POST", "/api/vision/calibrate/capture"),
  visionCalibrateFinalize: (body: VisionCalibFinalizeBody) => req<VisionCalibFinalizeResult>("POST", "/api/vision/calibrate/finalize", body),
  visionValidate: (spec: VisionBoardSpecBody, square_size_mm: number) => req<VisionValidateResult>("POST", "/api/vision/validate", { spec, square_size_mm }),
  // `url` is a backend-provided path (a record's sidecar_url from visionCaptures), already
  // carrying its own query string — passed straight through to req(), same as every other path.
  visionCaptureSidecar: (url: string) => req<VisionCaptureSidecar>("GET", url),
};
