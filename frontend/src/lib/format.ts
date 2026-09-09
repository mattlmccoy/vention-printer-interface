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

/** Part height agreement: measured vs print_settings-expected, amber when off by more than half a layer. */
export function heightMismatch(measured: number | null, expected: number, layerMm: number): boolean {
  return measured !== null && Math.abs(measured - expected) > Math.max(layerMm / 2, 0.05);
}

/** Layer-cycle step (1-6) for the current print_settings step, from its kind/axis/value sequence. */
export function cycleIndex(step: { kind: string; axis: number | null; value: number | null; phase: string } | null, plan: { recoater_end_mm: number; heater_end_mm: number; printhead_end_mm: number } | null): number {
  if (!step || !plan || step.phase === "setup") return 0;
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
