export type DiagramMode = "live" | "model";

/** Marker CSS classes for an axis: live vs model (preview), plus a moving modifier.
 *  `mk-live` is a neutral no-op that preserves each marker's per-axis colour;
 *  `mk-model` paints the violet "ghost"; `mk-moving` adds the motion pulse. */
export function markerClass(mode: DiagramMode, moving: boolean): string {
  const base = mode === "model" ? "mk-model" : "mk-live";
  return moving ? `${base} mk-moving` : base;
}

export type ArrowDir = "up" | "down";
/** Piston travel direction from consecutive positions: position GROWS = piston descends ("down"),
 *  SHRINKS = rises ("up"); equal or unknown prev = null (no arrow). eps guards float jitter. */
export function pistonArrow(prev: number | null, curr: number | null, eps = 0.05): ArrowDir | null {
  if (prev === null || curr === null) return null;
  const d = curr - prev;
  if (Math.abs(d) < eps) return null;
  return d > 0 ? "down" : "up";
}
