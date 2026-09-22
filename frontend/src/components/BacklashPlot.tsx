import type { BacklashPositionResult } from "../lib/api.ts";
import { binLevels } from "../lib/backlash_verify.ts";

/** Per-depth backlash vs a tolerance band. The measurement is quantised to the 0.1 mm encoder
 *  readout, so instead of a raw strip plot (reps stack into an unreadable blob on the band edge)
 *  each depth shows a COUNT BUBBLE per observed level — bubble area ∝ how many reps landed there,
 *  with the count printed in it — plus a bold median tick. The shaded band is ±`tolMm` (one 0.1 mm
 *  count): inside it, lash is at/below what the readout can even resolve. Fed the streamed
 *  `partial_positions` during a run or `result.positions` when done. `recommended` is unused for
 *  drawing now (the headline number states it) but kept for API compatibility. */
export function BacklashPlot({ positions, tolMm = 0.1 }: {
  positions: BacklashPositionResult[]; recommended?: number | null; tolMm?: number;
}) {
  const W = 340, H = 186, padL = 40, padR = 14, padT = 12, padB = 30;
  const allVals = positions.flatMap((p) => p.reps_mm);
  const maxAbs = Math.max(tolMm * 1.8, 0.05, ...allVals.map((v) => Math.abs(v)));
  const yMax = Math.ceil(maxAbs * 20) / 20;  // round up to 0.05
  const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
  const y = (v: number) => y1 - ((v + yMax) / (2 * yMax)) * (y1 - y0);
  const n = Math.max(1, positions.length);
  const colW = (x1 - x0) / n;
  const colX = (i: number) => x0 + (i + 0.5) * colW;
  const band = "var(--ok, #2e7d32)";
  const dot = "var(--accent, #d9a441)";
  const maxCount = Math.max(1, ...positions.map((p) => Math.max(1, ...binLevels(p.reps_mm).map((l) => l.count))));
  const rFor = (count: number) => 4 + 7 * Math.sqrt(count / maxCount);  // area ∝ count
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ display: "block", marginTop: 6 }} role="img" aria-label="backlash per depth (count bubbles)">
      {/* tolerance band ±tolMm — light, so the data reads on top */}
      <rect x={x0} y={y(tolMm)} width={x1 - x0} height={y(-tolMm) - y(tolMm)} fill={band} opacity={0.1} />
      <line x1={x0} y1={y(tolMm)} x2={x1} y2={y(tolMm)} stroke={band} strokeWidth={0.75} strokeDasharray="3 2" opacity={0.5} />
      <line x1={x0} y1={y(-tolMm)} x2={x1} y2={y(-tolMm)} stroke={band} strokeWidth={0.75} strokeDasharray="3 2" opacity={0.5} />
      {/* zero line + y labels */}
      <line x1={x0} y1={y(0)} x2={x1} y2={y(0)} stroke="var(--line, #888)" strokeWidth={1} opacity={0.6} />
      {[yMax, 0, -yMax].map((v) => (
        <text key={v} x={x0 - 5} y={y(v) + 3} textAnchor="end" fontSize={9} fill="var(--muted, #999)">{v.toFixed(2)}</text>
      ))}
      {/* per-depth: a count bubble per observed level + a bold median tick */}
      {positions.map((p, i) => {
        const cx = colX(i);
        const tick = Math.min(colW * 0.34, 13);
        return (
          <g key={p.ref_mm}>
            {binLevels(p.reps_mm).map((lvl) => {
              const r = rFor(lvl.count);
              return (
                <g key={lvl.value}>
                  <circle cx={cx} cy={y(lvl.value)} r={r} fill={dot} opacity={0.85} />
                  {r >= 6 && (
                    <text x={cx} y={y(lvl.value) + 3} textAnchor="middle" fontSize={8.5} fontWeight={700} fill="var(--image-bg, #10151f)">{lvl.count}</text>
                  )}
                </g>
              );
            })}
            <line x1={cx - tick} y1={y(p.backlash_median_mm)} x2={cx + tick} y2={y(p.backlash_median_mm)} stroke="var(--fg, #eee)" strokeWidth={2} />
            <text x={cx} y={H - 15} textAnchor="middle" fontSize={9} fill="var(--muted, #999)">{p.ref_mm.toFixed(0)}</text>
          </g>
        );
      })}
      <text x={(x0 + x1) / 2} y={H - 3} textAnchor="middle" fontSize={8.5} fill="var(--muted, #999)">depth (mm) · bubble = reps at that 0.1 mm level · bar = ±{tolMm} mm (one count)</text>
    </svg>
  );
}
