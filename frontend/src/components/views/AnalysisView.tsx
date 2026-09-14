import { useEffect, useState } from "react";
import { api, type DimensionalReport, type RunMeta } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import { analysisStatusKind, analysisStatusMessage, compensationRows, featureTiles } from "../../lib/analysis.ts";
import type { Call } from "./types.ts";

const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} kB`);
const label = (run: string) => `${run.slice(0, 8)} ${run.slice(9, 11)}:${run.slice(11, 13)}`;
const dispName = (r: RunMeta) => r.name || r.run.slice(16) || r.run;
const capturePath = (layer: number, stage: string) => `vision/layer_${String(layer).padStart(4, "0")}/${stage}.png`;

/** Calibration trend: scale-X across analyzed runs (chronological). */
function TrendChart({ points }: { points: { run: string; scale_x: number }[] }) {
  if (points.length < 2) return <div className="chart-empty">the calibration trend appears once two or more runs are analyzed</div>;
  const W = 520, H = 130, padL = 40, padB = 18, padT = 10;
  const xs = points.map((p) => p.scale_x);
  const lo = Math.min(...xs, 1), hi = Math.max(...xs, 1);
  const span = hi - lo || 1;
  const step = (W - padL) / (points.length - 1);
  const y = (v: number) => padT + (1 - (v - lo) / span) * (H - padT - padB);
  const pts = points.map((p, i) => `${padL + i * step},${y(p.scale_x)}`).join(" ");
  return (
    <svg className="mchart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="scale-X across analyzed runs">
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} />
      <line x1={padL} y1={H - padB} x2={W} y2={H - padB} />
      <line x1={padL} y1={y(1)} x2={W} y2={y(1)} stroke="var(--faint)" strokeDasharray="3 3" />
      <text x={padL - 6} y={y(1) + 3} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">1.000</text>
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {points.map((p, i) => <circle key={p.run} cx={padL + i * step} cy={y(p.scale_x)} r="3" fill="var(--accent)" />)}
      <text x={(W + padL) / 2} y={H - 4} fontSize="9" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)">scale-X · analyzed runs (oldest → newest)</text>
    </svg>
  );
}

export function AnalysisView({ gates, call, base }: { gates: Gates; call: Call; base: string }) {
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [sel, setSel] = useState("");
  const [report, setReport] = useState<DimensionalReport | null>(null);
  const [trend, setTrend] = useState<{ run: string; scale_x: number }[]>([]);
  const [copied, setCopied] = useState(false);

  useEffect(() => { api.recordings().then((r) => { setRuns(r.runs); setSel((c) => c || (r.runs.length ? r.runs[r.runs.length - 1].run : "")); }).catch(() => undefined); }, []);
  useEffect(() => {
    if (!sel) { setReport(null); return; }
    let live = true; setCopied(false);
    api.analysisGet(sel).then((r) => { if (live) setReport(r); }).catch(() => { if (live) setReport(null); });
    return () => { live = false; };
  }, [sel]);
  useEffect(() => { // best-effort calibration trend across all analyzed runs
    let live = true;
    Promise.all(runs.map((r) => api.analysisGet(r.run).then((rep) => rep).catch(() => null)))
      .then((reps) => { if (!live) return; setTrend(reps.filter((x): x is DimensionalReport => !!x && x.status === "ok" && !!x.compensation).map((x) => ({ run: x.run, scale_x: x.compensation!.scale_x }))); });
    return () => { live = false; };
  }, [runs]);

  const selRun = runs.find((r) => r.run === sel) ?? null;
  const status = report?.status ?? "not_run";
  const kind = analysisStatusKind(status);
  const comp = report?.compensation ?? null;
  const tiles = report ? featureTiles(report) : [];
  const analyze = () => call("analyze run", () => api.analysisRun(sel).then(setReport));
  const copy = () => { if (comp?.human) { navigator.clipboard?.writeText(comp.human).then(() => setCopied(true)).catch(() => undefined); } };

  const cf = report?.captured_from ?? null;
  const stillUrl = cf && typeof cf.layer === "number" && cf.stage
    ? `${base}/api/vision/runs/${encodeURIComponent(sel)}/file?path=${encodeURIComponent(capturePath(cf.layer, cf.stage))}` : null;

  return (
    <div className="view fixed-page analysis-view">
      <div className="sec-h">dimensional accuracy · print the gold-standard target, capture it, measure vs CAD →</div>
      <div style={{ display: "grid", gridTemplateColumns: "262px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <div className="runlist">
          {[...runs].reverse().map((r) => (
            <button key={r.run} className={`runitem${r.run === sel ? " on" : ""}`} onClick={() => setSel(r.run)}>
              <span className="rn">{dispName(r)}</span>
              <span className="rd">{label(r.run)} · {r.layer_count != null ? `${r.layer_count} L` : fmtSize(r.size_bytes)}</span>
            </button>
          ))}
          {runs.length === 0 && <div className="hint">no runs yet</div>}
        </div>

        <div className="grid-gap">
          {!selRun ? <div className="card"><div className="chart-empty">select a run to analyze its dimensional accuracy.</div></div> : (
            <>
              <div className="card">
                <h3>{dispName(selRun)} · {label(selRun.run)}
                  <span className={`state-pill ${kind === "ok" ? "ok" : kind === "empty" ? "" : "bad"}`}>{status.replace("_", " ")}</span>
                </h3>
                {kind !== "ok" && (
                  <div className={`banner ${kind === "error" ? "err" : ""}`} style={{ marginTop: 4 }}>
                    <span className="reason">{analysisStatusMessage(status, report?.message)}</span>
                    <button className="cta sm primary" disabled={!gates.reachable} style={{ marginLeft: "auto" }} onClick={analyze}>Analyze this run</button>
                  </div>
                )}
                {kind === "ok" && comp && (
                  <>
                    <div className="sec-h" style={{ marginTop: 6 }}>geometric compensation — apply upstream in CAD / slicer / RIP config</div>
                    <div className="cards-3" style={{ marginTop: 8 }}>
                      {compensationRows(comp).map((r) => (
                        <div key={r.label} className="anl-comp">
                          <span className="k">{r.label}</span><span className="v">{r.value}</span><span className="s">{r.sub}</span>
                        </div>
                      ))}
                    </div>
                    <div className="btnrow" style={{ marginTop: 12 }}>
                      <button className="cta primary sm" onClick={copy}>{copied ? "copied ✓" : "Copy compensation"}</button>
                      <button className="cta sm" disabled={!gates.reachable} onClick={analyze}>Re-analyze</button>
                    </div>
                  </>
                )}
              </div>

              <div className="card">
                <h3>per-feature metrics</h3>
                <div className="statrow">
                  {tiles.length ? tiles.map((t) => <div key={t.k} className="stat"><span className="k">{t.k}</span><span className="v">{t.v}</span></div>)
                    : <div className="chart-empty" style={{ minHeight: 80 }}>no per-feature metrics — analyze a gold-standard capture to populate.</div>}
                </div>
                {report?.px_per_mm != null && <div className="hint" style={{ marginTop: 8 }}>captured layer {cf?.layer} · {cf?.stage} · {report.px_per_mm.toFixed(1)} px/mm</div>}
              </div>

              <div className="card">
                <h3>registered capture<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>analyzed regions outlined</span></h3>
                <div className="stills-wrap">
                  {stillUrl ? (
                    <div style={{ position: "relative", maxWidth: 480, margin: "0 auto" }}>
                      <img className="cmp-img" src={stillUrl} alt="registered science-cam capture" onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                    </div>
                  ) : <div className="chart-empty">no registered capture to show for this run</div>}
                </div>
              </div>

              <div className="card">
                <h3>calibration trend</h3>
                <TrendChart points={trend} />
              </div>

              <div className="card">
                <h3>provenance</h3>
                <div className="zipwrap">
                  report-only · apply the correction upstream (CAD / slicer, or the Meteor RIP rip_scale_x/y) — the console does not re-slice.
                  {report?.tool_provenance?.source ? ` · analysis: ${String(report.tool_provenance.source)}` : ""}
                  {report?.generated_utc ? ` · generated ${report.generated_utc}` : ""}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
