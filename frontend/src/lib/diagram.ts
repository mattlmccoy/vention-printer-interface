export type DiagramMode = "live" | "model";

/** Marker CSS classes for an axis: live vs model (preview), plus a moving modifier.
 *  `mk-live` is a neutral no-op that preserves each marker's per-axis colour;
 *  `mk-model` paints the violet "ghost"; `mk-moving` adds the motion pulse. */
export function markerClass(mode: DiagramMode, moving: boolean): string {
  const base = mode === "model" ? "mk-model" : "mk-live";
  return moving ? `${base} mk-moving` : base;
}
