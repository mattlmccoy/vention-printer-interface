// Digital zoom/crop for a live camera <video>.
//
// Implemented as a CSS `transform: scale(zoom)` with a movable `transform-origin` (ox%, oy%): the
// container clips (overflow hidden), so any origin in [0,100] at zoom >= 1 always fully covers the
// frame (no empty edges) — panning is just moving the origin. Higher CAPTURE resolution keeps the
// crop sharp, which is why the overview requests up to 4K. This module is the pure math + storage.

export interface Crop {
  zoom: number; // 1 = no zoom
  ox: number; // transform-origin X, 0..100 %
  oy: number; // transform-origin Y, 0..100 %
}

export const NO_CROP: Crop = { zoom: 1, ox: 50, oy: 50 };
export const MAX_ZOOM = 4;

export function clampZoom(z: number): number {
  return Math.min(MAX_ZOOM, Math.max(1, Number.isFinite(z) ? z : 1));
}

export function clampPct(p: number): number {
  return Math.min(100, Math.max(0, Number.isFinite(p) ? p : 50));
}

/** New crop after dragging the image by (dx, dy) px inside a (w × h) px view at the current zoom.
 * Dragging the image right reveals its left side, so the origin decreases (hence the minus). A drag
 * at zoom 1 (nothing hidden) is a no-op. */
export function panOrigin(c: Crop, dx: number, dy: number, w: number, h: number): Crop {
  if (c.zoom <= 1 || w <= 0 || h <= 0) return c;
  const span = (c.zoom - 1); // fraction of the view hidden per axis, spread across 0..100% origin
  return {
    zoom: c.zoom,
    ox: clampPct(c.ox - (dx / (span * w)) * 100),
    oy: clampPct(c.oy - (dy / (span * h)) * 100),
  };
}

/** CSS for the video element implementing the crop. */
export function cropStyle(c: Crop): { transform: string; transformOrigin: string } {
  return { transform: `scale(${c.zoom})`, transformOrigin: `${c.ox}% ${c.oy}%` };
}

function key(deviceId: string): string {
  return `vpi.overviewCrop.${deviceId || "default"}`;
}

export function loadCrop(storage: Storage | null, deviceId: string): Crop {
  try {
    const raw = storage?.getItem(key(deviceId));
    if (!raw) return { ...NO_CROP };
    const p = JSON.parse(raw) as Partial<Crop>;
    return { zoom: clampZoom(p.zoom ?? 1), ox: clampPct(p.ox ?? 50), oy: clampPct(p.oy ?? 50) };
  } catch {
    return { ...NO_CROP };
  }
}

export function saveCrop(storage: Storage | null, deviceId: string, c: Crop): void {
  try {
    storage?.setItem(key(deviceId), JSON.stringify(c));
  } catch {
    /* storage disabled: crop just isn't remembered */
  }
}
