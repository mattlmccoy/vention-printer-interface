/** Geometry for the overlays drawn on the active calibration image (live preview + sweep photo). */

export type Pt = [number, number];

/** Points found on an image of size `from` placed onto an image of size `to` (same field of view). */
export function scaleOverlay(points: Pt[], from: [number, number], to: [number, number]): Pt[] {
  const sx = to[0] / from[0];
  const sy = to[1] / from[1];
  return points.map(([x, y]) => [x * sx, y * sy]);
}

/** Convex hull (monotone chain), counter-clockwise; [] for fewer than 3 distinct points. During the
 *  sweep this is the area of the photo the board has covered = the calibrated area so far. */
export function convexHull(points: Pt[]): Pt[] {
  const p = [...new Map(points.map((q) => [`${q[0]},${q[1]}`, q])).values()]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return [];
  const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Pt[] = [];
  for (const q of p) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop();
    lower.push(q);
  }
  const upper: Pt[] = [];
  for (const q of [...p].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop();
    upper.push(q);
  }
  const hull = [...lower.slice(0, -1), ...upper.slice(0, -1)];
  return hull.length >= 3 ? hull : [];
}

/** The operator lists chessboard corners first, then each marker's 4 corners in order
 *  (vision/charuco_points.py), so marker outlines are consecutive fours after `nChess`. */
export function markerQuads(points: Pt[], nChess: number): Pt[][] {
  const out: Pt[][] = [];
  for (let i = nChess; i + 4 <= points.length; i += 4) out.push(points.slice(i, i + 4));
  return out;
}

/** Arrow enlargement for lens-fit residuals: the 95th-percentile arrow draws 2% of the photo width
 *  (same rule and numpy-style linear percentile as the operator's residual overlay). */
export function arrowGain(residuals: Pt[], imageW: number): number {
  const m = residuals.map(([dx, dy]) => Math.hypot(dx, dy)).sort((a, b) => a - b);
  if (!m.length) return 1;
  const r = 0.95 * (m.length - 1);
  const lo = Math.floor(r);
  const p95 = m[lo] + (m[Math.min(lo + 1, m.length - 1)] - m[lo]) * (r - lo);
  return p95 > 0 ? (0.02 * imageW) / p95 : 1;
}
