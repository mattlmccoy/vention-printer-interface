export interface PrimingSettings {
  part_top_mm: number; feed_cavity_mm: number; level_recoat_end_mm: number;
  level_recoat_return_mm: number; n_level_passes: number;
}
/** Plain-language "what this will do" lines for the priming setup routine. */
export function primingSteps(s: PrimingSettings): string[] {
  const lines = [
    `Raise the build piston up to the top (${s.part_top_mm} mm)`,
    `Lower the feed piston down to open a powder cavity (${s.feed_cavity_mm} mm)`,
    `HOLD — load powder into the feed, then Resume`,
  ];
  for (let i = 0; i < s.n_level_passes; i++)
    lines.push(`Level pass ${i + 1}: spread to ${s.level_recoat_end_mm} mm, return to ${s.level_recoat_return_mm} mm`);
  return lines;
}
