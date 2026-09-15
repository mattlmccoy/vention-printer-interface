import { useEffect, useState, type MouseEvent as ReactMouseEvent } from "react";
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

// Analysis-plot palette: the calm seaborn-"muted" set (NOT the vivid live --trace-* dock colours).
// Axis order is the drive numbering (spec §4).
const AXES = [
  { axis: 1, label: "BUILD", token: "var(--plot-1)" },
  { axis: 2, label: "FEED", token: "var(--plot-2)" },
  { axis: 3, label: "PRINTHEAD", token: "var(--plot-3)" },
  { axis: 4, label: "RECOATER", token: "var(--plot-4)" },
] as const;
// Sans (not the instrument mono) for chart text, so the plots read as analysis figures. Tabular
// figures keep the numeric ticks aligned.
const PLOT_FONT = "var(--font-ui)";
const METRIC_UNIT: Record<Metric, string> = { pos: "mm", vel: "mm/s", accel: "mm/s²" };
const METRIC_LABEL: Record<Metric, string> = { pos: "position", vel: "velocity", accel: "acceleration" };

/** One axis's metric over time (its own y-scale), for the stacked small-multiples. */
function AxisPanel({ series, tMax, label, color, unit }: { series: { t: number; v: number }[]; tMax: number; label: string; color: string; unit: string }) {
  const [hi2, setHi2] = useState<number | null>(null);
  const W = 560, H = 82, padL = 54, padR = 10, padB = 4, padT = 6, plotH = H - padT - padB, plotW = W - padL - padR;
  const vs = series.map((p) => p.v);
  const lo = Math.min(0, ...vs);
  let hi = Math.max(0, ...vs);
  if (hi - lo < 1e-6) hi = lo + 1;
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  const x = (t: number) => padL + (tMax > 0 ? (t / tMax) * plotW : 0);
  const dec = (v: number) => (Math.abs(v) >= 100 ? "0" : Math.abs(v) >= 10 ? "1" : "2");
  const mid = (lo + hi) / 2;
  const tnum = { fontVariantNumeric: "tabular-nums" } as const;
  const onMove = (e: ReactMouseEvent<SVGSVGElement>) => {
    if (series.length === 0) return;
    const r = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;          // client px -> viewBox x
    const t = tMax * (vx - padL) / plotW;
    let best = 0, bd = Infinity;
    for (let i = 0; i < series.length; i++) { const d = Math.abs(series[i].t - t); if (d < bd) { bd = d; best = i; } }
    setHi2(best);
  };
  const hp = hi2 != null ? series[hi2] : null;
  return (
    <svg className="axpanel" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label={`${label} ${unit}`}
      onMouseMove={onMove} onMouseLeave={() => setHi2(null)}>
      {/* seaborn whitegrid: faint horizontal gridlines, no boxed spines */}
      {[hi, mid, lo].map((v) => <line key={v} x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="var(--line)" strokeWidth="1" />)}
      {lo < 0 && <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} stroke="var(--faint)" strokeWidth="1" strokeDasharray="2 3" />}
      <polyline points={series.map((p) => `${x(p.t)},${y(p.v)}`).join(" ")} fill="none" stroke={color} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      {hp && <line x1={x(hp.t)} y1={padT} x2={x(hp.t)} y2={H - padB} stroke="var(--faint)" strokeWidth="1" strokeDasharray="2 2" pointerEvents="none" />}
      {hp && <circle cx={x(hp.t)} cy={y(hp.v)} r={3} fill={color} pointerEvents="none" />}
      <text x={padL + 5} y={padT + 10} fontSize="10" fill="var(--muted)" fontFamily={PLOT_FONT} fontWeight={500}>{label}</text>
      {hp && <text x={W - padR} y={padT + 10} fontSize="9" fill="var(--fg-strong)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum} pointerEvents="none">{hp.t.toFixed(1)} s · {hp.v.toFixed(Number(dec(hp.v)))} {unit}</text>}
      <text x={padL - 6} y={padT + 8} fontSize="8.5" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum}>{hi.toFixed(Number(dec(hi)))}</text>
      <text x={padL - 6} y={H - padB} fontSize="8.5" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum}>{lo.toFixed(Number(dec(lo)))}</text>
      <text x={padL - 30} y={padT + plotH / 2} fontSize="8.5" fill="var(--faint)" textAnchor="middle" fontFamily={PLOT_FONT} transform={`rotate(-90 ${padL - 30} ${padT + plotH / 2})`}>{unit}</text>
    </svg>
  );
}

/** layer_accuracy.csv → per-layer build-piston deviation (actual − commanded) in microns, as signed
 *  lollipops around a zero line with a ±tolerance band; out-of-tolerance layers flagged red. */
function BuildDeviationChart({ rows, tolUm }: { rows: LayerAccuracy[]; tolUm: number }) {
  const [hov, setHov] = useState<number | null>(null);
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
  const tnum = { fontVariantNumeric: "tabular-nums" } as const;
  const nOut = pts.filter((p) => Math.abs(p.devUm) > tolUm).length;
  return (
    <svg className="mchart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="build-piston per-layer deviation in microns">
      {/* neutral tolerance band (not a semantic colour) + faint whitegrid at each tick */}
      <rect x={padL} y={y(tolUm)} width={plotW} height={y(-tolUm) - y(tolUm)} fill="var(--plot-band)" />
      {[maxAbs, tolUm, -tolUm, -maxAbs].map((v) => (
        <line key={v} x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="var(--line)" strokeWidth="1"
          strokeDasharray={Math.abs(v) === tolUm ? "3 3" : undefined} />
      ))}
      <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="var(--faint)" strokeWidth="1" />
      {[maxAbs, tolUm, -tolUm, -maxAbs].map((v) => (
        <text key={v} x={padL - 8} y={y(v) + 3} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum}>{v > 0 ? "+" : ""}{Math.round(v)}</text>
      ))}
      {pts.map((p, i) => {
        const col = Math.abs(p.devUm) <= tolUm ? "var(--plot-1)" : "var(--plot-warn)";
        const on = hov === i;
        return (
          <g key={p.layer}>
            <line x1={x(i)} y1={zeroY} x2={x(i)} y2={y(p.devUm)} stroke={col} strokeWidth={on ? 1.8 : 1.3} />
            <circle cx={x(i)} cy={y(p.devUm)} r={on ? 3.6 : 2.4} fill={col} />
            {(i % stepEvery === 0 || i === pts.length - 1) && <text x={x(i)} y={H - padB + 13} fontSize="8.5" fill="var(--faint)" textAnchor="middle" fontFamily={PLOT_FONT} style={tnum}>{p.layer}</text>}
          </g>
        );
      })}
      {/* wide invisible hit targets so points are easy to hover; native <title> is the fallback */}
      {pts.map((p, i) => (
        <circle key={`hit-${p.layer}`} cx={x(i)} cy={y(p.devUm)} r={9} fill="transparent"
          onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)} style={{ cursor: "pointer" }}>
          <title>{`layer ${p.layer}: ${p.devUm >= 0 ? "+" : ""}${Math.round(p.devUm)} µm`}</title>
        </circle>
      ))}
      {hov != null && (() => {
        const p = pts[hov];
        const out = Math.abs(p.devUm) > tolUm;
        const dv = Number(p.devUm.toFixed(1)) + 0;  // normalize -0.0 -> 0.0
        const label = `L${p.layer}   ${dv >= 0 ? "+" : ""}${dv.toFixed(1)} µm`;
        const boxW = Math.max(84, label.length * 6.4), boxH = 30;
        const bx = Math.max(padL, Math.min(x(hov) - boxW / 2, W - padR - boxW));
        const above = y(p.devUm) > padT + boxH + 10;
        const by = above ? y(p.devUm) - boxH - 9 : y(p.devUm) + 9;
        return (
          <g pointerEvents="none">
            <rect x={bx} y={by} width={boxW} height={boxH} rx={4} fill="var(--panel)" stroke="var(--line-strong)" strokeWidth="1" />
            <text x={bx + boxW / 2} y={by + 13} fontSize="10" fill="var(--fg-strong)" textAnchor="middle" fontFamily={PLOT_FONT} style={tnum}>{label}</text>
            <text x={bx + boxW / 2} y={by + 24} fontSize="8.5" fill={out ? "var(--plot-warn)" : "var(--muted)"} textAnchor="middle" fontFamily={PLOT_FONT}>{out ? `outside ±${tolUm} µm` : `within ±${tolUm} µm`}</text>
          </g>
        );
      })()}
      <text x={padL - 34} y={padT + plotH / 2} fontSize="9.5" fill="var(--muted)" textAnchor="middle" fontFamily={PLOT_FONT} transform={`rotate(-90 ${padL - 34} ${padT + plotH / 2})`}>deviation (µm)</text>
      <text x={padL + plotW / 2} y={H - 3} fontSize="9.5" fill="var(--faint)" textAnchor="middle" fontFamily={PLOT_FONT}>layer number{nOut > 0 ? ` · ${nOut} of ${pts.length} outside ±${tolUm} µm` : ` · all ${pts.length} within ±${tolUm} µm`}</text>
    </svg>
  );
}

/** Cumulative build height: commanded vs actual, layer by layer. The gap between the lines is the
 *  real drift — the headline answer to "is the build the right height." (Plot approach A.) */
function CumulativeHeightChart({ rows }: { rows: LayerAccuracy[] }) {
  const [hov, setHov] = useState<number | null>(null);
  const pts = rows
    .filter((r) => r.commanded_cum_mm != null && r.actual_cum_mm != null && r.layer != null)
    .map((r) => ({ layer: r.layer as number, cmd: r.commanded_cum_mm as number, act: r.actual_cum_mm as number }));
  if (pts.length === 0) return <div className="chart-empty">no build-piston layer data for this run</div>;
  const W = 560, H = 190, padL = 46, padR = 14, padB = 28, padT = 14, plotH = H - padT - padB, plotW = W - padL - padR;
  const ymax = Math.max(...pts.map((p) => Math.max(p.cmd, p.act))) * 1.12 || 1;
  const X = (i: number) => padL + (pts.length > 1 ? (i * plotW) / (pts.length - 1) : plotW / 2);
  const Y = (v: number) => padT + plotH * (1 - v / ymax);
  const tnum = { fontVariantNumeric: "tabular-nums" } as const;
  const end = pts[pts.length - 1];
  const line = (key: "cmd" | "act") => pts.map((p, i) => `${X(i)},${Y(p[key])}`).join(" ");
  return (
    <svg className="mchart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="cumulative build height, commanded vs actual">
      {[0, 1, 2, 3, 4].map((g) => { const v = ymax * g / 4; return <g key={g}><line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--line)" strokeWidth="1" /><text x={padL - 6} y={Y(v) + 3} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum}>{v.toFixed(1)}</text></g>; })}
      <polyline points={line("cmd")} fill="none" stroke="var(--faint)" strokeWidth="1.6" strokeDasharray="4 4" />
      <polyline points={line("act")} fill="none" stroke="var(--plot-1)" strokeWidth="2" strokeLinejoin="round" />
      {pts.map((p, i) => (
        <g key={p.layer}>
          <circle cx={X(i)} cy={Y(p.act)} r={hov === i ? 4 : 2.6} fill="var(--plot-1)" />
          <circle cx={X(i)} cy={Y(p.act)} r={9} fill="transparent" onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)} style={{ cursor: "pointer" }}>
            <title>{`layer ${p.layer}: actual ${p.act.toFixed(2)} mm / commanded ${p.cmd.toFixed(2)} mm (gap ${((p.act - p.cmd) * 1000 >= 0 ? "+" : "") + ((p.act - p.cmd) * 1000).toFixed(0)} µm)`}</title>
          </circle>
          <text x={X(i)} y={H - padB + 14} fontSize="8.5" fill="var(--faint)" textAnchor="middle" fontFamily={PLOT_FONT} style={tnum}>{p.layer}</text>
        </g>
      ))}
      <text x={padL} y={padT - 3} fontSize="9.5" fill="var(--muted)" fontFamily={PLOT_FONT}>height (mm)</text>
      <text x={W - padR} y={padT + 8} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT} style={tnum}>actual {end.act.toFixed(2)} / commanded {end.cmd.toFixed(2)} mm</text>
      <text x={W - padR} y={H - 3} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily={PLOT_FONT}>— — commanded    —— actual · layer number →</text>
    </svg>
  );
}

/** Activity timeline: a lane per axis, filled where the axis is actually moving (|v| > threshold).
 *  The gaps are dead time between commands — the inter-step latency, made visible. (Approach G.) */
function ActivityTimeline({ csv, axisList }: { csv: string; axisList: readonly { axis: number; label: string; token: string }[] }) {
  const series = axisList.map((a) => ({ ...a, s: motionSeries(csv, "vel", a.axis) })).filter((a) => a.s.length >= 2);
  if (series.length === 0) return null;
  const tMax = Math.max(1, ...series.map((a) => a.s[a.s.length - 1].t));
  const W = 560, laneH = 26, l = 62, r = 12, t = 6, b = 22, TH = 0.5;
  const H = series.length * laneH + t + b;
  const X = (tt: number) => l + (W - l - r) * tt / tMax;
  const tnum = { fontVariantNumeric: "tabular-nums" } as const;
  const segs = (s: { t: number; v: number }[]) => {
    const out: [number, number][] = []; let start: number | null = null;
    for (let i = 0; i < s.length; i++) {
      const mv = Math.abs(s[i].v) > TH;
      if (mv && start == null) start = s[i].t;
      if ((!mv || i === s.length - 1) && start != null) { out.push([start, s[i].t]); start = null; }
    }
    return out;
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="per-axis activity timeline">
      {series.map((a, i) => {
        const top = t + i * laneH;
        return (
          <g key={a.axis}>
            <rect x={l} y={top + 3} width={W - l - r} height={laneH - 10} fill="var(--plot-band)" rx="3" />
            <text x={l - 8} y={top + laneH / 2 - 1} fontSize="10" fill={a.token} textAnchor="end" fontFamily={PLOT_FONT} fontWeight={500}>{a.label}</text>
            {segs(a.s).map(([s0, s1], k) => <rect key={k} x={X(s0)} y={top + 3} width={Math.max(1.5, X(s1) - X(s0))} height={laneH - 10} fill={a.token} rx="2"><title>{`${a.label} moving ${s0.toFixed(1)}–${s1.toFixed(1)} s`}</title></rect>)}
          </g>
        );
      })}
      {[0, 1, 2, 3, 4, 5, 6].map((g) => { const tt = tMax * g / 6; return <text key={g} x={X(tt)} y={H - b + 16} fontSize="8.5" fill="var(--faint)" textAnchor="middle" fontFamily={PLOT_FONT} style={tnum}>{tt.toFixed(0)}</text>; })}
      <text x={W - r} y={H - b + 16} fontSize="9" fill="var(--muted)" textAnchor="end" fontFamily={PLOT_FONT}>time (s) — gaps = idle between commands</text>
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
                <div className="hint" style={{ margin: "0 0 6px", textTransform: "none", letterSpacing: 0 }}>cumulative height — commanded vs actual (the real drift is the gap)</div>
                <CumulativeHeightChart rows={accuracyRows} />
                <div className="chart-controls" style={{ marginTop: 14, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
                  <span className="hint" style={{ marginTop: 0, textTransform: "none", letterSpacing: 0 }}>per-layer deviation · tolerance band ±</span>
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
                <div className="hint" style={{ margin: "16px 0 6px", textTransform: "none", letterSpacing: 0, borderTop: "1px solid var(--line)", paddingTop: 12 }}>activity timeline — filled where the axis is moving; the gaps are idle time between commands</div>
                <ActivityTimeline csv={motionCsv} axisList={AXES.filter((a) => axes.includes(a.axis))} />
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
