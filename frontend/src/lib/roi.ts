// Pure geometry helper mirroring the backend dimensional-analysis ROI math.
//
// Single source of truth is the backend:
//   backend/vention_printer_interface/analysis/dimensional.py
//     - _AUTO_LAYOUT_MM   (per-feature center-based [x_mm, y_mm, w_mm, h_mm] boxes)
//     - mm_box_to_px_rect (center-based mm -> top-left-origin px rect)
//     - px_per_mm_from_circle (2*radius / diameter)
// Keep GOLD_LAYOUT_MM in sync with the backend's _AUTO_LAYOUT_MM.

export interface Circle {
  cx: number;
  cy: number;
  radius: number;
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

// Mirrored VERBATIM from backend dimensional.py _AUTO_LAYOUT_MM: center-based
// [x_mm, y_mm, w_mm, h_mm] with the Ø100 mm outer-circle center as origin, +x right,
// +y UP. Single source of truth is the backend; keep these in sync.
export const GOLD_LAYOUT_MM: Record<string, [number, number, number, number]> = {
  dot: [-24.1, 35.0, 30.0, 30.0],
  checkerboard: [5.4, 25.4, 20.0, 20.0],
  rings: [-34.6, 7.0, 44.0, 44.0],
  pitch: [9.0, 8.0, 26.0, 26.0],
};

/** px/mm implied by a marked Ø`diameterMm` outer circle (radius in px). */
export function pxPerMmFromCircle(radius: number, diameterMm = 100): number {
  return (2 * radius) / diameterMm;
}

/**
 * Feature ROIs from a marked outer circle, mirroring the backend exactly:
 *   x = round(cx + x_mm*ppm), y = round(cy - y_mm*ppm)  (+y mm is UP -> smaller row)
 *   w = round(w_mm*ppm),      h = round(h_mm*ppm)
 *
 * The backend uses Python `int(round(...))` (banker's rounding). Callers that need
 * pixel-exact parity with the backend should pick a circle whose products avoid .5
 * boundaries, where JS `Math.round` and Python `round` agree.
 */
export function roiBoxesFromCircle(
  c: Circle,
  layout: Record<string, [number, number, number, number]> = GOLD_LAYOUT_MM,
  diameterMm = 100,
): Record<string, Box> {
  const ppm = pxPerMmFromCircle(c.radius, diameterMm);
  const out: Record<string, Box> = {};
  for (const [feat, [xm, ym, wm, hm]] of Object.entries(layout)) {
    out[feat] = {
      x: Math.round(c.cx + xm * ppm),
      y: Math.round(c.cy - ym * ppm),
      w: Math.round(wm * ppm),
      h: Math.round(hm * ppm),
    };
  }
  return out;
}
