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

/** Like req() but returns the raw response body as a Blob — for binary downloads (seaborn PNG/PDF
 *  exports). Same client-header + FastAPI-detail error handling as req(). */
async function reqBlob(method: string, path: string, body?: unknown): Promise<Blob> {
  const headers: Record<string, string> = {};
  if (method !== "GET" && method !== "HEAD") headers[CLIENT_HEADER] = "1";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(apiUrl(base, path), { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try { const j = JSON.parse(text); if (j && typeof j === "object" && "detail" in j) detail = String((j as { detail: unknown }).detail); } catch { /* keep text */ }
    throw new ApiError(res.status, `${res.status} ${detail || res.statusText}`);
  }
  return res.blob();
}

/** Trigger a browser "save file" for a fetched blob (download-button glue). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export interface PathsInfo {
  jobs_root: string; jobs_root_source: string; jobs_root_is_fallback: boolean;
  experiments_root: string; experiments_root_source: string; experiments_root_is_fallback: boolean;
  config_path: string;
}
export interface Health { version: string; build?: string | null; api_version: string; backend: string; platform: string; paths?: PathsInfo | null }
// Data offload — verified copy of runs to a picked external drive. See backend offload.py.
export interface Drive { name: string; path: string; total_bytes: number; free_bytes: number }
export interface OffloadPlanRow { run: string; at_dest: boolean }
export interface OffloadJob { state: "idle" | "running" | "done" | "cancelled" | "error"; mode?: "copy" | "move"; dest?: string; progress?: { runs_done: number; runs_total: number; current: string; file_done: number; file_total: number }; files_copied?: number; files_skipped?: number; errors?: string[] }
export interface TimingConfig { print_min_wait_s: number; print_poll_interval_s: number; defaults: { print_min_wait_s: number; print_poll_interval_s: number } }
export interface Discovery { candidates: Array<{ backend: string; ip: string | null; label?: string; reachable: boolean }>; connected: { backend: string } }
export interface MeteorStatus { backend: string; available: boolean; ready: boolean; job_name: string | null; layers_ready: number; layers_expected: number; detail: string }
export interface PrintSettingsPayload { plan: Record<string, unknown>; validation: string[]; n_steps: number; estimated_duration_s: number; min_wait_s: number; total_layers: number; total_thickness_mm: number; feed_demand_mm: number; bounds: Record<string, unknown>; limits: Record<string, unknown>; exposure: { energy_j: number; time_s: number; sweep_speed_mm_s: number } }
export interface AxisMotion { max_speed: number | null; max_accel: number | null; bounds: { max_speed: [number, number]; max_accel: [number, number] }; limit_speed: number; limit_accel: number }
/** GET /api/print/feed-budget (control/feed_budget.py). available/sufficient/layers_supported are null
 *  when the feed position can't be verified (not homed / no telemetry); unknown_reason says why. */
export interface FeedBudgetPayload { demand_mm: number; available_mm: number | null; layers_total: number; layers_supported: number | null; sufficient: boolean | null; unknown_reason: string | null }
export interface PrimingPayload { settings: Record<string, number>; validation: string[]; n_steps: number; n_thick_precoats: number; limits: Record<string, unknown> }
export interface PrimedPayload { primed: { part_mm: number; feed_mm: number; captured_at: number } | null }
export interface BacklashPositionResult { ref_mm: number; backlash_median_mm: number; backlash_mag_median_mm: number; reps_mm: number[] }
export interface BacklashResult { axis: number; recommended_mm: number; cancelled: boolean; positions: BacklashPositionResult[] }
export interface BacklashSession { state: "idle" | "running" | "done" | "cancelled" | "error"; axis: number | null; progress: { done: number; total: number }; current_ref_mm: number | null; partial_positions?: BacklashPositionResult[]; result: BacklashResult | null; error: string | null }
// Persisted backlash cal history (survives restarts) — see backend control/backlash_history.py.
export interface BacklashHistoryItem { id: string; saved_utc: string; axis: number; recommended_mm: number | null; n_positions: number }
export interface BacklashRecord { id: string; saved_utc: string; axis: number; recommended_mm: number | null; positions: BacklashPositionResult[] }
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
export interface RunMeta { run: string; complete: boolean; status?: string; size_bytes: number; name?: string; notes?: string; started_at?: string | number | null; layer_count?: number | null; duration_s?: number | null; capture_count?: number | null; job_folder?: string | null; job_name?: string | null; locations?: string[] }
// Lane A dimensional analysis — GET/POST /api/analysis/{run}/dimensional (see backend
// vention_printer_interface/analysis/dimensional.py DimensionalReport). Non-"ok" statuses are
// honest 200 reports with features:{} and compensation:null — never fabricated metrics.
export type AnalysisStatus = "ok" | "no_capture" | "no_calibration" | "roi_failed" | "not_run";
export interface Compensation { scale_x: number; scale_y: number; yaw_deg: number | null; human: string; notes: string[]; deadband_pct?: number }
// Lane B — CAD-vs-real deviation (see backend analysis/lane_b.py). Non-"ok" statuses
// (no_capture/no_calibration/no_contour/decode_failed) are honest reports, not errors.
export interface LaneBReport {
  run?: string; layer?: number; folder?: string; status: string; message?: string;
  capture_url?: string;
  points_px?: [number, number][];       // printed contour, capture pixels (heatmap overlay coords)
  deviations_mm?: number[];             // signed deviation per point (+ = outside CAD / over)
  mean_abs_mm?: number; rms_mm?: number; max_abs_mm?: number; max_at_mm?: [number, number];
  area_ratio?: number; n?: number; mm_per_px?: number;
}

export interface DimensionalReport {
  run: string; status: AnalysisStatus; generated_utc?: string; message?: string;
  captured_from?: { layer?: number; stage?: string } | null; px_per_mm?: number | null; mm_per_px?: number | null;
  rois?: Record<string, [number, number, number, number]> | null;
  features?: Record<string, Record<string, number | null>>;
  compensation?: Compensation | null;
  tool_provenance?: Record<string, unknown>;
  // How the scale/ROIs were derived and any honest cross-check warning — see backend
  // analysis/dimensional.py (roi_source/calibration_source/calibration_warning on DimensionalReport).
  roi_source?: string | null;
  calibration_source?: string | null;
  calibration_warning?: string | null;
}
// Optional operator-marked outer circle (still natural-pixel coords), mirrors backend
// app.py CircleAnchor (cx_px/cy_px/radius_px). When present, the backend derives px/mm and the
// four feature ROIs from it (roi_source="circle"); `rois` still takes precedence over `circle`.
export interface CircleAnchorBody { cx_px: number; cy_px: number; radius_px: number }
export interface AnalysisRequest { layer?: number; stage?: string; rois?: Record<string, [number, number, number, number]>; nominals?: Record<string, unknown>; circle?: CircleAnchorBody }
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
export interface CalibCoverage { cells_filled: number; tilt_bins_filled: number; enough: boolean; gaps: string[]; total_views: number }
export interface VisionCalibSession { n_views: number; spec: Record<string, unknown> | null; ready: boolean; coverage?: CalibCoverage }
export interface VisionValidateScaleResult { rms_mm: number; max_mm: number; scale_bias: number; n_points: number; target_mm: number; passed: boolean; per_point?: Array<{ error_mm: number }> }
// Camera-center sweep (browser-driven): the client steps the recoater + captures a science frame
// per pose; the server scores each frame's bore offset and picks the centering recoater pose.
export interface CenterSweepSample { recoater_mm: number; offset_px: number | null }
export interface CenterSweepSession { active: boolean; poses: number[]; start_mm: number | null; samples: CenterSweepSample[]; done?: boolean }
export interface CenterSweepSampleResult { recoater_mm: number; found: boolean; offset_px: number | null; cx: number | null; cy: number | null; r: number | null; image_size: [number, number] }
export interface CenterSweepBest { pose_mm: number; offset_px: number; improved: boolean }
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
  offloadDrives: () => req<{ drives: Drive[] }>("GET", "/api/offload/drives"),
  offloadPlan: (dest: string) => req<{ plan: OffloadPlanRow[]; job: OffloadJob }>("GET", `/api/offload/plan?dest=${encodeURIComponent(dest)}`),
  offloadStart: (dest: string, opts?: { runs?: string[]; move?: boolean }) => req<OffloadJob>("POST", "/api/offload/start", { dest, runs: opts?.runs ?? null, move: opts?.move ?? false }),
  offloadJob: () => req<OffloadJob>("GET", "/api/offload/job"),
  offloadCancel: () => req<OffloadJob>("POST", "/api/offload/cancel"),
  timing: () => req<TimingConfig>("GET", "/api/config/timing"),
  setTiming: (body: { print_min_wait_s?: number; print_poll_interval_s?: number }) => req<TimingConfig>("PUT", "/api/config/timing", body),
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
  // Reference every axis at its current reported position WITHOUT homing (machine kept power).
  referenceCurrent: () => req<StatusPayload>("POST", "/api/reference/current"),
  // Re-launch the operator process in place (refused while a print is running). The server exits
  // right after replying, so the UI briefly shows "operator unreachable" then reconnects.
  operatorRestart: () => req<{ ok: boolean; restarting_in_s: number }>("POST", "/api/operator/restart"),
  move: (axis: number, mode: "abs" | "rel", mm: number) => req<{ applied_mm: number }>("POST", "/api/motion/move", { axis, mode, mm }),
  stop: () => req<StatusPayload>("POST", "/api/motion/stop", {}),
  backlashStart: (body: { axis: number; positions?: number[]; d_mm?: number; reps?: number; verify?: boolean }) => req<BacklashSession>("POST", "/api/motion/backlash/session", body),
  backlashStatus: () => req<BacklashSession>("GET", "/api/motion/backlash/session"),
  backlashCancel: () => req<BacklashSession>("POST", "/api/motion/backlash/cancel"),
  backlashApply: (axis: number) => req<PrintSettingsPayload>("POST", "/api/motion/backlash/apply", { axis }),
  backlashHistory: () => req<{ calibrations: BacklashHistoryItem[] }>("GET", "/api/motion/backlash/history"),
  backlashRecord: (id: string) => req<BacklashRecord>("GET", `/api/motion/backlash/history/${encodeURIComponent(id)}`),
  // Seaborn figure exports (optional `plots` extra; 503 if not installed). Return PNG/PDF blobs.
  plotBacklash: (fmt: "png" | "pdf") => reqBlob("GET", `/api/plots/backlash.${fmt}`),
  plotLayerAccuracy: (run: string, fmt: "png" | "pdf") => reqBlob("GET", `/api/plots/layer-accuracy/${encodeURIComponent(run)}.${fmt}`),
  plotValidation: (residuals_mm: number[], target_mm: number, fmt: "png" | "pdf") => reqBlob("POST", `/api/plots/validation.${fmt}`, { residuals_mm, target_mm }),
  plotSweep: (rows: Array<Record<string, unknown>>, fmt: "png" | "pdf") => reqBlob("POST", `/api/plots/sweep.${fmt}`, { rows }),
  axisMotion: (n: number) => req<AxisMotion>("GET", `/api/axes/${n}/motion`),
  setAxisMotion: (n: number, body: { max_speed?: number; max_accel?: number }) => req<AxisMotion>("PUT", `/api/axes/${n}/motion`, body),
  limits: () => req<Record<string, unknown>>("GET", "/api/safety-limits"),
  setLimits: (body: Record<string, unknown>) => req<Record<string, unknown>>("PUT", "/api/safety-limits", body),
  heaterOn: () => req<StatusPayload>("POST", "/api/heater/on"),
  heaterOff: () => req<StatusPayload>("POST", "/api/heater/off"),
  printSettings: () => req<PrintSettingsPayload>("GET", "/api/print-settings"),
  setPrintSettings: (patch: Record<string, unknown>) => req<PrintSettingsPayload>("PUT", "/api/print-settings", patch),
  printStart: (body: { single_step: boolean; name?: string; notes?: string; accept_feed_risk?: boolean }) => req<StatusPayload["print"]>("POST", "/api/print/start", body),
  printFeedBudget: () => req<FeedBudgetPayload>("GET", "/api/print/feed-budget"),
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
  // Fetch a run's raw CSV/text file (motion_profiles.csv, layer_accuracy.csv, ...). "" when absent.
  recordingFileText: async (run: string, file: string): Promise<string> => {
    try {
      const res = await fetch(`${base}/api/recordings/${encodeURIComponent(run)}/${file}`);
      return res.ok ? await res.text() : "";
    } catch {
      return "";
    }
  },
  laneB: (run: string, layer: number, folder: string, stage = "post_jet") => req<LaneBReport>("GET", `/api/analysis/${encodeURIComponent(run)}/lane-b?layer=${layer}&folder=${encodeURIComponent(folder)}&stage=${stage}`),
  analysisGet: (run: string) => req<DimensionalReport>("GET", `/api/analysis/${encodeURIComponent(run)}/dimensional`),
  analysisRun: (run: string, body: AnalysisRequest = {}) => req<DimensionalReport>("POST", `/api/analysis/${encodeURIComponent(run)}/dimensional`, body),
  recordingSetMeta: (run: string, body: { name?: string; notes?: string }) => req<{ name: string; notes: string }>("PUT", `/api/recordings/${encodeURIComponent(run)}/meta`, body),
  recordingDelete: (run: string) => req<{ run: string; deleted: boolean }>("DELETE", `/api/recordings/${encodeURIComponent(run)}`),
  // Move an offloaded run from its drive back to the local experiments root (copy, verify, delete drive copy).
  recordingRestore: (run: string) => req<{ run: string; restored: boolean; files: number }>("POST", `/api/recordings/${encodeURIComponent(run)}/restore`),
  // Reveal a run's metadata on disk in the OS file browser (operator is local). Returns the path.
  recordingReveal: (run: string) => req<{ run: string; path: string; revealed: boolean; note: string }>("POST", `/api/recordings/${encodeURIComponent(run)}/reveal`),
  jobs: () => req<{ jobs: Array<Omit<StatusPayload["job"] & object, "current_layer">>; roots: string[] }>("GET", "/api/jobs"),
  selectJob: (path: string) => req<{ job: StatusPayload["job"]; print_settings: PrintSettingsPayload }>("POST", "/api/jobs/select", { path }),
  clearJob: () => req<{ job: null }>("POST", "/api/jobs/clear"),
  // Meteor firing readiness: is a complete sliced job loaded in the hot folder MetPrint fires from?
  meteorStatus: () => req<MeteorStatus>("GET", "/api/meteor/status"),
  jobLayerUrl: (layer: number, jobFolder = "") => `${base}/api/jobs/current/layers/${layer}.png?job=${encodeURIComponent(jobFolder)}`,
  // serve a specific job folder's layer (incl. archived jobs), regardless of the selected job
  jobLayerByFolderUrl: (layer: number, folder: string) => `${base}/api/jobs/by-folder/${encodeURIComponent(folder)}/layers/${layer}.png`,
  // the slicer's isometric splash/preview image for a job folder (PNG); 404 when none exists
  jobPreviewUrl: (folder: string) => `${base}/api/jobs/by-folder/${encodeURIComponent(folder)}/preview.png`,
  // Animated-GIF timelapse of a run (#4). source "science" (per-layer stills for `stage`, default =
  // the fullest stage) or "overview" (time-ordered wide-view frames). Usable as an <img src> or link.
  recordingTimelapseUrl: (run: string, opts: { source?: "science" | "overview"; stage?: string; fps?: number } = {}) => {
    const q = new URLSearchParams({ source: opts.source ?? "science", fps: String(opts.fps ?? 6) });
    if (opts.source !== "overview" && opts.stage) q.set("stage", opts.stage);
    return `${base}/api/recordings/${encodeURIComponent(run)}/timelapse.gif?${q.toString()}`;
  },
  // AVFoundation cameras with stable unique ids + the science-camera binding for the unattended
  // (no-tab-open) server capture path (#/Phase 2). Empty `cameras` on non-macOS.
  // Data locations (jobs + runs) — persisted install-independently so a reinstall can't lose them.
  getConfigPaths: () => req<PathsInfo | Record<string, never>>("GET", "/api/config/paths"),
  setConfigPaths: (body: { jobs_root?: string | null; experiments_root?: string | null }) => req<PathsInfo & { restart_required: boolean }>("PUT", "/api/config/paths", body),
  // `ignored_names` / `names` (browser-safe names of ignored cameras) are absent on an older operator.
  avfCameras: () => req<{ cameras: Array<{ index: number; name: string; unique_id: string }>; science_uid: string | null; ignored_uids: string[]; ignored_names?: string[] }>("GET", "/api/vision/avf-cameras"),
  setScienceUid: (unique_id: string | null) => req<{ unique_id: string | null }>("PUT", "/api/vision/science-uid", { unique_id }),
  ignoredCameras: () => req<{ unique_ids: string[]; names?: string[] }>("GET", "/api/vision/ignored-cameras"),
  setIgnoredCameras: (unique_ids: string[]) => req<{ unique_ids: string[]; names?: string[] }>("PUT", "/api/vision/ignored-cameras", { unique_ids }),
  // Move a completed job's folder into the hot folder's _archive/ (Jobs-page housekeeping).
  archiveJob: (folder: string) => req<{ folder: string; archived_to: string }>("POST", "/api/jobs/archive", { folder }),
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
  // Client-side science capture: heartbeat (keeps the server from doing its own cv2 grab), and the
  // still upload (raw encoded image as the body; layer/stage/cad_layer in the query).
  scienceClientHeartbeat: () => req<{ ok: boolean }>("POST", "/api/vision/science/client-heartbeat"),
  scienceClientFallback: (seq: number) => req<{ queued: boolean }>(
    "POST", `/api/vision/science/client-fallback?seq=${encodeURIComponent(seq)}`,
  ),
  scienceCaptureUpload: async (blob: Blob, p: { layer: number; stage: string; cadLayer?: number }): Promise<boolean> => {
    const q = new URLSearchParams({ layer: String(p.layer), stage: p.stage });
    if (p.cadLayer != null) q.set("cad_layer", String(p.cadLayer));
    const res = await fetch(apiUrl(base, `/api/vision/science/capture?${q.toString()}`), {
      method: "POST",
      headers: { [CLIENT_HEADER]: "1", "Content-Type": blob.type || "image/webp" },
      body: blob,
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} science capture`);
    return true;
  },
  // Upload one OVERVIEW timelapse frame (raw body) during a recording; stored under <run>/overview/.
  overviewTimelapseUpload: async (blob: Blob): Promise<boolean> => {
    const res = await fetch(apiUrl(base, "/api/vision/overview/capture"), {
      method: "POST",
      headers: { [CLIENT_HEADER]: "1", "Content-Type": blob.type || "image/webp" },
      body: blob,
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} overview capture`);
    return true;
  },
  visionCalibrate: (body: VisionCalibrateBody) => req<VisionCalibrateResult>("POST", "/api/vision/calibrate", body),
  visionCalibrateSessionStart: (spec?: VisionBoardSpecBody) => req<VisionCalibSession>("POST", "/api/vision/calibrate/session", { spec: spec ?? null }),
  visionCalibrateSessionGet: () => req<VisionCalibSession>("GET", "/api/vision/calibrate/session"),
  visionCalibrateCapture: () => req<VisionCalibCaptureResult>("POST", "/api/vision/calibrate/capture"),
  // Browser-side calibration capture: POST a science still (raw body). Calibration then uses the
  // SAME getUserMedia source as the print-time captures — and needs no server camera.
  visionCalibrateCaptureUpload: async (blob: Blob): Promise<VisionCalibCaptureResult> => {
    const res = await fetch(apiUrl(base, "/api/vision/calibrate/capture-upload"), {
      method: "POST",
      headers: { [CLIENT_HEADER]: "1", "Content-Type": blob.type || "image/png" },
      body: blob,
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} calibration capture`);
    return res.json() as Promise<VisionCalibCaptureResult>;
  },
  visionCalibrateFinalize: (body: VisionCalibFinalizeBody) => req<VisionCalibFinalizeResult>("POST", "/api/vision/calibrate/finalize", body),
  visionValidate: (spec: VisionBoardSpecBody, square_size_mm: number) => req<VisionValidateResult>("POST", "/api/vision/validate", { spec, square_size_mm }),
  // Browser-image scale validation: POST a chessboard still; scored in world-mm vs the certified pitch.
  visionValidateScaleUpload: async (blob: Blob, p: { cols: number; rows: number; squareSizeMm: number; certifiedMm: number; targetMm?: number }): Promise<VisionValidateScaleResult> => {
    const q = new URLSearchParams({ cols: String(p.cols), rows: String(p.rows), square_size_mm: String(p.squareSizeMm), certified_mm: String(p.certifiedMm) });
    if (p.targetMm != null) q.set("target_mm", String(p.targetMm));
    const res = await fetch(apiUrl(base, `/api/vision/validate/scale-upload?${q.toString()}`), {
      method: "POST",
      headers: { [CLIENT_HEADER]: "1", "Content-Type": blob.type || "image/png" },
      body: blob,
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} scale validation`);
    return res.json() as Promise<VisionValidateScaleResult>;
  },
  // `url` is a backend-provided path (a record's sidecar_url from visionCaptures), already
  // carrying its own query string — passed straight through to req(), same as every other path.
  visionCaptureSidecar: (url: string) => req<VisionCaptureSidecar>("GET", url),
  // Camera-center sweep. start/status/best/apply/cancel are plain JSON; sample POSTs a raw frame.
  centerSweepStart: (body: { start_mm?: number; span_mm?: number; step_mm?: number }) => req<CenterSweepSession>("POST", "/api/vision/center-sweep/session", body),
  centerSweepStatus: () => req<CenterSweepSession>("GET", "/api/vision/center-sweep/session"),
  centerSweepBest: () => req<CenterSweepBest>("POST", "/api/vision/center-sweep/best"),
  centerSweepApply: (recoater_mm: number) => req<PrintSettingsPayload>("POST", "/api/vision/center-sweep/apply", { recoater_mm }),
  centerSweepCancel: () => req<{ active: boolean }>("POST", "/api/vision/center-sweep/cancel"),
  centerSweepSample: async (blob: Blob, recoaterMm: number): Promise<CenterSweepSampleResult> => {
    const res = await fetch(apiUrl(base, `/api/vision/center-sweep/sample?recoater_mm=${recoaterMm}`), {
      method: "POST",
      headers: { [CLIENT_HEADER]: "1", "Content-Type": blob.type || "image/png" },
      body: blob,
    });
    if (!res.ok) throw new ApiError(res.status, `${res.status} center-sweep sample`);
    return res.json() as Promise<CenterSweepSampleResult>;
  },
};
