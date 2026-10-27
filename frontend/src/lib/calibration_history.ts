/** Settings → Calibrations: every science-camera calibration, viewable long after it was made
 *  (operator: vision/calibration_history.py, api/calibration_history_routes.py). Pure functions so
 *  the panel only renders. An unknown value shows "—" and a missing validation never reads as
 *  passing. */

export interface ValidationLatest {
  stamp: string | null; legacy: boolean; passed: boolean | null;
  rms_mm: number | null; max_mm: number | null; target_mm: number | null; scale_bias: number | null;
}
export interface ValidationSummary { count: number; status: "none" | "passed" | "failed"; latest: ValidationLatest | null }

export interface CalibrationSummary {
  version: string; saved_at: string | null; method: string; active: boolean; archived: boolean;
  image_size: [number, number] | null; lens_rms_mm: number | null; shift_rms_mm: number | null;
  scale_ratio: number | null; n_views: number | null; area_mm: [number, number] | null;
  point_method: string | null; self_check: { passed: boolean | null; rms_mm: number | null } | null;
  images: string[]; validation: ValidationSummary;
}

export interface ValidationRecord {
  stamp: string | null; legacy: boolean; annotated: boolean; raw: boolean; note?: string;
  passed?: boolean | null; rms_mm?: number | null; max_mm?: number | null; target_mm?: number | null;
  scale_bias?: number | null; scale_free_rms_mm?: number | null; n_points?: number | null; certified_mm?: number | null;
}

export interface CalibrationDetail extends CalibrationSummary {
  report: Record<string, unknown> | null;
  provenance: Record<string, unknown>;
  validations: ValidationRecord[];
}

const mm = (v: number | null | undefined, digits = 3) => (v == null ? "—" : `${v.toFixed(digits)} mm`);
const size = (s: [number, number] | null | undefined) => (s ? `${s[0]} × ${s[1]}` : "—");

export const POINT_METHOD_LABELS: Record<string, string> = {
  all: "every identified point",
  drop_outliers: "every point except lens-fit misses over 3 px",
  chessboard: "chessboard corners only",
};

export const IMAGE_CAPTIONS: Record<string, string> = {
  capture: "The capture-pose photo, as taken.",
  raw: "As photographed: amber = the board's square edges where the calibration predicts them; green = calibrated area.",
  corrected: "Corrected onto the bed (lens distortion removed): edges straight and on the amber grid.",
  residuals: "Lens-fit residual of every point, enlarged (factor printed on the photo): one direction = systematic misfit, scattered = noise.",
};

/** Status of a calibration's latest validation against a certified plate. */
export function validationBadge(v: ValidationSummary): { tone: "ok" | "warn" | "err"; text: string } {
  const l = v.latest;
  if (v.status === "none" || !l) return { tone: "warn", text: "not validated" };
  const worst = `worst ${mm(l.max_mm)}${l.target_mm != null ? ` (target ${l.target_mm} mm)` : ""}`;
  const legacy = l.legacy ? " · numbers only, no photo" : "";
  return v.status === "passed"
    ? { tone: "ok", text: `validated — ${worst}${legacy}` }
    : { tone: "err", text: `validation failed — ${worst}, RMS ${mm(l.rms_mm)}${legacy}` };
}

/** The calibration's key numbers as label/value pairs. */
export function summaryFacts(r: CalibrationSummary): Array<[string, string]> {
  const points = r.point_method
    ? POINT_METHOD_LABELS[r.point_method] ?? r.point_method
    : r.method === "auto-sweep" ? "every identified point (before 0.21.0)" : "—";
  const sc = r.self_check;
  return [
    ["photo size", size(r.image_size)],
    ["lens fit", mm(r.lens_rms_mm)],
    ["encoder shift", r.shift_rms_mm == null ? "—" : `${mm(r.shift_rms_mm)} RMS`],
    ["scale vs recoater", r.scale_ratio == null ? "—" : r.scale_ratio.toFixed(4)],
    ["calibrated area", r.area_mm ? `${Math.round(r.area_mm[0])} × ${Math.round(r.area_mm[1])} mm` : "—"],
    ["photos", r.n_views == null ? "—" : String(r.n_views)],
    ["self-check", !sc ? "not run" : `${sc.passed ? "passed" : "failed"} (${mm(sc.rms_mm)} RMS)`],
    ["points fitted", points],
  ];
}

/** What "use this calibration" will do, and a warning when its photo size differs from the one
 *  in use (a calibration only measures photos of the size it was fitted on). */
export function restorePlan(target: CalibrationSummary, active: CalibrationSummary | null): { confirm: string; warning: string | null } {
  const confirm = `Use ${target.version} (fitted on ${size(target.image_size)} photos) for every science photo from now on? ` +
    (active ? `It replaces ${active.version}, which stays in this list and can be restored.` : "At the moment no calibration is in use.");
  const differs = !!active?.image_size && !!target.image_size &&
    (active.image_size[0] !== target.image_size[0] || active.image_size[1] !== target.image_size[1]);
  const warning = differs
    ? `The calibration in use was fitted on ${size(active!.image_size)} photos; this one needs ${size(target.image_size)}. Set the science camera to ${size(target.image_size)} or its photos will not be measured.`
    : null;
  return { confirm, warning };
}
