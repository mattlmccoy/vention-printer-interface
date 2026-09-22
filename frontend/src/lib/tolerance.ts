/** Factory-style tolerance-band helpers, shared by the calibration validation panels (scale +
 *  resolution) and reusable by the backlash-cal plots later. Pure. */

/** Pass when a value is within an UPPER limit (error/tolerance bands: smaller is better). */
export function passMax(value: number, limit: number): boolean {
  return value <= limit;
}

/** Pass when a value is at least a target (resolution lp/mm: larger is better). */
export function passMin(value: number, target: number): boolean {
  return value >= target;
}

/** Value as a fraction of the limit, clamped to a plotting ceiling so a wild outlier still renders
 *  inside the chart. 0 when the limit is non-positive (avoids divide-by-zero). */
export function bandFraction(value: number, limit: number, ceiling = 2.5): number {
  if (limit <= 0) return 0;
  return Math.min(ceiling, Math.max(0, value / limit));
}
