/** Geometry for the to-scale machine view (pure). The printer is drawn as two vertical pistons
 *  (part, feed; 0 at top = fully up... see note) and two horizontal gantries (printhead,
 *  recoater) over the bed. Positions are controller mm: pistons increase DOWN (V1.py moves the
 *  part piston +t per layer and the feed piston −t up), gantries increase from home (left). */

import { AXES, TRAVEL_MM, type AxisNo } from "./telemetry.ts";

export interface Rect { x: number; y: number; w: number; h: number }
export interface AxisGeom {
  axis: AxisNo;
  orientation: "vertical" | "horizontal";
  track: Rect;
  /** map controller mm → pixel coordinate along the track (x for horizontal, y for vertical) */
  px(mm: number): number;
  /** inverse for hit-testing / jog-to-click */
  mm(px: number): number;
}

export interface ViewGeom {
  width: number;
  height: number;
  axes: Record<AxisNo, AxisGeom>;
  bed: Rect;
  scale: number; // px per mm
}

const PAD = 28;

/** Fit the machine (bed 930 mm wide gantry travel × pistons 145 mm) into a viewport. */
export function layoutMachine(width: number, height: number): ViewGeom {
  const gantryLen = Math.max(TRAVEL_MM[3], TRAVEL_MM[4]);
  const pistonLen = TRAVEL_MM[1];
  const usableW = Math.max(100, width - 2 * PAD);
  const usableH = Math.max(100, height - 2 * PAD);
  // horizontal: gantry travel; vertical: two gantry tracks (2 × 14 px) + gap + piston travel
  const scale = Math.min(usableW / gantryLen, (usableH - 60) / pistonLen);
  const gantryW = gantryLen * scale;
  const x0 = (width - gantryW) / 2;
  const tracks: Record<AxisNo, Rect> = {
    3: { x: x0, y: PAD, w: TRAVEL_MM[3] * scale, h: 14 },
    4: { x: x0, y: PAD + 22, w: TRAVEL_MM[4] * scale, h: 14 },
    2: { x: x0, y: PAD + 60, w: 0, h: pistonLen * scale },
    1: { x: x0, y: PAD + 60, w: 0, h: pistonLen * scale },
  };
  // the two pistons sit side by side under the gantries: feed on the left, part on the right
  const bedW = gantryW;
  tracks[2] = { ...tracks[2], x: x0 + bedW * 0.25 - 20, w: 40 };
  tracks[1] = { ...tracks[1], x: x0 + bedW * 0.7 - 20, w: 40 };
  const axes = {} as Record<AxisNo, AxisGeom>;
  for (const a of AXES) {
    const t = tracks[a];
    const horizontal = a === 3 || a === 4;
    axes[a] = {
      axis: a,
      orientation: horizontal ? "horizontal" : "vertical",
      track: t,
      px: (mm) => (horizontal ? t.x + clamp(mm, 0, TRAVEL_MM[a]) * scale : t.y + clamp(mm, 0, TRAVEL_MM[a]) * scale),
      mm: (px) => (horizontal ? clamp((px - t.x) / scale, 0, TRAVEL_MM[a]) : clamp((px - t.y) / scale, 0, TRAVEL_MM[a])),
    };
  }
  return { width, height, axes, bed: { x: x0, y: PAD + 60, w: bedW, h: pistonLen * scale }, scale };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

/** Soft-limit bands (px) outside [travel_min, travel_max] for shading. */
export function limitBands(g: AxisGeom, travelMin: number, travelMax: number): Rect[] {
  const t = g.track;
  if (g.orientation === "horizontal") {
    return [
      { x: t.x, y: t.y, w: g.px(travelMin) - t.x, h: t.h },
      { x: g.px(travelMax), y: t.y, w: t.x + t.w - g.px(travelMax), h: t.h },
    ].filter((r) => r.w > 0.5);
  }
  return [
    { x: t.x, y: t.y, w: t.w, h: g.px(travelMin) - t.y },
    { x: t.x, y: g.px(travelMax), w: t.w, h: t.y + t.h - g.px(travelMax) },
  ].filter((r) => r.h > 0.5);
}

/** The heater rides on the recoater gantry: its glyph sits at the recoater position. */
export function heaterGlyph(g: ViewGeom, recoaterMm: number): { x: number; y: number } {
  const rc = g.axes[4];
  return { x: rc.px(recoaterMm), y: rc.track.y + rc.track.h + 6 };
}
