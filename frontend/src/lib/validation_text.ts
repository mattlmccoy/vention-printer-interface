/** Certified-chessboard validation: what the score covers (backend api/app.py
 *  _score_checkerboard_mm). Only corners inside the calibration's area are scored; an older
 *  calibration (or an older operator) has no area, and the text must say so rather than imply a
 *  filtered score. */
export function validationCoverageText(r: { n_points: number; n_outside?: number; area_known?: boolean }): string {
  if (r.area_known !== true) {
    return `${r.n_points} corners scored — calibrated area unknown (older calibration), so every corner counts`;
  }
  return `${r.n_points} corners scored inside the calibrated area, ${r.n_outside ?? 0} outside it (not scored)`;
}
