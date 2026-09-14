import { useEffect, useState } from "react";
import { api, type RunMeta } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { parseCaptures, type Capture } from "../../lib/vision.ts";
import { EventLog } from "../EventLog.tsx";
import type { Call } from "./types.ts";

const STAGE_LABEL: Record<string, string> = { pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat" };
const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} kB`);
const fmtDur = (s?: number | null) => {
  if (s == null || !Number.isFinite(s)) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return h ? `${h} h ${String(m).padStart(2, "0")} m` : m ? `${m} m ${String(sec).padStart(2, "0")} s` : `${sec} s`;
};

/** motion_profiles.csv → per-axis velocity series for the chart. Columns:
 *  host_timestamp_ns, pos_1..4, vel_1..4, accel_1..4. Blank cells are skipped. */
function parseVel(csv: string, axis: number): number[] {
  const lines = csv.trim().split("\n");
  if (lines.length < 2) return [];
  const idx = lines[0].split(",").indexOf(`vel_${axis}`);
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
  if (series.length < 2) return <div className="chart-empty">no motion profile for this run yet</div>;
  const W = 520, H = 150, padL = 34, padB = 20, padT = 10;
  const max = Math.max(1, ...series.map(Math.abs));
  const step = (W - padL) / (series.length - 1);
  const y = (v: number) => padT + (1 - Math.abs(v) / max) * (H - padT - padB);
  const pts = series.map((v, i) => `${padL + i * step},${y(v)}`).join(" ");
  return (
    <svg className="mchart" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img" aria-label="recoater velocity profile">
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} />
      <line x1={padL} y1={H - padB} x2={W} y2={H - padB} />
      <text x={padL - 6} y={padT + 6} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">{Math.round(max)}</text>
      <text x={padL - 6} y={H - padB} fontSize="9" fill="var(--faint)" textAnchor="end" fontFamily="var(--font-mono)">0</text>
      <polyline points={pts} fill="none" stroke="var(--trace-rc)" strokeWidth="2" />
      <text x={(W + padL) / 2} y={H - 4} fontSize="9" fill="var(--faint)" textAnchor="middle" fontFamily="var(--font-mono)">recoater speed (mm/s) over the run</text>
    </svg>
  );
}

export function RunsView({ status, gates, call, base }: { status: StatusPayload | null; gates: Gates; call: Call; base: string }) {
  const [runs, setRuns] = useState<RunMeta[]>([]);
  const [sel, setSel] = useState<string>("");
  const [caps, setCaps] = useState<Capture[]>([]);
  const [vel, setVel] = useState<number[]>([]);
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
    if (!sel) { setCaps([]); setVel([]); return; }
    let live = true;
    api.visionCaptures(sel).then((rc) => { if (live) setCaps(parseCaptures(rc)); }).catch(() => { if (live) setCaps([]); });
    fetch(`${base}/api/recordings/${encodeURIComponent(sel)}/motion_profiles.csv`)
      .then((r) => (r.ok ? r.text() : "")).then((txt) => { if (live) setVel(parseVel(txt, 4)); }).catch(() => { if (live) setVel([]); });
    return () => { live = false; };
  }, [sel, base]);

  const label = (run: string) => `${run.slice(0, 8)} ${run.slice(9, 11)}:${run.slice(11, 13)}`;
  const dispName = (r: RunMeta) => r.name || r.run.slice(16) || r.run;
  const saveMeta = () => call("save run name/notes", () => api.recordingSetMeta(sel, { name, notes }).then(() => { setDirty(false); return refresh(); }));

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
                  <a className="cta primary sm" href={`${base}/api/recordings/${encodeURIComponent(selRun.run)}/archive.zip`} target="_blank" rel="noreferrer" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>⬇ Download run (.zip)</a>
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
                <h3>motion profile — recoater (axis 4)</h3>
                <VelChart series={vel} />
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
