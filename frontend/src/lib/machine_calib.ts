/** Overlay calibration for the printer photo/wireframe (pure). Points are image pixels; the
 *  overlay SVG uses the image size as its viewBox so markers stay aligned at any display size. */
import { TRAVEL_MM } from "./telemetry.ts";

export interface Line { x0: number; y0: number; x1: number; y1: number }
export interface Vert { x: number; y0: number; y1: number }
export interface Calibration {
  image: { w: number; h: number };
  rails: { printhead: Line; recoater: Line };
  pistons: { feed: Vert; build: Vert };
  heater_offset_px: { dx: number; dy: number };
}
export const POINTS = [
  ["rails.printhead.0", "printhead carriage center at HOME (0 mm)"],
  ["rails.printhead.1", "printhead carriage center at the FAR end (970 mm)"],
  ["rails.recoater.0", "recoater carriage center at HOME (0 mm)"],
  ["rails.recoater.1", "recoater carriage center at the FAR end (972 mm)"],
  ["pistons.feed.0", "feed piston top surface fully UP (0 mm)"],
  ["pistons.feed.1", "feed piston top surface fully DOWN (145 mm)"],
  ["pistons.build.0", "build piston top surface fully UP (0 mm)"],
  ["pistons.build.1", "build piston top surface fully DOWN (145 mm)"],
] as const;
export type PointKey = (typeof POINTS)[number][0];

const num = (v: unknown, fb: number) => (typeof v === "number" && Number.isFinite(v) ? v : fb);
function line(v: unknown, fb: Line): Line { const o = (v ?? {}) as Record<string, unknown>; return { x0: num(o.x0, fb.x0), y0: num(o.y0, fb.y0), x1: num(o.x1, fb.x1), y1: num(o.y1, fb.y1) }; }
function vert(v: unknown, fb: Vert): Vert { const o = (v ?? {}) as Record<string, unknown>; return { x: num(o.x, fb.x), y0: num(o.y0, fb.y0), y1: num(o.y1, fb.y1) }; }

export const DEFAULT_CALIB: Calibration = {
  image: { w: 1526, h: 1017 },
  rails: { printhead: { x0: 470, y0: 105, x1: 1390, y1: 190 }, recoater: { x0: 120, y0: 205, x1: 1400, y1: 285 } },
  pistons: { feed: { x: 690, y0: 400, y1: 700 }, build: { x: 880, y0: 385, y1: 685 } },
  heater_offset_px: { dx: 60, dy: 10 },
};

export function parseCalibration(v: unknown): Calibration {
  const o = (v ?? {}) as Record<string, unknown>;
  const img = (o.image ?? {}) as Record<string, unknown>;
  const rails = (o.rails ?? {}) as Record<string, unknown>;
  const pistons = (o.pistons ?? {}) as Record<string, unknown>;
  const ho = (o.heater_offset_px ?? {}) as Record<string, unknown>;
  return {
    image: { w: num(img.w, DEFAULT_CALIB.image.w), h: num(img.h, DEFAULT_CALIB.image.h) },
    rails: { printhead: line(rails.printhead, DEFAULT_CALIB.rails.printhead), recoater: line(rails.recoater, DEFAULT_CALIB.rails.recoater) },
    pistons: { feed: vert(pistons.feed, DEFAULT_CALIB.pistons.feed), build: vert(pistons.build, DEFAULT_CALIB.pistons.build) },
    heater_offset_px: { dx: num(ho.dx, DEFAULT_CALIB.heater_offset_px.dx), dy: num(ho.dy, DEFAULT_CALIB.heater_offset_px.dy) },
  };
}

const clamp01 = (t: number) => Math.min(Math.max(t, 0), 1);
export function railPoint(l: Line, mm: number, travel: number): { x: number; y: number } {
  const t = clamp01(mm / travel);
  return { x: l.x0 + (l.x1 - l.x0) * t, y: l.y0 + (l.y1 - l.y0) * t };
}
export function pistonPoint(v: Vert, mm: number): { x: number; y: number } {
  const t = clamp01(mm / TRAVEL_MM[1]);
  return { x: v.x, y: v.y0 + (v.y1 - v.y0) * t };
}

/** Apply a clicked image point to the calibration (calibrate mode). Pure. */
export function setPoint(c: Calibration, key: PointKey, p: { x: number; y: number }): Calibration {
  const [group, name, idx] = key.split(".") as ["rails" | "pistons", string, "0" | "1"];
  if (group === "rails") {
    const l = { ...c.rails[name as "printhead" | "recoater"] };
    if (idx === "0") { l.x0 = p.x; l.y0 = p.y; } else { l.x1 = p.x; l.y1 = p.y; }
    return { ...c, rails: { ...c.rails, [name]: l } };
  }
  const v = { ...c.pistons[name as "feed" | "build"] };
  if (idx === "0") { v.x = p.x; v.y0 = p.y; } else { v.y1 = p.y; if (!v.x) v.x = p.x; }
  return { ...c, pistons: { ...c.pistons, [name]: v } };
}

const KEY = "vpi.machine.v1";
export function loadCalibration(storage: Storage | null): Calibration | null {
  try { const raw = storage?.getItem(KEY); return raw ? parseCalibration(JSON.parse(raw)) : null; } catch { return null; }
}
export function saveCalibration(storage: Storage | null, c: Calibration | null): void {
  try { if (c === null) storage?.removeItem(KEY); else storage?.setItem(KEY, JSON.stringify(c)); } catch { /* ignore */ }
}
