/** Pure helpers for the backlash calibration UI: quantised-rep binning (for a clearer plot that
 *  shows how many reps landed at each encoder level) and a repeatability verdict.
 *
 *  Note: the backlash cal always measures the RAW mechanical lash — the applied build_backlash_mm
 *  compensation is a print-time move (compile_print), not part of the measurement. So re-running
 *  the cal verifies the READING's repeatability (is one run trustworthy?), NOT that compensation
 *  zeroed the lash. Whether the compensation actually works shows up downstream in layer accuracy. */

export interface Level {
  value: number;
  count: number;
}

/** Group reps by their nearest encoder level (`quantumMm`, default one 0.1 mm count) and count how
 *  many landed at each. Ascending by level. Quantised data overplots as a blob on a raw strip plot;
 *  showing per-level counts instead makes the distribution legible. */
export function binLevels(reps: number[], quantumMm = 0.1): Level[] {
  const counts = new Map<number, number>();
  for (const r of reps) {
    const level = Math.round(r / quantumMm) * quantumMm;
    const key = Number(level.toFixed(6));  // avoid -0 and float dust as map keys
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => a.value - b.value);
}

export interface Verdict {
  consistent: boolean;
  deltaMm: number;
  priorMm: number;
  newMm: number;
}

/** Compare a re-measured backlash to a prior measurement. "Consistent" = within one encoder count
 *  (`tolMm`), i.e. the two runs agree to the readout's resolution, so a single reading is
 *  trustworthy. A larger gap means the reading is noisy and shouldn't be trusted from one run. */
export function verifyVerdict(priorMm: number, newMm: number, tolMm = 0.1): Verdict {
  const deltaMm = Math.abs(newMm - priorMm);
  return { consistent: deltaMm <= tolMm + 1e-9, deltaMm, priorMm, newMm };
}
