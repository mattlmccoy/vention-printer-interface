import { passMax, passMin, bandFraction } from "../lib/tolerance.ts";

/** A factory-style tolerance band: a shaded pass zone with the measured value marked against it, and
 *  a PASS/FAIL chip. `mode="max"` (error bands: pass when value ≤ limit, pass zone is 0..limit);
 *  `mode="min"` (resolution: pass when value ≥ limit, pass zone is limit..∞). */
export function ToleranceBand({ label, value, limit, unit, mode = "max", hint }: {
  label: string; value: number; limit: number; unit: string;
  mode?: "max" | "min"; hint?: string;
}) {
  const pass = mode === "max" ? passMax(value, limit) : passMin(value, limit);
  // Plot on a 0..ceiling*limit axis; the band edge sits at the limit.
  const ceiling = 2.5;
  const frac = mode === "max"
    ? bandFraction(value, limit, ceiling)
    : Math.min(ceiling, Math.max(0, limit > 0 ? value / limit : 0));
  const W = 320, H = 30, pad = 2;
  const x = (f: number) => pad + (f / ceiling) * (W - 2 * pad);
  const limitX = x(1);
  const valX = x(frac);
  const passFill = "var(--ok, #2e7d32)";
  const failFill = "var(--danger, #c62828)";
  return (
    <div className="tol-band" style={{ margin: "8px 0" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="hint" style={{ marginTop: 0, textTransform: "none", letterSpacing: 0 }}>{label}</span>
        <span style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <b style={{ fontFamily: "var(--font-mono)" }}>{value.toFixed(unit === "mm" ? 3 : 1)} {unit}</b>
          <span className="pill" style={{
            padding: "1px 8px", borderRadius: 999, fontSize: 12, fontWeight: 700,
            color: "#fff", background: pass ? passFill : failFill,
          }}>{pass ? "PASS" : "FAIL"}</span>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ display: "block", marginTop: 4 }}>
        <rect x={pad} y={10} width={W - 2 * pad} height={10} rx={3} fill="var(--track, #2a2f3a)" />
        {/* pass zone */}
        {mode === "max"
          ? <rect x={pad} y={10} width={limitX - pad} height={10} rx={3} fill={passFill} opacity={0.35} />
          : <rect x={limitX} y={10} width={W - pad - limitX} height={10} rx={3} fill={passFill} opacity={0.35} />}
        {/* limit line */}
        <line x1={limitX} y1={6} x2={limitX} y2={24} stroke="var(--line, #888)" strokeWidth={1.5} strokeDasharray="3 2" />
        <text x={limitX} y={H} textAnchor="middle" fontSize={9} fill="var(--muted, #999)">{limit}{unit === "mm" ? "" : ""}</text>
        {/* value marker */}
        <circle cx={valX} cy={15} r={5} fill={pass ? passFill : failFill} stroke="#fff" strokeWidth={1} />
      </svg>
      {hint && <div className="hint" style={{ marginTop: 2, textTransform: "none", letterSpacing: 0 }}>{hint}</div>}
    </div>
  );
}
