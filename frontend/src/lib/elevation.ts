/** Geometry (pure) for the front-elevation machine drawing: two rails on top, two pistons in
 *  the bed. Positions are controller mm: gantries from home at the left; pistons increase
 *  DOWNWARD (the V1.py convention: build piston +t per layer, feed piston −t up). */
import { TRAVEL_MM } from "./telemetry.ts";

export interface Rect { x: number; y: number; w: number; h: number }
export interface Elevation {
  vb: { w: number; h: number };
  railPh: Rect; railRc: Rect;
  feed: Rect; build: Rect; bed: Rect; frame: Rect;
  scaleX: number; scaleY: number;
  gantryX(axis: 3 | 4, mm: number): number;
  pistonTopY(axis: 1 | 2, mm: number): number;
}

export function layoutElevation(w = 900, h = 380): Elevation {
  const left = 70, right = w - 40;
  const scaleX = (right - left) / TRAVEL_MM[4];
  const railPh = { x: left, y: 52, w: TRAVEL_MM[3] * scaleX, h: 10 };
  const railRc = { x: left, y: 92, w: TRAVEL_MM[4] * scaleX, h: 10 };
  const bed = { x: left + 50, y: 150, w: right - left - 100, h: h - 200 };
  const scaleY = bed.h / TRAVEL_MM[1];
  const pw = Math.min(bed.w * 0.16, 120);
  const feed = { x: bed.x + bed.w * 0.3 - pw / 2, y: bed.y, w: pw, h: bed.h };
  const build = { x: bed.x + bed.w * 0.62 - pw / 2, y: bed.y, w: pw, h: bed.h };
  const clamp = (v: number, hi: number) => Math.min(Math.max(v, 0), hi);
  return {
    vb: { w, h }, railPh, railRc, feed, build, bed, scaleX, scaleY,
    frame: { x: left - 30, y: 30, w: right - left + 60, h: h - 60 },
    gantryX: (axis, mm) => left + clamp(mm, TRAVEL_MM[axis]) * scaleX,
    pistonTopY: (axis, mm) => bed.y + clamp(mm, TRAVEL_MM[axis]) * scaleY,
  };
}
