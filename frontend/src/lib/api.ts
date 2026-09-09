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
export interface PrintSettingsPayload { plan: Record<string, unknown>; validation: string[]; n_steps: number; estimated_duration_s: number; total_layers: number; total_thickness_mm: number; bounds: Record<string, unknown>; limits: Record<string, unknown> }
export interface AxisMotion { max_speed: number | null; max_accel: number | null; bounds: { max_speed: [number, number]; max_accel: [number, number] }; limit_speed: number; limit_accel: number }

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
  recordingStart: (body: { name: string; notes: string }) => req<{ run: string }>("POST", "/api/recording/start", body),
  recordingStop: () => req<{ run: string | null; stopped: boolean }>("POST", "/api/recording/stop"),
  recordings: () => req<{ runs: Array<{ run: string; complete: boolean; size_bytes: number }> }>("GET", "/api/recordings"),
  jobs: () => req<{ jobs: Array<Omit<StatusPayload["job"] & object, "current_layer">>; roots: string[] }>("GET", "/api/jobs"),
  selectJob: (path: string) => req<{ job: StatusPayload["job"]; print_settings: PrintSettingsPayload }>("POST", "/api/jobs/select", { path }),
  clearJob: () => req<{ job: null }>("POST", "/api/jobs/clear"),
  jobLayerUrl: (layer: number, jobFolder = "") => `${base}/api/jobs/current/layers/${layer}.png?job=${encodeURIComponent(jobFolder)}`,
  macro: (name: string) => req<StatusPayload["print"]>("POST", `/api/macro/${name}`),
  events: () => req<{ events: StatusPayload["events"] }>("GET", "/api/events"),
  autoLog: () => req<{ enabled: boolean }>("GET", "/api/auto-log"),
  setAutoLog: (enabled: boolean) => req<{ enabled: boolean }>("PUT", "/api/auto-log", { enabled }),
};
