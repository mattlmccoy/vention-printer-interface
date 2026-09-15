import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { api, type DimensionalReport, type RunMeta } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import { analysisStatusKind, analysisStatusMessage, calibrationChip, compensationRows, featureTiles, roiEditPrompt } from "../../lib/analysis.ts";
import { roiBoxesFromCircle, type Circle } from "../../lib/roi.ts";
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

/**
 * ROI-edit overlay: the registered still with a draggable Ø100 circle and the four derived ROI
 * boxes drawn live. The SVG viewBox equals the still's NATURAL pixel size, so SVG user-units are
 * still pixels; the circle/boxes are therefore already in the coordinates the backend expects.
 * Pointer coords are mapped client→user via the SVG's getBoundingClientRect scale (no letterbox,
 * because the overlay exactly covers the natural-aspect image).
 */
function RoiEditor({ stillUrl, circle, natSize, onChange, onLoad }: {
  stillUrl: string;
  circle: Circle | null;
  natSize: { w: number; h: number } | null;
  onChange: (c: Circle) => void;
  onLoad: (w: number, h: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ mode: "body" | "rim"; dx: number; dy: number } | null>(null);

  const toUser = (e: ReactPointerEvent): { x: number; y: number } | null => {
    const svg = svgRef.current;
    if (!svg || !natSize) return null;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: ((e.clientX - rect.left) / rect.width) * natSize.w,
      y: ((e.clientY - rect.top) / rect.height) * natSize.h,
    };
  };

  const clamp = (c: Circle): Circle => {
    if (!natSize) return c;
    const cx = Math.min(Math.max(c.cx, 0), natSize.w);
    const cy = Math.min(Math.max(c.cy, 0), natSize.h);
    const radius = Math.min(Math.max(c.radius, 4), Math.max(natSize.w, natSize.h));
    return { cx, cy, radius };
  };

  const onDownBody = (e: ReactPointerEvent) => {
    if (!circle) return;
    const p = toUser(e); if (!p) return;
    drag.current = { mode: "body", dx: p.x - circle.cx, dy: p.y - circle.cy };
    svgRef.current?.setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const onDownRim = (e: ReactPointerEvent) => {
    if (!circle) return;
    drag.current = { mode: "rim", dx: 0, dy: 0 };
    svgRef.current?.setPointerCapture(e.pointerId);
    e.stopPropagation(); e.preventDefault();
  };
  const onMove = (e: ReactPointerEvent) => {
    if (!drag.current || !circle) return;
    const p = toUser(e); if (!p) return;
    if (drag.current.mode === "body") onChange(clamp({ ...circle, cx: p.x - drag.current.dx, cy: p.y - drag.current.dy }));
    else onChange(clamp({ ...circle, radius: Math.hypot(p.x - circle.cx, p.y - circle.cy) }));
  };
  const onUp = (e: ReactPointerEvent) => {
    drag.current = null;
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* capture already released */ }
  };

  const boxes = circle ? roiBoxesFromCircle(circle) : {};
  const dim = natSize ? Math.max(natSize.w, natSize.h) : 0;
  const strokeW = dim * 0.0035 || 2;
  const handleR = dim * 0.012 || 6;

  return (
    <div className="roi-edit">
      <img
        className="roi-still"
        src={stillUrl}
        alt="registered science-cam capture"
        onLoad={(e) => onLoad(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
        onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
      />
      {circle && natSize && (
        <svg ref={svgRef} className="roi-overlay" viewBox={`0 0 ${natSize.w} ${natSize.h}`}
          onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
          {Object.entries(boxes).map(([feat, b]) => (
            <g key={feat}>
              <rect className="roi-box" x={b.x} y={b.y} width={b.w} height={b.h} strokeWidth={strokeW} />
              <text className="roi-box-label" x={b.x + strokeW * 1.5} y={b.y - strokeW} fontSize={handleR * 1.5}>{feat}</text>
            </g>
          ))}
          <circle className="roi-circle" cx={circle.cx} cy={circle.cy} r={circle.radius} strokeWidth={strokeW} onPointerDown={onDownBody} />
          <circle className="roi-handle" cx={circle.cx + circle.radius} cy={circle.cy} r={handleR} strokeWidth={strokeW} onPointerDown={onDownRim} />
        </svg>
      )}
    </div>
  );
}

export function AnalysisView({ gates, call, base }: { gates: Gates; call: Call; base: string }) {
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [sel, setSel] = useState("");
  const [report, setReport] = useState<DimensionalReport | null>(null);
  const [trend, setTrend] = useState<{ run: string; scale_x: number }[]>([]);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [circle, setCircle] = useState<Circle | null>(null);
  const [natSize, setNatSize] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => { api.recordings().then((r) => { setRuns(r.runs); setSel((c) => c || (r.runs.length ? r.runs[r.runs.length - 1].run : "")); }).catch(() => undefined); }, []);
  useEffect(() => {
    if (!sel) { setReport(null); return; }
    let live = true; setCopied(false); setEditing(false); setCircle(null); setNatSize(null);
    api.analysisGet(sel).then((r) => { if (live) setReport(r); }).catch(() => { if (live) setReport(null); });
    return () => { live = false; };
  }, [sel]);
  // Auto-enter ROI-edit mode when auto-location failed (fires only on report change, so a Cancel
  // that leaves the roi_failed report in place does not re-open the editor).
  useEffect(() => { if (report?.status === "roi_failed") setEditing(true); }, [report]);
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
  const calWarn = report ? calibrationChip(report) : null;
  const roiPrompt = roiEditPrompt(status);
  const analyze = () => call("analyze run", () => api.analysisRun(sel).then(setReport));
  const copy = () => { if (comp?.human) { navigator.clipboard?.writeText(comp.human).then(() => setCopied(true)).catch(() => undefined); } };
  // Seed the initial circle once the still's natural size is known: centered, radius ~40% of the
  // smaller dimension — a visible starting point the operator drags onto the real Ø100 outline.
  const onStillLoad = (w: number, h: number) => {
    setNatSize({ w, h });
    setCircle((c) => c ?? { cx: w / 2, cy: h / 2, radius: 0.4 * Math.min(w, h) });
  };
  const analyzeCircle = () => {
    if (!circle) return;
    call("analyze run", () => api.analysisRun(sel, { circle: { cx_px: circle.cx, cy_px: circle.cy, radius_px: circle.radius } }).then((r) => { setReport(r); setEditing(false); }));
  };

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
                {calWarn && <div style={{ marginTop: 6 }}><span className="chip warn" title="the marked circle and the camera calibration disagree — the circle scale is being used">{calWarn}</span></div>}
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
                <h3>registered capture<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>{editing ? "drag the circle onto the Ø100 outline — the four ROIs follow" : "analyzed regions outlined"}</span></h3>
                <div className="stills-wrap">
                  {!stillUrl ? (
                    <div className="chart-empty">no registered capture to show for this run</div>
                  ) : editing ? (
                    <>
                      {roiPrompt && <div className="banner err" style={{ marginBottom: 12 }}><span className="reason">{roiPrompt}</span></div>}
                      <RoiEditor stillUrl={stillUrl} circle={circle} natSize={natSize} onChange={setCircle} onLoad={onStillLoad} />
                      <div className="btnrow" style={{ marginTop: 12 }}>
                        <button className="cta primary sm" disabled={!gates.reachable || !circle} onClick={analyzeCircle}>Analyze with this circle</button>
                        <button className="cta sm" onClick={() => setEditing(false)}>Cancel</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ position: "relative", maxWidth: 480, margin: "0 auto" }}>
                        <img className="cmp-img" src={stillUrl} alt="registered science-cam capture" onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                      </div>
                      <div className="btnrow" style={{ marginTop: 12 }}>
                        <button className="cta sm" onClick={() => setEditing(true)}>Adjust ROIs</button>
                      </div>
                    </>
                  )}
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
