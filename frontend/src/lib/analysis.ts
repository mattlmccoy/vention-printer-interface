/** Pure UI helpers for the Lane A dimensional-analysis report (see api.ts DimensionalReport and
 *  backend analysis/dimensional.py). Kept pure + tested so the view stays declarative. */
import type { AnalysisStatus, Compensation, DimensionalReport } from "./api.ts";

/** How a status should render: "ok" (healthy), "empty" (not analyzed yet — info), "error" (a
 *  distinct, non-green failure). Never collapses a failure into a healthy look. */
export function analysisStatusKind(status: AnalysisStatus): "ok" | "empty" | "error" {
  if (status === "ok") return "ok";
  if (status === "not_run") return "empty";
  return "error"; // no_capture | no_calibration | roi_failed
}

/** Operator-facing message for a status; the backend `message` is appended when present. "" for ok. */
export function analysisStatusMessage(status: AnalysisStatus, message?: string): string {
  const base: Record<Exclude<AnalysisStatus, "ok">, string> = {
    not_run: "Not analyzed yet — run the analysis on this run.",
    no_capture: "No usable science-cam capture of the test geometry in this run.",
    no_calibration: "This capture isn't bed-plane calibrated (no mm/px) — run Setup calibration first.",
    roi_failed: "Couldn't locate the test pattern automatically — supply manual ROIs and re-analyze.",
  };
  if (status === "ok") return "";
  const b = base[status];
  return message ? `${b} (${message})` : b;
}

/** Human-readable prompt shown when auto-location failed and the operator must mark the circle.
 *  Actionable copy for `roi_failed`; `null` for every other status (nothing to prompt). */
export function roiEditPrompt(status: string): string | null {
  return status === "roi_failed" ? "Auto-location failed — mark the outer circle" : null;
}

/** The calibration cross-check warning to show as a chip, or `null` when there's nothing honest to
 *  flag. Returns the backend `calibration_warning` only when it's a non-empty string. */
export function calibrationChip(report: Pick<DimensionalReport, "calibration_warning">): string | null {
  const w = report.calibration_warning;
  return typeof w === "string" && w.length > 0 ? w : null;
}

const fmtScale = (n: number | null | undefined): string => (typeof n === "number" ? n.toFixed(4) : "—");
const fmtPct = (n: number | null | undefined): string => (typeof n === "number" ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` : "—");
const fmtDeg = (n: number | null | undefined): string => (typeof n === "number" ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}°` : "—");

export interface CompRow { label: string; value: string; sub: string }
/** The three compensation figures (scale X, scale Y, yaw) with display strings + a short note. */
export function compensationRows(comp: Compensation | null | undefined): CompRow[] {
  const c = comp ?? null;
  const scaleSub = (s: number | null | undefined): string => {
    if (typeof s !== "number" || s === 1) return "within deadband — no correction";
    return s > 1 ? "printed small → enlarge geometry" : "printed large → shrink geometry";
  };
  return [
    { label: "scale · X", value: fmtScale(c?.scale_x), sub: scaleSub(c?.scale_x) },
    { label: "scale · Y", value: fmtScale(c?.scale_y), sub: scaleSub(c?.scale_y) },
    { label: "yaw", value: fmtDeg(c?.yaw_deg), sub: c?.yaw_deg == null ? "no checkerboard angle" : "rotate to correct" },
  ];
}

export interface FeatureTile { k: string; v: string }
/** Key per-feature error metrics as stat tiles, drawn only from features actually present (a report
 *  with no features yields no tiles — never zeros). */
export function featureTiles(report: DimensionalReport): FeatureTile[] {
  const f = report.features ?? {};
  const tiles: FeatureTile[] = [];
  const dot = f.dot;
  if (dot) {
    tiles.push({ k: "dot spacing X", v: fmtPct(dot.spacing_x_error_pct) });
    tiles.push({ k: "dot spacing Y", v: fmtPct(dot.spacing_y_error_pct) });
    tiles.push({ k: "dot Ø err", v: fmtPct(dot.diameter_error_pct) });
  }
  const cb = f.checkerboard;
  if (cb) {
    tiles.push({ k: "checker sq", v: fmtPct(cb.square_error_pct) });
    // yaw ERROR (small sliver used for compensation), not the raw grid orientation angle_deg
    tiles.push({ k: "checker yaw", v: fmtDeg(cb.checkerboard_angle_error_deg ?? cb.angle_deg) });
  }
  const rings = f.rings;
  if (rings && typeof rings.mean_line_width_mm === "number") {
    tiles.push({ k: "ring line", v: `${rings.mean_line_width_mm.toFixed(3)} mm` });
  }
  const pitch = f.pitch;
  if (pitch && typeof pitch.min_resolvable_mm === "number") {
    tiles.push({ k: "min pitch", v: `${pitch.min_resolvable_mm.toFixed(2)} mm` });
  }
  return tiles;
}
