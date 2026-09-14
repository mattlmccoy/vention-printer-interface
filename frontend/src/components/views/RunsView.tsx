import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { parseCaptures, type Capture } from "../../lib/vision.ts";
import { EventLog } from "../EventLog.tsx";
import type { Call } from "./types.ts";

const STAGE_LABEL: Record<string, string> = { pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat" };
const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} kB`);

/** Parse motion_profiles.csv into a per-axis velocity series for the chart. Columns:
 *  host_timestamp_ns, pos_1..4, vel_1..4, accel_1..4. Blank cells (uncomputable) are skipped. */
function parseVel(csv: string, axis: number): number[] {
  const lines = csv.trim().split("\n");
  if (lines.length < 2) return [];
  const cols = lines[0].split(",");
  const idx = cols.indexOf(`vel_${axis}`);
  if (idx < 0) return [];
  const out: number[] = [];
  for (const line of lines.slice(1)) {
    const v = line.split(",")[idx];
    const num = Number(v);
    if (v !== "" && v !== undefined && Number.isFinite(num)) out.push(num);
  }
  return out;
}

function VelChart({ series }: { series: number[] }) {
  if (series.length < 2) return <div className="hint" style={{ marginTop: 0 }}>no motion profile for this run yet</div>;
  const W = 520, H = 130, padL = 34, padB = 18, padT = 10;
  const max = Math.max(1, ...series.map(Math.abs));
  const step = (W - padL) / (series.length - 1);
  const y = (v: number) => padT + (1 - Math.abs(v) / max) * (H - padT - padB);
  const pts = series.map((v, i) => `${padL + i * step},${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="recoater velocity profile">
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke="var(--line)" />
      <line x1={padL} y1={H - padB} x2={W} y2={H - padB} stroke="var(--line)" />
      <text x={padL - 6} y={padT + 6} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">{Math.round(max)}</text>
      <text x={padL - 6} y={H - padB} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">0</text>
      <polyline points={pts} fill="none" stroke="var(--trace-rc)" strokeWidth="2" />
      <text x={(W + padL) / 2} y={H - 4} fontSize="9" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)">recoater speed (mm/s) over the run</text>
    </svg>
  );
}

export function RunsView({ status, gates, call, base }: { status: StatusPayload | null; gates: Gates; call: Call; base: string }) {
  const [runs, setRuns] = useState<Array<{ run: string; complete: boolean; size_bytes: number }>>([]);
  const [sel, setSel] = useState<string>("");
  const [caps, setCaps] = useState<Capture[]>([]);
  const [vel, setVel] = useState<number[]>([]);
  const rec = status?.recording;

  useEffect(() => {
    api.recordings().then((r) => {
      setRuns(r.runs);
      setSel((cur) => cur || (r.runs.length ? r.runs[r.runs.length - 1].run : ""));
    }).catch(() => undefined);
  }, [status?.recording.active, gates.reachable]);

  useEffect(() => {
    if (!sel) { setCaps([]); setVel([]); return; }
    let live = true;
    api.visionCaptures(sel).then((rc) => { if (live) setCaps(parseCaptures(rc)); }).catch(() => { if (live) setCaps([]); });
    fetch(`${base}/api/recordings/${encodeURIComponent(sel)}/motion_profiles.csv`)
      .then((r) => (r.ok ? r.text() : "")).then((txt) => { if (live) setVel(parseVel(txt, 4)); }).catch(() => { if (live) setVel([]); });
    return () => { live = false; };
  }, [sel, base]);

  const selRun = runs.find((r) => r.run === sel) ?? null;
  const layers = useMemo(() => [...new Set(caps.map((c) => c.layer))].sort((a, b) => a - b), [caps]);
  const label = (run: string) => `${run.slice(0, 8)} ${run.slice(9, 11)}:${run.slice(11, 13)}`;

  return (
    <div className="view fixed-page runs-view">
      <div className="row" style={{ marginBottom: 4 }}>
        {rec?.active
          ? <button className="small" onClick={() => call("stop recording", api.recordingStop)}>■ stop recording {rec.run}</button>
          : <button className="small" disabled={!gates.connected} onClick={() => call("record", () => api.recordingStart({ name: "manual", notes: "" }))}>● record now</button>}
        <span className="hint">Every print is recorded automatically — stills, telemetry, motion profiles.</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "262px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <div className="card" style={{ padding: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {[...runs].reverse().map((r) => (
              <button key={r.run} className={`runitem${r.run === sel ? " on" : ""}`} onClick={() => setSel(r.run)}>
                <span className="rn">{r.run.slice(16) || r.run}</span>
                <span className="rd">{label(r.run)} · {fmtSize(r.size_bytes)}{r.complete ? "" : " · INCOMPLETE"}</span>
              </button>
            ))}
            {runs.length === 0 && <div className="hint">no runs yet</div>}
          </div>
        </div>

        <div className="grid-gap">
          {selRun ? (
            <>
              <div className="card">
                <h3>{selRun.run.slice(16) || selRun.run} · {label(selRun.run)}
                  <a className="cta primary sm" href={`${base}/api/recordings/${encodeURIComponent(selRun.run)}/archive.zip`} target="_blank" rel="noreferrer" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>⬇ Download run (.zip)</a>
                </h3>
                <div className="chips" style={{ marginTop: 0 }}>
                  <span className="chip">{selRun.complete ? "complete" : "incomplete"}</span>
                  <span className="chip">{fmtSize(selRun.size_bytes)}</span>
                  <span className="chip">{layers.length} layers captured</span>
                  <span className="chip">{caps.length} stills</span>
                </div>
                <div className="hint" style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                  {selRun.run}.zip → telemetry.csv · motion_profiles.csv · events.json · manifest.json · layers.csv · vision/ (stills + sidecars)
                </div>
              </div>

              <div className="card">
                <h3>science-cam stills<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>layer × stage</span></h3>
                {caps.length === 0 ? <div className="hint" style={{ marginTop: 0 }}>no science-cam captures for this run</div> : (
                  <div className="cam-grid">
                    {caps.slice(0, 24).map((c) => (
                      <div key={`${c.layer}-${c.stage}`} className="cam-still">
                        <header>L{c.layer} · {STAGE_LABEL[c.stage] ?? c.stage}</header>
                        <img className="cam-panel-img" src={`${base}${c.url}`} alt={`layer ${c.layer} ${c.stage}`} onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="card">
                <h3>motion profile — recoater (axis 4)</h3>
                <VelChart series={vel} />
              </div>
            </>
          ) : <div className="card"><div className="hint" style={{ marginTop: 0 }}>select a run to see its stills, motion profile, and download.</div></div>}

          <div className="card">
            <h3>event log</h3>
            <EventLog events={status?.events ?? []} title="" />
          </div>
        </div>
      </div>
    </div>
  );
}
