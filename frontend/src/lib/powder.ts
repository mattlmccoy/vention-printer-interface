export const FEED_TRAVEL_MM = 145; // safety.TRAVEL_MM[FEED]; the feed cavity can open at most this far.

export type FillSource = "job" | "layers" | "depth";
export interface FillInput {
  source: FillSource;
  feedDemandMm?: number;       // source "job": PrintSettingsPayload.feed_demand_mm (feed/layer x layers)
  thickPrecoatFeedMm?: number; // source "job": feed priming's thick precoats spend first (thickPrecoatFeedMm)
  nLayers?: number;            // source "layers"
  layerThicknessMm?: number;   // source "layers"
  manualDepthMm?: number;      // source "depth"
  marginMm?: number;           // safety extra added to job/layers (calibration-pending default)
  feedTravelMm?: number;       // default FEED_TRAVEL_MM
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/** Feed-piston fill depth (mm) = how far DOWN to open the feed cavity so a print has enough powder.
 *  "job"    -> the print's FEED demand + the thick precoats' feed + margin. The feed rises feed_thickness
 *              per layer (not the build's layer thickness), and priming's thick precoats spend their
 *              feed before the print starts — sizing on build thickness under-filled the 2026-09-22 run.
 *  "layers" -> nLayers x layerThickness + margin (operator must include the precoat layers).
 *  "depth"  -> operator's direct mm.
 *  Clamped to [0, feedTravel].
 *  FUTURE (calibration): a "volume" source computing depth from the powder volume needed to fill the
 *  build-piston cavity + runway backfill -- needs the feed/part cylinder cross-section areas, which are
 *  NOT in the codebase yet. Do not wire that path until those areas are measured. */
export function fillDepthMm(i: FillInput): number {
  const margin = i.marginMm ?? 0;
  const travel = i.feedTravelMm ?? FEED_TRAVEL_MM;
  let raw: number;
  if (i.source === "job") raw = (i.feedDemandMm ?? 0) + (i.thickPrecoatFeedMm ?? 0) + margin;
  else if (i.source === "layers") raw = (i.nLayers ?? 0) * (i.layerThicknessMm ?? 0) + margin;
  else raw = i.manualDepthMm ?? 0;
  return clamp(raw, 0, travel);
}

/** What fraction of the feed travel the cavity uses, 0-100 (a fill gauge). */
export function cavityFillPct(depthMm: number, feedTravelMm: number = FEED_TRAVEL_MM): number {
  return clamp(Math.round((100 * depthMm) / feedTravelMm), 0, 100);
}

/** Fraction of a piston well that is FILLED with material, 0-1, for the machine diagram.
 *  Position mm is DEPTH below flush (0 = flush with the bed, travel = piston fully down), so the
 *  well fills from the top down: flush -> full (1), deep -> empty (0); a cavity opens at the top as
 *  the piston descends. Matches the front-elevation schematic (pistonTopY). Non-finite/null -> 0. */
export function pistonMaterialFrac(mm: number | null | undefined, travelMm: number = FEED_TRAVEL_MM): number {
  if (typeof mm !== "number" || !Number.isFinite(mm)) return 0;
  const travel = travelMm > 0 ? travelMm : 1;
  return clamp(1 - mm / travel, 0, 1);
}

/** Feed spent by priming's thick precoats before the print starts: each raises the feed
 *  thick_feed_mm (control/priming.py compile_priming_setup). Missing values -> 0. */
export function thickPrecoatFeedMm(nThickPrecoats: number | null | undefined, thickFeedMm: number | null | undefined): number {
  if (typeof nThickPrecoats !== "number" || typeof thickFeedMm !== "number") return 0;
  return Math.max(0, nThickPrecoats) * Math.max(0, thickFeedMm);
}
