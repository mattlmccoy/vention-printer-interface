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

/** How much of a validation error is pure scale (the operator also fits rotation + translation +
 *  ONE scale and reports what is left). "" when the operator did not report it (older version). */
export function validationScaleText(r: { max_mm: number; rms_mm: number; scale_bias: number; target_mm: number; scale_free_max_mm?: number | null; scale_free_rms_mm?: number | null }): string {
  if (r.scale_free_max_mm == null || r.scale_free_rms_mm == null) return "";
  const pct = (r.scale_bias - 1) * 100;
  const dir = pct >= 0 ? "too large" : "too small";
  const head = `Scale: measured lengths are ${Math.abs(pct).toFixed(2)}% ${dir}. With scale removed: worst ${r.scale_free_max_mm.toFixed(3)} mm, RMS ${r.scale_free_rms_mm.toFixed(3)} mm`;
  const mostlyScale = r.max_mm > r.target_mm && r.scale_free_max_mm <= r.target_mm;
  const tail = mostlyScale
    ? " — this is mostly a scale error; recalibrating with the encoder scale correction (0.19.3+) removes it."
    : r.scale_free_max_mm > r.target_mm
      ? " — not a scale error: the rest is lens fit, board flatness or placement (see the photo)."
      : ".";
  return head + tail;
}
