import type { CSSProperties } from "react";
import { residualText, type ResidualGroup } from "../lib/autocal.ts";
import { checkRows, compareCalibrations, type RunResult, type SavedCalibration } from "../lib/autocal_report.ts";

/** One solved sweep as the operator saved it (GET /api/vision/autocal/last). */
export interface LastSweep {
  saved_at: string | null;
  image_size: [number, number];
  capture_mm: number;
  result: RunResult & { reasons?: string[]; residuals?: Record<string, ResidualGroup>; current?: SavedCalibration | null };
  views: Array<{ recoater_mm: number; points: number; chessboard: number; markers: number; image_points: [number, number][] }>;
}

const MAP_W = 320;

/** The run report shown on the Calibrate page after every solve and on reload (plan Task 11-12):
 *  every check against its limit, the comparison with the calibration in use, where the lens error
 *  sits, where board points were seen in the photo, the calibrated area on the bed, and each photo. */
export function CalibrationRunReport({ last }: { last: LastSweep }) {
  const r = last.result;
  const rows = checkRows(r);
  const cmp = "current" in r ? compareCalibrations(r, r.current ?? null) : null;
  const [w, h] = last.image_size;
  const mapH = Math.round((MAP_W * h) / w);
  const dot = Math.max(w, h) / 220;
  const region = r.valid_region_mm ?? [];
  const xs = region.map((p) => p[0]);
  const ys = region.map((p) => p[1]);
  const pad = 6;
  const bx0 = Math.min(0, ...xs) - pad, bx1 = Math.max(0, ...xs) + pad;
  const by0 = Math.min(0, ...ys) - pad, by1 = Math.max(0, ...ys) + pad;
  const when = last.saved_at ? new Date(last.saved_at).toLocaleString() : "unknown time";

  return (
    <div className="grid-gap" style={{ marginTop: 12 }}>
      <div className={r.passed ? "okline" : "errline"} style={{ margin: 0 }}>
        Run report ({when}, {r.n_views} usable photos at {w}×{h}): {r.passed ? "passed" : "did not pass"}.
        {r.reasons && r.reasons.length > 0 && <ul style={{ margin: "4px 0 0 18px" }}>{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
      </div>

      <div style={{ overflowX: "auto" }}>
        <table className="report-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead><tr><th style={th}>check</th><th style={th}>this run</th><th style={th}>limit</th><th style={th}></th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td style={td}>{row.label}</td>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{row.value}</td>
                <td style={{ ...td, color: "var(--muted)" }}>{row.limit}</td>
                <td style={{ ...td, color: row.ok === true ? "var(--live)" : row.ok === false ? "var(--err)" : "var(--muted)" }}>
                  {row.ok === true ? "pass" : row.ok === false ? "FAIL" : "info"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {r.residuals && (
        <div className="hint" style={{ margin: 0 }} title="Lens-fit error by point type and by distance from the photo centre (centre < 1/3 of the half-diagonal, edge ≥ 2/3).">
          Where the lens error is: {residualText(r.residuals) || "—"}
        </div>
      )}

      {cmp && (
        <div>
          <div className={cmp.tone === "ok" ? "okline" : cmp.tone === "warn" ? "warnline" : "hint"} style={{ margin: 0 }}>{cmp.verdict}</div>
          {cmp.rows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6 }}>
                <thead><tr><th style={th}></th><th style={th}>this run</th><th style={th}>saved ({r.current?.version})</th></tr></thead>
                <tbody>{cmp.rows.map((row) => (
                  <tr key={row.label}><td style={td}>{row.label}</td><td style={{ ...td, fontFamily: "var(--font-mono)" }}>{row.now}</td><td style={{ ...td, fontFamily: "var(--font-mono)" }}>{row.saved}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="cols-2">
        <figure style={{ margin: 0 }}>
          <svg viewBox={`0 0 ${w} ${h}`} width={MAP_W} height={mapH} role="img" aria-label="where board points were seen in the photo"
               style={{ maxWidth: "100%", height: "auto", background: "var(--bg-deep)", border: "1px solid var(--line)" }}>
            {[1, 2].map((k) => <line key={`v${k}`} x1={(w * k) / 3} y1={0} x2={(w * k) / 3} y2={h} stroke="var(--line-strong)" strokeWidth={w / 400} />)}
            {[1, 2].map((k) => <line key={`h${k}`} x1={0} y1={(h * k) / 3} x2={w} y2={(h * k) / 3} stroke="var(--line-strong)" strokeWidth={w / 400} />)}
            {last.views.flatMap((v, i) => v.image_points.map(([x, y], j) => (
              <circle key={`${i}-${j}`} cx={x} cy={y} r={dot} fill="var(--accent)" fillOpacity={0.55} />
            )))}
          </svg>
          <figcaption className="hint" style={{ margin: "4px 0 0" }}>Every board point seen, in the photo ({w}×{h}); grid = the 9 coverage regions.</figcaption>
        </figure>
        <figure style={{ margin: 0 }}>
          {region.length >= 3 ? (
            <svg viewBox={`${bx0} ${by0} ${bx1 - bx0} ${by1 - by0}`} width={MAP_W} role="img" aria-label="calibrated area on the bed"
                 style={{ maxWidth: "100%", height: "auto", background: "var(--bg-deep)", border: "1px solid var(--line)" }}>
              <polygon points={region.map((p) => p.join(",")).join(" ")} fill="var(--accent)" fillOpacity={0.18} stroke="var(--accent)" strokeWidth={0.6} />
              <line x1={0} y1={0} x2={10} y2={0} stroke="var(--fg-strong)" strokeWidth={0.6} />
              <line x1={0} y1={0} x2={0} y2={10} stroke="var(--fg-strong)" strokeWidth={0.6} />
              <text x={11} y={1.5} fontSize={4} fill="var(--fg)">+X (recoater)</text>
              <text x={1} y={14} fontSize={4} fill="var(--fg)">+Y</text>
            </svg>
          ) : <div className="hint">No calibrated area recorded.</div>}
          <figcaption className="hint" style={{ margin: "4px 0 0" }}>Calibrated area on the bed (mm, origin = board corner 0): measurements outside it are extrapolated.</figcaption>
        </figure>
      </div>

      <details>
        <summary>Each photo ({last.views.length})</summary>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6, fontVariantNumeric: "tabular-nums" }}>
            <thead><tr><th style={th}>recoater (mm)</th><th style={th}>points</th><th style={th}>chessboard</th><th style={th}>markers</th></tr></thead>
            <tbody>{last.views.map((v, i) => (
              <tr key={i} style={Math.abs(v.recoater_mm - last.capture_mm) < 0.2 ? { background: "var(--warn-bg)" } : undefined}>
                <td style={td}>{v.recoater_mm.toFixed(1)}{Math.abs(v.recoater_mm - last.capture_mm) < 0.2 ? " (capture pose)" : ""}</td>
                <td style={td}>{v.points}</td><td style={td}>{v.chessboard}</td><td style={td}>{v.markers}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

const th: CSSProperties = { textAlign: "left", fontWeight: 500, color: "var(--muted)", borderBottom: "1px solid var(--line)", padding: "4px 8px" };
const td: CSSProperties = { borderBottom: "1px solid var(--line)", padding: "4px 8px", verticalAlign: "top" };
