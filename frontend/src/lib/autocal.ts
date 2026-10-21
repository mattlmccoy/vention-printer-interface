/** Automatic science-camera calibration: run logic (spec docs/superpowers/specs/2026-10-20-auto-
 *  calibration-design.md). The browser drives motion and capture like the camera-centre sweep:
 *  move the recoater (axis 4), wait until it settles, take the still through the print capture
 *  path, upload it with the position READ BACK from telemetry. Pure functions with injected
 *  dependencies so the motion sequence is unit-tested; the panel only wires them up. */
import type { StatusPayload } from "./telemetry.ts";

export const RECOATER_AXIS = 4;

/** Why Start must stay disabled, as plain sentences (empty = ready). Unknown never counts as ready:
 *  a missing homing flag blocks just like an unhomed one. */
export function preflight(i: {
  status: StatusPayload | null;
  capturePoseMm: number;
  scienceAssigned: boolean;
  boardOk: boolean;
  printActive?: boolean;
}): string[] {
  const out: string[] = [];
  if (i.printActive) out.push("A print is running — wait until it finishes.");
  const c = i.status?.controller;
  if (!i.status || !c) out.push("Operator not reachable — start the operator and reload.");
  else {
    if (c.state !== "connected") out.push("Controller not connected — connect the machine first.");
    if (!c.armed) out.push("Machine not armed — arm it on the Control page.");
    if (c.telemetry?.referenced?.[String(RECOATER_AXIS)] !== true) {
      out.push("Recoater not homed (or its homing state is unknown) — home it first.");
    }
    const pos = c.telemetry?.positions?.[String(RECOATER_AXIS)];
    if (typeof pos !== "number" || !Number.isFinite(pos)) {
      out.push("Recoater position is not being read from the machine — check the controller connection.");
    }
  }
  if (!(i.capturePoseMm > 0)) out.push("No capture pose saved — set it under Settings → Capture pose.");
  if (!i.scienceAssigned) out.push("No science camera assigned — set it under Settings → Cameras.");
  if (!i.boardOk) out.push("Board settings incomplete — check Settings → Calibration board.");
  return out;
}

const realSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Recoater readout quantum: MM2 positions land on a 0.1 mm grid (backend control/settle.py). */
export const READOUT_MM = 0.1;
/** A photo is refused when the axis settled farther than this from the commanded pose. */
export const POSE_TOL_MM = 0.15;

/** Wait until `axis` has really finished its move and is holding position; returns the settled
 *  position. A port of the operator's validated control/settle.py: MM2 keeps reporting
 *  motion_complete=true from the PREVIOUS move for a few polls after a new move is issued, so a
 *  "complete" reading only counts once the move has registered (motion_complete went false) or a
 *  start grace has passed (a no-op move never goes incomplete). Then it needs `stable` consecutive
 *  complete readings within one readout count. Throws on timeout — never guesses. (2026-10-21: the
 *  old version returned on the stale "complete" and every photo was taken mid-move.) */
export async function waitSettled(
  getStatus: () => Promise<StatusPayload>,
  axis: number,
  opts: {
    timeoutMs?: number; startGraceMs?: number; pollMs?: number; stable?: number; settleMs?: number;
    sleep?: (ms: number) => Promise<void>; now?: () => number;
  } = {},
): Promise<number> {
  const sleep = opts.sleep ?? realSleep;
  const now = opts.now ?? (() => Date.now());
  const timeoutMs = opts.timeoutMs ?? 30000;
  const grace = opts.startGraceMs ?? 400;
  const poll = opts.pollMs ?? 50;
  const need = opts.stable ?? 3;
  const key = String(axis);
  const t0 = now();
  let sawIncomplete = false;
  let window: number[] = [];
  let last: number | null = null;
  while (now() - t0 < timeoutMs) {
    try {
      const tel = (await getStatus()).controller?.telemetry;
      const complete = tel?.motion_complete?.[key] === true;
      const pos = tel?.positions?.[key];
      if (!complete) sawIncomplete = true;
      const ready = sawIncomplete || now() - t0 >= grace;
      if (typeof pos === "number" && Number.isFinite(pos)) {
        last = pos;
        if (ready && complete) {
          window = [...window, pos].slice(-need);
          if (window.length >= need && Math.max(...window) - Math.min(...window) <= READOUT_MM + 1e-9) {
            if (opts.settleMs ?? 400) await sleep(opts.settleMs ?? 400);  // let gantry vibration die down
            return window[window.length - 1];
          }
        } else {
          window = [];  // moving, or the move has not registered yet: no stale "stable"
        }
      }
    } catch { /* transient status error: keep polling */ }
    await sleep(poll);
  }
  throw new Error(`Axis ${axis} did not settle within ${Math.round(timeoutMs / 1000)} s (last position ${last ?? "unknown"} mm) — nothing was photographed.`);
}

export interface SweepDeps {
  move: (mm: number) => Promise<void>;
  /** Resolves with the SETTLED position once the axis has really stopped (see waitSettled). */
  settle: () => Promise<number>;
  capture: () => Promise<Blob>;
  readMm: () => Promise<number>;
  sample: (b: Blob, mm: number) => Promise<{ usable: boolean }>;
  stopped: () => boolean;
  stopMotion: () => Promise<void>;
  onStep?: (i: number, r: { pose: number; mm: number; usable: boolean } & Record<string, unknown>) => void;
}

/** Pre-approach, then every planned pose (descending, so all are approached from the same side).
 *  `stopped()` is checked before EVERY move; when set, motion is halted and nothing further moves.
 *  Below the capture pose the sweep ends at the first photo without a usable board. Errors
 *  propagate to the caller (the panel shows them and offers the confirmed return move). */
export async function runSweep(
  plan: { poses: number[]; preApproachMm: number; captureMm: number; windowMinMm: number; windowMaxMm: number },
  d: SweepDeps,
): Promise<"done" | "stopped"> {
  const halt = async () => { await d.stopMotion(); return "stopped" as const; };
  if (d.stopped()) return halt();
  // The FIRST move starts wherever the recoater is: refuse (no motion) unless that is inside the
  // safety window too, or the blade could sweep through the zone the window keeps it out of.
  const start = await d.readMm();
  if (!Number.isFinite(start)) throw new Error("Cannot read the recoater position — nothing was moved.");
  if (start < plan.windowMinMm || start > plan.windowMaxMm) {
    throw new Error(`The recoater is at ${start.toFixed(1)} mm, outside the safety window (${plan.windowMinMm}–${plan.windowMaxMm} mm). Jog it inside the window first — nothing was moved.`);
  }
  await d.move(plan.preApproachMm);
  await d.settle();
  for (let i = 0; i < plan.poses.length; i++) {
    const pose = plan.poses[i];
    if (d.stopped()) return halt();
    await d.move(pose);
    const mm = await d.settle();
    if (Math.abs(mm - pose) > POSE_TOL_MM) {
      throw new Error(`The recoater stopped at ${mm.toFixed(1)} mm, not at ${pose.toFixed(1)} mm — calibration stopped (no photo taken).`);
    }
    const blob = await d.capture();
    const r = await d.sample(blob, mm);
    d.onStep?.(i, { ...r, pose, mm });
    if (d.stopped()) return halt();  // Stop pressed during this photo: nothing is solved
    if (pose < plan.captureMm && !r.usable) return "done";
  }
  return d.stopped() ? halt() : "done";
}
