import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import type { Call } from "./types.ts";

export function RunsView({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call }) {
  const [runs, setRuns] = useState<Array<{ run: string; complete: boolean; size_bytes: number }>>([]);
  const [name, setName] = useState("manual");
  useEffect(() => { api.recordings().then((r) => setRuns(r.runs)).catch(() => undefined); }, [status?.recording.active, gates.reachable]);
  const rec = status?.recording;
  return (
    <section className="view runs">
      <div>
        <div className="card-h">Recording<span className="muted">a run opens automatically when a recipe starts</span></div>
        <div className="row" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {rec?.active ? <button className="small" onClick={() => call("stop recording", api.recordingStop)}>■ stop {rec.run}</button>
            : <><input type="text" value={name} onChange={(e) => setName(e.target.value)} /><button className="small" disabled={!gates.connected} onClick={() => call("record", () => api.recordingStart({ name, notes: "" }))}>● record now</button></>}
        </div>
        <div className="log" style={{ marginTop: 16 }}>
          <div className="card-h">Runs<span className="muted">{runs.length}</span></div>
          <table><tbody>{[...runs].reverse().map((r) => (
            <tr key={r.run} className={r.complete ? "" : "warn"}><td>{r.run.slice(0, 15)}</td><td className="k">{r.run.slice(16)}</td><td className="d">{r.complete ? "complete" : "INCOMPLETE (no manifest)"} · {(r.size_bytes / 1024).toFixed(0)} KB · <a href={`/api/recordings/${r.run}/telemetry.csv`} target="_blank" rel="noreferrer">telemetry</a> · <a href={`/api/recordings/${r.run}/layers.csv`} target="_blank" rel="noreferrer">layers</a> · <a href={`/api/recordings/${r.run}/events.json`} target="_blank" rel="noreferrer">events</a></td></tr>
          ))}</tbody></table>
          {runs.length === 0 && <div className="hint">no runs recorded yet</div>}
        </div>
      </div>
    </section>
  );
}
