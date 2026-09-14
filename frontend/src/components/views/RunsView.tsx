import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { EventLog } from "../EventLog.tsx";
import type { Call } from "./types.ts";

export function RunsView({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call }) {
  const [runs, setRuns] = useState<Array<{ run: string; complete: boolean; size_bytes: number }>>([]);
  useEffect(() => { api.recordings().then((r) => setRuns(r.runs)).catch(() => undefined); }, [status?.recording.active, gates.reachable]);
  const rec = status?.recording;
  return (
    <div className="view fixed-page runs-view">
      <div className="card">
        <h3>runs
          {rec?.active
            ? <button className="small" onClick={() => call("stop recording", api.recordingStop)}>■ stop recording {rec.run}</button>
            : <button className="small" disabled={!gates.connected} onClick={() => call("record", () => api.recordingStart({ name: "manual", notes: "" }))}>● record now</button>}
        </h3>
        <div className="hint" style={{ marginTop: 0, marginBottom: 12 }}>Every print is recorded automatically — telemetry, layers, and events per run.</div>
        <div className="log run-log">
          <div className="tbl-scroll">
            <table><tbody>{[...runs].reverse().map((r) => (
              <tr key={r.run} className={r.complete ? "" : "warn"}><td>{r.run.slice(0, 8)} {r.run.slice(9, 11)}:{r.run.slice(11, 13)}</td><td className="k">{r.run.slice(16)}</td><td className="d">{r.complete ? "complete" : "INCOMPLETE"} · <a href={`/api/recordings/${r.run}/telemetry.csv`} target="_blank" rel="noreferrer">telemetry</a> · <a href={`/api/recordings/${r.run}/layers.csv`} target="_blank" rel="noreferrer">layers</a> · <a href={`/api/recordings/${r.run}/events.json`} target="_blank" rel="noreferrer">events</a></td></tr>
            ))}</tbody></table>
          </div>
          {runs.length === 0 && <div className="hint">no runs yet</div>}
        </div>
      </div>
      <div className="card">
        <h3>event log</h3>
        <EventLog events={status?.events ?? []} title="" />
      </div>
    </div>
  );
}
