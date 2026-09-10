export const FEED_TRAVEL_MM = 145; // safety.TRAVEL_MM[FEED]; the feed cavity can open at most this far.

export type FillSource = "job" | "layers" | "depth";
export interface FillInput {
  source: FillSource;
  totalThicknessMm?: number;   // source "job": PrintSettingsPayload.total_thickness_mm
  nLayers?: number;            // source "layers"
  layerThicknessMm?: number;   // source "layers"
  manualDepthMm?: number;      // source "depth"
  marginMm?: number;           // safety extra added to job/layers (calibration-pending default)
  feedTravelMm?: number;       // default FEED_TRAVEL_MM
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** Feed-piston fill depth (mm) = how far DOWN to open the feed cavity so a print has enough powder.
 *  "job"    -> total print thickness consumed from the feed piston + margin (exact; incl. thick precoats).
 *  "layers" -> nLayers x layerThickness + margin (operator must include the precoat layers).
 *  "depth"  -> operator's direct mm.
 *  Clamped to [0, feedTravel].
 *  FUTURE (calibration): a "volume" source computing depth from the powder volume needed to fill the
 *  part-piston cavity + runway backfill -- needs the feed/part cylinder cross-section areas, which are
 *  NOT in the codebase yet. Do not wire that path until those areas are measured. */
export function fillDepthMm(i: FillInput): number {
  const margin = i.marginMm ?? 0;
  const travel = i.feedTravelMm ?? FEED_TRAVEL_MM;
  let raw: number;
  if (i.source === "job") raw = (i.totalThicknessMm ?? 0) + margin;
  else if (i.source === "layers") raw = (i.nLayers ?? 0) * (i.layerThicknessMm ?? 0) + margin;
  else raw = i.manualDepthMm ?? 0;
  return clamp(raw, 0, travel);
}

/** What fraction of the feed travel the cavity uses, 0-100 (a fill gauge). */
export function cavityFillPct(depthMm: number, feedTravelMm: number = FEED_TRAVEL_MM): number {
  return clamp(Math.round((100 * depthMm) / feedTravelMm), 0, 100);
}
