import { useEffect, useState } from "react";
import { api, type RunMeta } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { parseCaptures, type Capture } from "../../lib/vision.ts";
import {
  hasNativeSpeed,
  layerAccuracySummary,
  motionSeries,
  parseLayerAccuracy,
  type LayerAccuracy,
  type Metric,
} from "../../lib/motion.ts";
import { EventLog } from "../EventLog.tsx";
import type { Call } from "./types.ts";

const STAGE_LABEL: Record<string, string> = { pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat" };
const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} kB`);
const fmtDur = (s?: number | null) => {
  if (s == null || !Number.isFinite(s)) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} m` : m ? `${m} m ${String(sec).padStart(2, "0")} s` : `${sec} s`;
};

// Per-axis trace colors match the machine dock; axis order is the drive numbering (spec §4).
const AXES = [
  { axis: 1, label: "BUILD", token: "var(--trace-part)" },
  { axis: 2, label: "FEED", token: "var(--trace-feed)" },
  { axis: 3, label: "PRINTHEAD", token: "var(--trace-ph)" },
  { axis: 4, label: "RECOATER", token: "var(--trace-rc)" },
] as const;
const METRIC_UNIT: Record<Metric, string> = { pos: "mm", vel: "mm/s", accel: "mm/s²" };
const METRIC_LABEL: Record<Metric, string> = { pos: "position", vel: "velocity", accel: "acceleration" };

/** One axis's metric over time (its own y-scale), for the stacked small-multiples. */
function AxisPanel({ series, tMax, label, color, unit }: { series: { t: number; v: number }[]; tMax: number; label: string; color: string; unit: string }) {
  const W = 560, H = 82, padL = 54, padR = 10, padB = 4, padT = 6, plotH = H - padT - padB, plotW = W - padL - padR;
  const vs = series.map((p) => p.v);
  const lo = Math.min(0, ...vs);
  let hi = Math.max(0, ...vs);
  if (hi - lo < 1e-6) hi = lo + 1;
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  const x = (t: number) => padL + (tMax > 0 ? (t / tMax) * plotW : 0);
  const dec = (v: number) => (Math.abs(v) >= 100 ? "0" : Math.abs(v) >= 10 ? "1" : "2");
  return (
    <svg className="axpanel" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label={`${label} ${unit}`}>
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} />
      {lo < 0 && <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} strokeDasharray="2 3" />}
      <polyline points={series.map((p) => `${x(p.t)},${y(p.v)}`).join(" ")} fill="none" stroke={color} strokeWidth="1.5" />
      <text x={padL + 5} y={padT + 10} fontSize="9.5" fill={color} fontFamily="var(--font-mono)">{label}</text>
      <text x={padL - 6} y={padT + 8} fontSize="8" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">{hi.toFixed(Number(dec(hi)))}</text>
      <text x={padL - 6} y={H - padB} fontSize="8" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">{lo.toFixed(Number(dec(lo)))}</text>
      <text x={padL - 30} y={padT + plotH / 2} fontSize="8" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)" transform={`rotate(-90 ${padL - 30} ${padT + plotH / 2})`}>{unit}</text>
    </svg>
  );
}

/** layer_accuracy.csv → per-layer build-piston deviation (actual − commanded) in microns, as signed
 *  lollipops around a zero line with a ±tolerance band; out-of-tolerance layers flagged red. */
function BuildDeviationChart({ rows, tolUm }: { rows: LayerAccuracy[]; tolUm: number }) {
  const pts = rows
    .filter((r) => (r.phase === "thin_precoat" || r.phase === "printing") && r.deviation_mm != null && r.layer != null)
    .map((r) => ({ layer: r.layer as number, devUm: (r.deviation_mm as number) * 1000 }));
  if (pts.length === 0) return <div className="chart-empty">no build-piston layer data for this run</div>;
  const W = 560, H = 205, padL = 54, padR = 12, padB = 30, padT = 12, plotH = H - padT - padB, plotW = W - padL - padR;
  const maxAbs = Math.max(tolUm * 1.6, ...pts.map((p) => Math.abs(p.devUm))) * 1.08;
  const y = (v: number) => padT + (1 - (v + maxAbs) / (2 * maxAbs)) * plotH;
  const x = (i: number) => padL + (pts.length > 1 ? (i * plotW) / (pts.length - 1) : plotW / 2);
  const zeroY = y(0);
  const stepEvery = Math.max(1, Math.ceil(pts.length / 10));
  return (
    <svg className="mchart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="build-piston per-layer deviation in microns">
      <rect x={padL} y={y(tolUm)} width={plotW} height={y(-tolUm) - y(tolUm)} fill="var(--live-bg)" />
      <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} />
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} />
      {[maxAbs, tolUm, -tolUm, -maxAbs].map((v) => (
        <text key={v} x={padL - 6} y={y(v) + 3} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">{v > 0 ? "+" : ""}{Math.round(v)}</text>
      ))}
      {pts.map((p, i) => {
        const col = Math.abs(p.devUm) <= tolUm ? "var(--trace-part)" : "var(--err)";
        return (
          <g key={p.layer}>
            <line x1={x(i)} y1={zeroY} x2={x(i)} y2={y(p.devUm)} stroke={col} strokeWidth="1.8" />
            <circle cx={x(i)} cy={y(p.devUm)} r="2.6" fill={col} />
            {(i % stepEvery === 0 || i === pts.length - 1) && <text x={x(i)} y={H - padB + 13} fontSize="8" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)">{p.layer}</text>}
          </g>
        );
      })}
      <text x={padL - 34} y={padT + plotH / 2} fontSize="9" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)" transform={`rotate(-90 ${padL - 34} ${padT + plotH / 2})`}>deviation (µm)</text>
      <text x={padL + plotW / 2} y={H - 3} fontSize="9" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)">layer number · shaded band = ±{tolUm} µm tolerance</text>
    </svg>
  );
}

export function RunsView({ status, gates, call, base }: { status: StatusPayload | null; gates: Gates; call: Call; base: string }) {
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [sel, setSel] = useState<string>("");
  const [caps, setCaps] = useState<Capture[]>([]);
  const [motionCsv, setMotionCsv] = useState("");
  const [accuracyRows, setAccuracyRows] = useState<LayerAccuracy[]>([]);
  const [metric, setMetric] = useState<Metric>("vel");
  const [axes, setAxes] = useState<number[]>([1, 2, 3, 4]); // all axes stacked by default
  const [tolUm, setTolUm] = useState("50"); // build-piston tolerance band (µm), editable
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [dirty, setDirty] = useState(false);
  const [viewIdx, setViewIdx] = useState(-1); // index into `caps` of the open lightbox still, or -1
  const [viewJobFolder, setViewJobFolder] = useState<string | null>(null); // for the CAD-slice compare
  const [viewCadErr, setViewCadErr] = useState(false); // CAD slice failed to load (e.g. archived job)
  const rec = status?.recording;
  const viewCap = viewIdx >= 0 && viewIdx < caps.length ? caps[viewIdx] : null;

  const refresh = () => api.recordings().then((r) => {
    setRuns(r.runs);
    setSel((cur) => cur || (r.runs.length ? r.runs[r.runs.length - 1].run : ""));
  }).catch(() => undefined);
  useEffect(() => { refresh(); }, [status?.recording.active, gates.reachable]);

  const selRun = runs.find((r) => r.run === sel) ?? null;
  useEffect(() => { setName(selRun?.name ?? ""); setNotes(selRun?.notes ?? ""); setDirty(false); setViewIdx(-1); }, [sel]); // eslint-disable-line react-hooks/exhaustive-deps

  // Lightbox: fetch the open capture's sidecar to learn its job folder, so we can show the matching
  // CAD slice beside the science-cam image (both are bed-plane-registered → a 1:1 comparison).
  useEffect(() => {
    setViewCadErr(false);
    if (!viewCap?.sidecarUrl) { setViewJobFolder(null); return; }
    let live = true;
    fetch(`${base}${viewCap.sidecarUrl}`).then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (live) setViewJobFolder(j?.job?.folder ?? null); })
      .catch(() => { if (live) setViewJobFolder(null); });
    return () => { live = false; };
  }, [viewIdx, base]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // ?still=N deep-link / capture aid: open a capture ONCE, then strip the param so it
    // doesn't re-open every time this view remounts (e.g. re-clicking the Runs tab).
    if (typeof location === "undefined") return;
    const params = new URLSearchParams(location.search);
    const raw = params.get("still"); // NOTE: Number(null) === 0, so guard the missing param explicitly
    const q = raw === null || raw === "" ? NaN : Number(raw);
    if (Number.isInteger(q) && q >= 0 && q < caps.length) {
      setViewIdx(q);
      params.delete("still");
      const qs = params.toString();
      history.replaceState(null, "", `${location.pathname}${qs ? `?${qs}` : ""}${location.hash}`);
    }
  }, [caps.length]);
  useEffect(() => {
    if (viewIdx < 0) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setViewIdx(-1);
      else if (e.key === "ArrowRight") setViewIdx((i) => Math.min(caps.length - 1, i + 1));
      else if (e.key === "ArrowLeft") setViewIdx((i) => Math.max(0, i - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewIdx, caps.length]);

  useEffect(() => {
    if (!sel) { setCaps([]); setMotionCsv(""); setAccuracyRows([]); return; }
    let live = true;
    api.visionCaptures(sel).then((rc) => { if (live) setCaps(parseCaptures(rc)); }).catch(() => { if (live) setCaps([]); });
    api.recordingFileText(sel, "motion_profiles.csv").then((txt) => { if (live) setMotionCsv(txt); });
    api.recordingFileText(sel, "layer_accuracy.csv").then((txt) => { if (live) setAccuracyRows(txt ? parseLayerAccuracy(txt) : []); });
    return () => { live = false; };
  }, [sel, base]);

  const label = (run: string) => `${run.slice(0, 8)} ${run.slice(9, 11)}:${run.slice(11, 13)}`;
  const dispName = (r: RunMeta) => r.name || r.run.slice(16) || r.run;
  const saveMeta = () => call("save run name/notes", () => api.recordingSetMeta(sel, { name, notes }).then(() => { setDirty(false); return refresh(); }));
  const delRun = () => {
    if (!selRun) return;
    if (window.confirm(`Delete run "${dispName(selRun)}"?\n\nThis permanently removes its stills, telemetry, motion profiles, and all data. This cannot be undone.`)) {
      call("delete run", () => api.recordingDelete(sel).then(() => { setSel(""); setViewIdx(-1); return refresh(); }));
    }
  };

  return (
    <div className="view fixed-page runs-view">
      <div className="row" style={{ marginBottom: 4 }}>
        {rec?.active
          ? <button className="small" onClick={() => call("stop recording", api.recordingStop)}>■ stop recording {rec.run}</button>
          : <button className="small" disabled={!gates.connected} onClick={() => call("record", () => api.recordingStart({ name: "manual", notes: "" }))}>● record now</button>}
        <span className="hint">Every print is recorded automatically — stills, telemetry, motion profiles.</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "262px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <div className="runlist">
          {[...runs].reverse().map((r) => (
            <button key={r.run} className={`runitem${r.run === sel ? " on" : ""}`} onClick={() => setSel(r.run)}>
              <span className="rn">{dispName(r)}</span>
              <span className="rd">{label(r.run)} · {r.layer_count != null ? `${r.layer_count} L` : fmtSize(r.size_bytes)}{r.complete ? "" : " · incomplete"}</span>
            </button>
          ))}
          {runs.length === 0 && <div className="hint">no runs yet</div>}
        </div>

        <div className="grid-gap">
          {selRun ? (
            <>
              <div className="card">
                <h3>{dispName(selRun)} · {label(selRun.run)}
                  <span className="btnrow" style={{ display: "inline-flex" }}>
                    <a className="cta primary sm" href={`${base}/api/recordings/${encodeURIComponent(selRun.run)}/archive.zip`} target="_blank" rel="noreferrer" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>⬇ Download run (.zip)</a>
                    <button className="cta danger sm" disabled={!gates.reachable} onClick={delRun}>Delete run</button>
                  </span>
                </h3>
                <div className="statrow">
                  <div className="stat"><span className="k">Status</span><span className="v">{selRun.complete ? "complete" : "incomplete"}</span></div>
                  <div className="stat"><span className="k">Layers</span><span className="v">{selRun.layer_count ?? "—"}</span></div>
                  <div className="stat"><span className="k">Duration</span><span className="v">{fmtDur(selRun.duration_s)}</span></div>
                  <div className="stat"><span className="k">Stills</span><span className="v">{caps.length}</span></div>
                  <div className="stat"><span className="k">Size</span><span className="v">{fmtSize(selRun.size_bytes)}</span></div>
                </div>
                <div className="zipwrap">{selRun.run}.zip ⟶ vision/ (stills + .json sidecars) · telemetry.csv · motion_profiles.csv · events.json · manifest.json · layers.csv</div>
              </div>

              <div className="card">
                <h3>name &amp; notes</h3>
                <div className="fields" style={{ marginTop: 0, maxWidth: "none", gridTemplateColumns: "auto minmax(0,1fr)" }}>
                  <span>run name</span>
                  <input type="text" placeholder={selRun.run.slice(16) || "run name"} value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} />
                  <span>notes</span>
                  <textarea rows={3} placeholder="observations for this run…" value={notes} onChange={(e) => { setNotes(e.target.value); setDirty(true); }} style={{ resize: "vertical", fontFamily: "var(--font-ui)" }} />
                </div>
                <div className="btnrow" style={{ marginTop: 12 }}>
                  <button className="cta primary sm" disabled={!dirty || !gates.reachable} onClick={saveMeta}>Save name &amp; notes</button>
                </div>
              </div>

              <div className="card">
                <h3>science-cam stills<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>layer × stage</span></h3>
                <div className="stills-wrap">
                  {caps.length === 0 ? <div className="chart-empty">no science-cam captures for this run</div> : (
                    <div className="stills">
                      {caps.slice(0, 24).map((c, i) => (
                        <div key={`${c.layer}-${c.stage}`} className="still" role="button" tabIndex={0}
                          title="open — compare with the CAD layer"
                          onClick={() => setViewIdx(i)}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setViewIdx(i); } }}>
                          <img src={`${base}${c.url}`} alt={`layer ${c.layer} ${c.stage}`} onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                          <span className="ll">L{c.layer}</span><span className="lb">{STAGE_LABEL[c.stage] ?? c.stage}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="card">
                <h3>build-piston layer accuracy{(() => {
                  const s = layerAccuracySummary(accuracyRows);
                  return s.n > 0 ? <span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>mean |dev| {(s.meanAbsDevMm! * 1000).toFixed(0)} µm · max {(s.maxAbsDevMm! * 1000).toFixed(0)} µm (layer {s.maxLayer}) · n={s.n}</span> : null;
                })()}</h3>
                <div className="chart-controls">
                  <span className="hint" style={{ marginTop: 0 }}>tolerance band ±</span>
                  <input type="number" inputMode="decimal" value={tolUm} onChange={(e) => setTolUm(e.target.value)} style={{ width: 64 }} aria-label="tolerance band (microns)" />
                  <span className="hint" style={{ marginTop: 0 }}>µm</span>
                </div>
                <BuildDeviationChart rows={accuracyRows} tolUm={Math.max(1, Number(tolUm) || 50)} />
              </div>

              <div className="card">
                <h3>motion profiles — per axis{hasNativeSpeed(motionCsv) ? <span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>velocity = native measured speed</span> : null}</h3>
                <div className="chart-controls">
                  <span className="seg">{(["pos", "vel", "accel"] as Metric[]).map((m) => <button key={m} type="button" className={metric === m ? "on" : ""} onClick={() => setMetric(m)}>{METRIC_LABEL[m]}</button>)}</span>
                  <span className="chart-axes">{AXES.map((a) => {
                    const on = axes.includes(a.axis);
                    return (
                      <button key={a.axis} type="button" className={`axtog${on ? " on" : ""}`} style={on ? { borderColor: a.token, color: a.token } : undefined} aria-pressed={on}
                        onClick={() => setAxes((cur) => cur.includes(a.axis) ? cur.filter((x) => x !== a.axis) : [...cur, a.axis])}>{a.label}</button>
                    );
                  })}</span>
                </div>
                {(() => {
                  const panels = AXES.filter((a) => axes.includes(a.axis))
                    .map((a) => ({ meta: a, s: motionSeries(motionCsv, metric, a.axis) }))
                    .filter((p) => p.s.length >= 2);
                  if (panels.length === 0) return <div className="chart-empty">no motion profile for this run (or no axis selected)</div>;
                  const tMax = Math.max(1, ...panels.map((p) => p.s[p.s.length - 1].t));
                  return (
                    <div className="axpanels">
                      {panels.map((p) => <AxisPanel key={p.meta.axis} series={p.s} tMax={tMax} label={p.meta.label} color={p.meta.token} unit={METRIC_UNIT[metric]} />)}
                      <div className="axtime">time → 0 … {tMax.toFixed(1)} s · {METRIC_LABEL[metric]}, each axis auto-scaled</div>
                    </div>
                  );
                })()}
              </div>
            </>
          ) : <div className="card"><div className="chart-empty">select a run to see its stills, motion profile, and download.</div></div>}

          <div className="card">
            <h3>event log</h3>
            <div className="stills-wrap"><EventLog events={status?.events ?? []} title="" /></div>
          </div>
        </div>
      </div>

      {viewCap && (
        <div className="lightbox" role="dialog" aria-modal="true" aria-label="science-cam still" onClick={() => setViewIdx(-1)}>
          <div className="lb-body" onClick={(e) => e.stopPropagation()}>
            <div className="lb-h">
              <span>layer {viewCap.layer} · {STAGE_LABEL[viewCap.stage] ?? viewCap.stage}</span>
              <button className="iconbtn" onClick={() => setViewIdx(-1)} aria-label="close">✕</button>
            </div>
            <div className="lb-compare">
              <div className="cmp"><div className="cmp-h">science cam</div>
                <img className="cmp-img" src={`${base}${viewCap.url}`} alt={`science cam layer ${viewCap.layer} ${viewCap.stage}`} /></div>
              <div className="cmp"><div className="cmp-h">CAD slice</div>
                {viewJobFolder && !viewCadErr
                  ? <img className="cmp-img" src={api.jobLayerByFolderUrl(viewCap.layer, viewJobFolder)} alt={`CAD layer ${viewCap.layer}`} onError={() => setViewCadErr(true)} />
                  : <div className="cmp-img chart-empty" style={{ display: "grid", placeItems: "center", textAlign: "center", padding: 16 }}>{viewJobFolder ? "CAD slice unavailable — its sliced job isn't loaded" : "CAD slice unavailable for this run"}</div>}
              </div>
            </div>
            <div className="lb-nav">
              <button className="small" disabled={viewIdx <= 0} onClick={() => setViewIdx((i) => Math.max(0, i - 1))}>← prev</button>
              <span>{viewIdx + 1} / {caps.length}</span>
              <button className="small" disabled={viewIdx >= caps.length - 1} onClick={() => setViewIdx((i) => Math.min(caps.length - 1, i + 1))}>next →</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
