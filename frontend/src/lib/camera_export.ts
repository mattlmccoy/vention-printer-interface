/** Snapshot / recording export naming + on-image metadata stamps for the camera studio (#12).
 *  Pure so the labeling is unit-tested; the studio component does the canvas/MediaRecorder work. */

import type { CameraRole } from "./camera_roles.ts";

function pad(n: number): string { return String(n).padStart(2, "0"); }

/** Local-time stamp, filename-safe: YYYY-MM-DD_HH-MM-SS. Uses local components so it matches the
 *  operator's wall clock (and is TZ-stable in tests when the Date is built from local parts). */
export function snapshotStamp(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_` +
    `${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
}

/** Human-readable local timestamp for the on-image overlay: YYYY-MM-DD HH:MM:SS. */
export function humanStamp(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Download filename for a still: vpi-<role>-<stamp>.png. */
export function snapshotFilename(role: CameraRole, d: Date): string {
  return `vpi-${role}-${snapshotStamp(d)}.png`;
}

/** Download filename for a recording: vpi-<role>-<stamp>.webm. */
export function recordingFilename(role: CameraRole, d: Date): string {
  return `vpi-${role}-${snapshotStamp(d)}.webm`;
}

/** The text burned into the corner of an exported still: role · timestamp · WxH (+ optional run). */
export function snapshotOverlay(role: CameraRole, width: number, height: number, d: Date, run?: string | null): string {
  const base = `${role} · ${humanStamp(d)} · ${width}×${height}`;
  return run ? `${base} · run ${run}` : base;
}
