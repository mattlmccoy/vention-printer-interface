export interface PrimingSettings {
  part_top_mm: number; feed_cavity_mm: number; level_recoat_end_mm: number;
  level_recoat_start_mm: number; n_thick_precoats: number; thick_feed_mm: number;
}
/** Plain-language "what this will do" lines for the priming setup routine. Priming now OWNS the
 *  thick precoats: each one spreads powder across the bed and advances the feed piston while the
 *  build piston stays fixed (backfill). */
export function primingSteps(s: PrimingSettings): string[] {
  const lines = [
    `Raise the build piston up to the top (${s.part_top_mm} mm)`,
    `Raise the feed piston up to the top (0 mm)`,
    `Lower the feed piston down to open a powder cavity (${s.feed_cavity_mm} mm)`,
    `Move the recoater to the start, left of the feed piston (${s.level_recoat_start_mm} mm)`,
    `HOLD — load powder into the feed, then Resume`,
  ];
  for (let i = 0; i < s.n_thick_precoats; i++)
    lines.push(`Thick precoat ${i + 1}: spread across to ${s.level_recoat_end_mm} mm, recoater back to ${s.level_recoat_start_mm} mm, feed up ${s.thick_feed_mm} mm`);
  return lines;
}
