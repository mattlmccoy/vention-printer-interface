import type { BacklashPositionResult } from "../lib/api.ts";

/** Live strip plot of measured backlash per probed depth against a tolerance band. Each depth shows
 *  its per-rep lash values (dots) and their median (tick); the shaded band is ±`tolMm` (default one
 *  0.1 mm encoder count) — inside it, lash is at/below what the readout can even resolve. Fed the
 *  streamed `partial_positions` during a run (fills in per depth) or `result.positions` when done. */
export function BacklashPlot({ positions, recommended, tolMm = 0.1 }: {
  positions: BacklashPositionResult[]; recommended: number | null; tolMm?: number;
}) {
  const W = 340, H = 180, padL = 34, padR = 10, padT = 10, padB = 26;
  const allVals = positions.flatMap((p) => p.reps_mm);
  const maxAbs = Math.max(tolMm * 1.6, 0.05, ...allVals.map((v) => Math.abs(v)));
  const yMax = Math.ceil(maxAbs * 20) / 20;  // round up to 0.05
  const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
  const y = (v: number) => y1 - ((v + yMax) / (2 * yMax)) * (y1 - y0);
  const n = Math.max(1, positions.length);
  const colX = (i: number) => x0 + ((i + 0.5) / n) * (x1 - x0);
  const band = "var(--ok, #2e7d32)";
  const dot = "var(--accent, #d9a441)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ display: "block", marginTop: 6 }} role="img" aria-label="backlash per depth">
      {/* tolerance band ±tolMm */}
      <rect x={x0} y={y(tolMm)} width={x1 - x0} height={y(-tolMm) - y(tolMm)} fill={band} opacity={0.18} />
      <line x1={x0} y1={y(tolMm)} x2={x1} y2={y(tolMm)} stroke={band} strokeWidth={1} strokeDasharray="3 2" />
      <line x1={x0} y1={y(-tolMm)} x2={x1} y2={y(-tolMm)} stroke={band} strokeWidth={1} strokeDasharray="3 2" />
      {/* zero line + y labels */}
      <line x1={x0} y1={y(0)} x2={x1} y2={y(0)} stroke="var(--line, #888)" strokeWidth={1} />
      {[yMax, 0, -yMax].map((v) => (
        <text key={v} x={x0 - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill="var(--muted, #999)">{v.toFixed(2)}</text>
      ))}
      {/* recommended comp line */}
      {recommended != null && recommended > 0 && (
        <line x1={x0} y1={y(recommended)} x2={x1} y2={y(recommended)} stroke={dot} strokeWidth={1.2} strokeDasharray="5 3" />
      )}
      {/* per-depth reps + median */}
      {positions.map((p, i) => {
        const cx = colX(i);
        return (
          <g key={p.ref_mm}>
            {p.reps_mm.map((v, k) => (
              <circle key={k} cx={cx + ((k % 5) - 2) * 3} cy={y(v)} r={2.4} fill={dot} opacity={0.7} />
            ))}
            <line x1={cx - 9} y1={y(p.backlash_median_mm)} x2={cx + 9} y2={y(p.backlash_median_mm)} stroke="var(--fg, #eee)" strokeWidth={2} />
            <text x={cx} y={H - 14} textAnchor="middle" fontSize={9} fill="var(--muted, #999)">{p.ref_mm.toFixed(0)}</text>
          </g>
        );
      })}
      <text x={(x0 + x1) / 2} y={H - 2} textAnchor="middle" fontSize={9} fill="var(--muted, #999)">depth (mm) · band = ±{tolMm} mm (one encoder count)</text>
    </svg>
  );
}
