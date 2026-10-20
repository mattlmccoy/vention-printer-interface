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
}): string[] {
  const out: string[] = [];
  const c = i.status?.controller;
  if (!i.status || !c) out.push("Operator not reachable — start the operator and reload.");
  else {
    if (c.state !== "connected") out.push("Controller not connected — connect the machine first.");
    if (!c.armed) out.push("Machine not armed — arm it on the Control page.");
    if (c.telemetry?.referenced?.[String(RECOATER_AXIS)] !== true) {
      out.push("Recoater not homed (or its homing state is unknown) — home it first.");
    }
  }
  if (!(i.capturePoseMm > 0)) out.push("No capture pose saved — set it under Settings → Capture pose.");
  if (!i.scienceAssigned) out.push("No science camera assigned — set it under Settings → Cameras.");
  if (!i.boardOk) out.push("Board settings incomplete — check Settings → Calibration board.");
  return out;
}

const realSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Wait until `axis` reports motion complete (or `timeoutMs`), then `settleMs` more so gantry
 *  vibration dies down before the photo. Transient status errors are retried. */
export async function waitSettled(
  getStatus: () => Promise<StatusPayload>,
  axis: number,
  opts: { timeoutMs?: number; settleMs?: number; sleep?: (ms: number) => Promise<void> } = {},
): Promise<void> {
  const sleep = opts.sleep ?? realSleep;
  const timeoutMs = opts.timeoutMs ?? 6000;
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const s = await getStatus();
      if (s.controller?.telemetry?.motion_complete?.[String(axis)] !== false) break;
    } catch { /* transient: try again */ }
    await sleep(200);
  }
  await sleep(opts.settleMs ?? 400);
}

export interface SweepDeps {
  move: (mm: number) => Promise<void>;
  settle: () => Promise<void>;
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
  plan: { poses: number[]; preApproachMm: number; captureMm: number },
  d: SweepDeps,
): Promise<"done" | "stopped"> {
  const halt = async () => { await d.stopMotion(); return "stopped" as const; };
  if (d.stopped()) return halt();
  await d.move(plan.preApproachMm);
  await d.settle();
  for (let i = 0; i < plan.poses.length; i++) {
    const pose = plan.poses[i];
    if (d.stopped()) return halt();
    await d.move(pose);
    await d.settle();
    const blob = await d.capture();
    const mm = await d.readMm();
    const r = await d.sample(blob, mm);
    d.onStep?.(i, { ...r, pose, mm });
    if (pose < plan.captureMm && !r.usable) return "done";
  }
  return "done";
}
