/** Formatting + gating helpers (pure). Gating mirrors the T&C tool:
 *  connected = reachable && state in {connected, fault}; controllable = connected && armed.
 *  Safe-direction actions (STOP, HEATER OFF, E-STOP, DISARM, PAUSE, ABORT) gate on `connected` only. */

import type { StatusPayload } from "./telemetry.ts";

export interface Gates {
  reachable: boolean;
  connected: boolean;
  armed: boolean;
  controllable: boolean;
  faulted: boolean;
  printActive: boolean;
}

export function gates(status: StatusPayload | null, reachable: boolean): Gates {
  const state = status?.controller.state ?? "disconnected";
  const connected = reachable && (state === "connected" || state === "fault");
  const armed = connected && (status?.controller.armed ?? false);
  const rs = status?.print.state;
  return {
    reachable,
    connected,
    armed,
    controllable: connected && armed,
    faulted: state === "fault",
    printActive: rs === "running" || rs === "paused",
  };
}

export function fmtMm(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(digits)} mm`;
}

export function fmtSpeed(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v >= 10 ? 0 : 1)} mm/s`;
}

export function fmtAccel(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(v >= 10 ? 0 : 1)} mm/s²`;
}

/** Jog-button glyphs for a gantry given which physical side it homes to (printhead LEFT,
 *  recoater RIGHT, 2026-09-09). Moving toward 0 is toward home; the arrow must point at the
 *  real home side so the operator isn't fighting a mislabelled control. */
export function gantryJogLabels(side: "left" | "right"): { toHome: string; away: string } {
  return side === "left"
    ? { toHome: "◀ home", away: "away ▶" }
    : { toHome: "home ▶", away: "◀ away" };
}

export function fmtSecs(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return "—";
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return m > 0 ? `${m}:${r.toString().padStart(2, "0")}` : `${r}s`;
}

/** Tri-state status word for the status bar: unknown must never read as healthy. */
export function tri(v: boolean | null | undefined, yes: string, no: string, unknown = "?"): string {
  return v === true ? yes : v === false ? no : unknown;
}

export function armHint(g: Gates, faultReasons: string[]): string {
  if (!g.reachable) return "Operator unreachable.";
  if (!g.connected) return "Connect a controller to begin.";
  if (g.faulted) return `FAULT: ${faultReasons.join("; ") || "see status"}. Clear the fault to continue.`;
  if (!g.armed) return "Read-only. Check positions against the machine, then ARM to take control.";
  return "Armed. Motion, heater and print_settings controls are live.";
}

/** Part height agreement: measured piston displacement vs the print_settings-expected height.
 *  The compiled expected height increments at layer_start — BEFORE the build piston physically drops
 *  — so during every layer the measured value legitimately trails expected by up to one full layer
 *  (the in-flight drop). Warn only past that: >1.5 layers off, which is where a genuinely missed or
 *  stalled drop shows up (≈two layers behind at the next layer boundary). Amber advisory only. */
export function heightMismatch(measured: number | null, expected: number, layerMm: number): boolean {
  return measured !== null && Math.abs(measured - expected) > layerMm + Math.max(layerMm / 2, 0.05);
}

/** Layer-cycle step (1-6) for the current print_settings step, from its kind/axis/value sequence. */
export function cycleIndex(step: { kind: string; axis: number | null; value: number | null; phase: string } | null, plan: { recoater_end_mm: number; heater_end_mm: number; printhead_end_mm: number } | null): number {
  if (!step || !plan || step.phase === "setup" || step.phase === "finish" || step.kind === "home") return 0;
  if (step.kind === "heater" || (step.axis === 4 && step.kind === "move_abs" && step.value === plan.heater_end_mm)) return 6;
  if (step.axis === 3) return 5;
  if (step.axis === 4 && step.kind === "move_abs") return step.value === plan.recoater_end_mm ? 2 : 4;
  if (step.axis === 2) return 3;
  if (step.axis === 1) return 1;
  return 0;
}

export function formatError(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}
