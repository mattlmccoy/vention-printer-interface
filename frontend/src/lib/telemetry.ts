/** TS mirrors of the operator's status payload (backend api/app.py status_payload) and a ring
 *  buffer for position traces. Keep field names identical to the Python side. */

export type AxisNo = 1 | 2 | 3 | 4;
export const AXES: readonly AxisNo[] = [1, 2, 3, 4];
export const AXIS_NAMES: Record<AxisNo, string> = {
  1: "Part Piston",
  2: "Feed Piston",
  3: "Printhead Gantry",
  4: "Recoater Gantry",
};
export const AXIS_SHORT: Record<AxisNo, string> = { 1: "part", 2: "feed", 3: "printhead", 4: "recoater" };
/** Physical side each gantry homes to (user, 2026-09-09): printhead LEFT, recoater RIGHT. */
export const GANTRY_HOME_SIDE: Record<3 | 4, "left" | "right"> = { 3: "left", 4: "right" };
/** Measured travel (mm) from V1.py; the backend's HARD_BOUNDS use the same numbers. */
export const TRAVEL_MM: Record<AxisNo, number> = { 1: 145, 2: 145, 3: 840, 4: 972 };

export interface Telemetry {
  host_timestamp_ns: number;
  positions: Record<string, number>;
  motion_complete: Record<string, boolean>;
  estop_triggered: boolean | null;
  drives_ready: boolean | null;
  health_ok: boolean;
  heater_on: boolean | null;
}

export interface Limits {
  max_speed: Record<string, number>;
  max_accel: Record<string, number>;
  travel_min: Record<string, number>;
  travel_max: Record<string, number>;
  heater_max_on_s: number;
  telemetry_timeout_s: number;
  near_limit_mm: number;
}

export interface ControllerSnap {
  state: "disconnected" | "connected" | "fault" | "closed";
  backend: string;
  armed: boolean;
  fault_reasons: string[];
  warnings: string[];
  read_error: string | null;
  limits: Limits;
  heater: { on: boolean | null; commanded_on: boolean; on_s: number; max_on_s: number };
  telemetry: Telemetry | null;
}

export interface PrintSnap {
  state: "idle" | "running" | "paused" | "done" | "aborted" | "fault";
  macro: string | null;
  part_zero_mm: number | null;
  part_height_measured_mm: number | null;
  step_index: number;
  n_steps: number;
  phase: string;
  layer: number;
  n_layers: number;
  part_height_mm: number;
  elapsed_s: number;
  dry_run: boolean;
  single_step: boolean;
  reason: string;
  current_step: { index: number; kind: string; axis: number | null; value: number | null; label: string } | null;
  plan: Record<string, unknown> | null;
}

export interface EventItem { host_timestamp_ns: number; label: string; data: Record<string, unknown> }

export interface JobSnap {
  path: string; name: string; folder: string; layer_count: number; layer_height_mm: number; height_mm: number;
  bbox_mm: { x: number; y: number; z: number }; dpi: number; bpp: number; timestamp: string; complete: boolean;
  missing_pages: number[]; current_layer: number;
}

export interface StatusPayload {
  device: Record<string, unknown>;
  events: EventItem[];
  job: JobSnap | null;
  controller: ControllerSnap;
  axis_motion: Record<string, { max_speed: number | null; max_accel: number | null }>;
  print: PrintSnap;
  auto_log: boolean;
  recording: { active: boolean; run: string | null };
}

/** Fixed-capacity ring of (t, value) samples per axis for the plot dock. */
export class TraceBuffer {
  private t: Float64Array;
  private v: Float64Array;
  private head = 0;
  private n = 0;
  readonly capacity: number;
  constructor(capacity: number) {
    this.capacity = capacity;
    this.t = new Float64Array(capacity);
    this.v = new Float64Array(capacity);
  }
  push(t: number, value: number): void {
    this.t[this.head] = t;
    this.v[this.head] = value;
    this.head = (this.head + 1) % this.capacity;
    if (this.n < this.capacity) this.n++;
  }
  get length(): number {
    return this.n;
  }
  /** Samples newer than (latest - windowS), oldest first. */
  window(windowS: number): Array<[number, number]> {
    if (this.n === 0) return [];
    const latest = this.t[(this.head - 1 + this.capacity) % this.capacity];
    const out: Array<[number, number]> = [];
    for (let i = 0; i < this.n; i++) {
      const idx = (this.head - this.n + i + this.capacity) % this.capacity;
      if (latest - this.t[idx] <= windowS) out.push([this.t[idx], this.v[idx]]);
    }
    return out;
  }
  clear(): void {
    this.head = 0;
    this.n = 0;
  }
}

/** Derived staleness: acquiring but no sample for > 2 s (mirrors the FLIR rule). */
export function isStale(lastSampleMs: number | null, nowMs: number, limitMs = 2000): boolean {
  return lastSampleMs !== null && nowMs - lastSampleMs > limitMs;
}
