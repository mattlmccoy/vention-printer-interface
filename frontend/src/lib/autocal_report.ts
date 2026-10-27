/** Calibration run analysis shown IN the Calibrate page (plan Tasks 10-12, 2026-10-21: "all these
 *  analyses need to be shown in the tool itself"). Pure functions over the operator's solve output
 *  (api/autocal_routes.py) so the panel only renders. Unknown values never render as passing. */

/** Limits used when a saved run predates `limits` in the solve output (0.16.x). */
export const DEFAULT_LIMITS = { min_views: 5, reprojection_mm: 0.05, shift_rms_mm: 0.1 };

export interface RunResult {
  passed?: boolean; n_views: number;
  reprojection_rms_px: number; reprojection_rms_mm?: number | null; px_mm?: number | null;
  shift_rms_mm: number; shift_worst_mm?: number; scale_ratio: number;
  image_size: [number, number]; valid_region_mm?: [number, number][];
  limits?: { min_views: number; reprojection_mm: number; shift_rms_mm: number };
}

export interface SavedCalibration {
  version: string; method?: string; image_size: [number, number] | null;
  reprojection_rms_mm: number | null; reprojection_rms_px: number | null;
  shift_rms_mm: number | null; scale_ratio: number | null; area_mm: [number, number] | null;
  n_views?: number | null;
}

export interface CheckRow { label: string; value: string; limit: string; ok: boolean | null }

/** Solve what a stopped run already photographed, once it has enough usable photos. */
export function canSolvePartial(shots: Array<{ usable: boolean }>, minViews: number): boolean {
  return shots.filter((s) => s.usable).length >= minViews;
}

export function areaOf(region: [number, number][] | undefined): [number, number] | null {
  if (!region || region.length < 3) return null;
  const xs = region.map((p) => p[0]);
  const ys = region.map((p) => p[1]);
  return [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
}

const mmArea = (a: [number, number] | null) => (a ? `${Math.round(a[0])} × ${Math.round(a[1])} mm` : "—");

/** Every pass check with its value and limit; informational rows have ok = null. */
export function checkRows(r: RunResult): CheckRow[] {
  const lim = r.limits ?? DEFAULT_LIMITS;
  const lensMm = r.reprojection_rms_mm;
  return [
    {
      label: "lens fit",
      value: lensMm == null ? `${r.reprojection_rms_px.toFixed(2)} px (no mm figure)` : `${lensMm.toFixed(3)} mm (${r.reprojection_rms_px.toFixed(2)} px)`,
      limit: `≤ ${lim.reprojection_mm} mm on the bed`,
      ok: lensMm == null ? null : lensMm <= lim.reprojection_mm,
    },
    {
      label: "encoder-shift check",
      value: `${r.shift_rms_mm.toFixed(3)} mm RMS${r.shift_worst_mm != null ? `, worst ${r.shift_worst_mm.toFixed(3)} mm` : ""}`,
      limit: `≤ ${lim.shift_rms_mm} mm RMS`,
      ok: r.shift_rms_mm <= lim.shift_rms_mm,
    },
    { label: "usable photos", value: String(r.n_views), limit: `≥ ${lim.min_views}`, ok: r.n_views >= lim.min_views },
    { label: "scale vs recoater", value: r.scale_ratio.toFixed(4), limit: "1.0000 = exact (checked by the shift test)", ok: null },
    { label: "calibrated area", value: mmArea(areaOf(r.valid_region_mm)), limit: "where board points were seen", ok: null },
  ];
}

export interface Comparison { tone: "ok" | "warn" | "info"; verdict: string; rows: Array<{ label: string; now: string; saved: string }> }

/** This run side by side with the calibration in use, with a plain verdict. */
export function compareCalibrations(r: RunResult, cur: SavedCalibration | null): Comparison {
  if (!cur) return { tone: "info", verdict: "No calibration saved yet — this run would be the first.", rows: [] };
  const size = (s: [number, number] | null) => (s ? `${s[0]}×${s[1]}` : "unknown");
  const lens = (mm: number | null | undefined, px: number | null | undefined) =>
    mm != null ? `${mm.toFixed(3)} mm` : px != null ? `${px.toFixed(2)} px (no mm figure)` : "—";
  const rows = [
    { label: "photo size", now: size(r.image_size), saved: size(cur.image_size) },
    { label: "lens fit", now: lens(r.reprojection_rms_mm, r.reprojection_rms_px), saved: lens(cur.reprojection_rms_mm, cur.reprojection_rms_px) },
    { label: "encoder-shift check", now: `${r.shift_rms_mm.toFixed(3)} mm`, saved: cur.shift_rms_mm == null ? "—" : `${cur.shift_rms_mm.toFixed(3)} mm` },
    { label: "scale vs recoater", now: r.scale_ratio.toFixed(4), saved: cur.scale_ratio == null ? "—" : cur.scale_ratio.toFixed(4) },
    { label: "calibrated area", now: mmArea(areaOf(r.valid_region_mm)), saved: mmArea(cur.area_mm) },
    { label: "photos", now: String(r.n_views), saved: cur.n_views == null ? "—" : String(cur.n_views) },
  ];
  const sameSize = !!cur.image_size && cur.image_size[0] === r.image_size[0] && cur.image_size[1] === r.image_size[1];
  if (!sameSize) {
    return {
      tone: "warn",
      verdict: `The saved calibration (${cur.version}, ${size(cur.image_size)}) does not apply to these ${size(r.image_size)} photos — print stills at this size are not measured until you save a new one.`,
      rows,
    };
  }
  const better = (a: number | null | undefined, b: number | null | undefined) => (a != null && b != null ? (a < b ? 1 : a > b ? -1 : 0) : 0);
  const score = [better(r.shift_rms_mm, cur.shift_rms_mm), better(r.reprojection_rms_mm, cur.reprojection_rms_mm)];
  if (score.every((s) => s >= 0) && score.some((s) => s > 0)) return { tone: "ok", verdict: `This run is better than the saved calibration (${cur.version}).`, rows };
  if (score.every((s) => s <= 0) && score.some((s) => s < 0)) return { tone: "warn", verdict: `This run is worse than the saved calibration (${cur.version}) — keep the saved one unless the board or camera changed.`, rows };
  return { tone: "info", verdict: `Mixed against the saved calibration (${cur.version}) — compare the rows.`, rows };
}

/** "2 placements: 14 + 12 photos": how many photos each board placement contributed (a photo
 *  without a placement is from the first). */
export function placementSummary(views: Array<{ placement?: number }>): string {
  if (!views.length) return "no photos";
  const counts = new Map<number, number>();
  for (const v of views) counts.set(v.placement ?? 0, (counts.get(v.placement ?? 0) ?? 0) + 1);
  const keys = [...counts.keys()].sort((a, b) => a - b);
  return `${keys.length} placement${keys.length === 1 ? "" : "s"}: ${keys.map((k) => counts.get(k)).join(" + ")} photos`;
}

/** One row of the operator's per-run point-method table (api/autocal_routes.py solve output). */
export interface PointMethodRow {
  method: string; label: string; n_photos: number; n_points: number; chosen: boolean; passed: boolean;
  lens_mm?: number | null; n_heldout?: number; heldout_mean_mm?: number | null; heldout_worst_mm?: number | null;
  error?: string;
}

/** The three point methods tried on this run and the one it kept (lowest error on held-out photos:
 *  fit on every photo but one, predict that one; every method is scored on the same points).
 *  null for a run from before 0.21.0. */
export function pointMethodSummary(rows: PointMethodRow[] | undefined): {
  verdict: string; rows: Array<{ label: string; points: string; heldout: string; worst: string; kept: boolean; note: string }>;
} | null {
  if (!rows || !rows.length) return null;
  const mm = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(3)} mm`);
  const kept = rows.find((r) => r.chosen);
  const verdict = !kept
    ? "No point method was kept."
    : kept.heldout_mean_mm == null
      ? `Kept: ${kept.label} (no held-out photos to compare the methods on).`
      : `Kept: ${kept.label} — lowest average error on held-out photos (${mm(kept.heldout_mean_mm)}).`;
  return {
    verdict,
    rows: rows.map((r) => ({
      label: r.label,
      points: `${r.n_points} points, ${r.n_photos} photos`,
      heldout: r.error ? "—" : mm(r.heldout_mean_mm),
      worst: r.error ? "—" : mm(r.heldout_worst_mm),
      kept: r.chosen,
      note: r.error ?? (r.passed ? "" : "does not pass the run's limits"),
    })),
  };
}
