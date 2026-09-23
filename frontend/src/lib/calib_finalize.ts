/** Input checks for the Calibrate page's finalize step — mirror backend
 *  vision/registration.py bed_raster_error, so bad inputs are flagged inline before the 400.
 *
 * The finalize "mm / px" and "bed extent" define the corrected top-down bed image built on EVERY
 * science capture: (right-left)/mm_per_px × (bottom-top)/mm_per_px pixels. Too small an mm/px
 * makes that image enormous (0.01 on a 200 mm bed = 20000×20000 px, ~1.2 GB per frame). */

export const MAX_BED_IMAGE_PX = 25_000_000;

export type BedExtent = [number, number, number, number];
export type FinalizeInputs =
  | { ok: true; mmPerPx: number; extent: BedExtent }
  | { ok: false; field: "mmPerPx" | "bedExtent"; error: string };

/** [width, height] px of the bed image (same rounding as the backend's warp_to_bed). */
export function bedImageSize(mmPerPx: number, extent: BedExtent): [number, number] {
  const [x0, y0, x1, y1] = extent;
  return [Math.round((x1 - x0) / mmPerPx), Math.round((y1 - y0) / mmPerPx)];
}

export function parseFinalizeInputs(mmPerPxText: string, extentText: string): FinalizeInputs {
  const mm = mmPerPxText.trim() === "" ? NaN : Number(mmPerPxText);
  if (!Number.isFinite(mm) || mm <= 0) return { ok: false, field: "mmPerPx", error: "mm / px must be a positive number" };
  const parts = extentText.split(",").map((v) => v.trim());
  const nums = parts.map((v) => (v === "" ? NaN : Number(v)));
  if (nums.length !== 4 || nums.some((v) => !Number.isFinite(v))) {
    return { ok: false, field: "bedExtent", error: "bed extent needs 4 numbers: left, top, right, bottom (mm)" };
  }
  const extent = nums as BedExtent;
  const [x0, y0, x1, y1] = extent;
  if (!(x1 > x0)) return { ok: false, field: "bedExtent", error: `right must be greater than left (got left ${x0}, right ${x1})` };
  if (!(y1 > y0)) return { ok: false, field: "bedExtent", error: `bottom must be greater than top (got top ${y0}, bottom ${y1})` };
  const [w, h] = bedImageSize(mm, extent);
  if (w * h > MAX_BED_IMAGE_PX) {
    const minMm = Math.ceil(Math.sqrt(((x1 - x0) * (y1 - y0)) / MAX_BED_IMAGE_PX) * 1000 - 1e-6) / 1000;
    return {
      ok: false,
      field: "mmPerPx",
      error: `${mm} mm/px on a ${x1 - x0}×${y1 - y0} mm bed makes a ${w}×${h} px image (${((w * h) / 1e6).toFixed(1)} MP) — the limit is ${MAX_BED_IMAGE_PX / 1e6} MP, so use at least ${minMm} mm/px`,
    };
  }
  return { ok: true, mmPerPx: mm, extent };
}
