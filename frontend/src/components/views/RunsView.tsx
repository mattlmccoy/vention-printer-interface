import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { EventLog } from "../EventLog.tsx";
import { ModuleGrid, type Module } from "../Modules.tsx";
import type { Call } from "./types.ts";

export function RunsView({ status, gates, call, order, sizes, onOrder, onResize }: { status: StatusPayload | null; gates: Gates; call: Call; order?: string[]; sizes?: Record<string, import("../../lib/console.ts").ModuleSize>; onOrder: (ids: string[]) => void; onResize: (id: string, size: import("../../lib/console.ts").ModuleSize) => void }) {
  const [runs, setRuns] = useState<Array<{ run: string; complete: boolean; size_bytes: number }>>([]);
  useEffect(() => { api.recordings().then((r) => setRuns(r.runs)).catch(() => undefined); }, [status?.recording.active, gates.reachable]);
  const rec = status?.recording;
  const modules: Module[] = [
    { id: "runs", title: "runs", size: "l", node: (
      <>
        <div className="row" style={{ marginBottom: 14 }}>
          {rec?.active ? <button className="small" onClick={() => call("stop recording", api.recordingStop)}>■ stop recording {rec.run}</button>
            : <button className="small" disabled={!gates.connected} onClick={() => call("record", () => api.recordingStart({ name: "manual", notes: "" }))}>● record now</button>}
          <span className="hint">every print is recorded automatically</span>
        </div>
        <div className="log">
          <table><tbody>{[...runs].reverse().map((r) => (
            <tr key={r.run} className={r.complete ? "" : "warn"}><td>{r.run.slice(0, 8)} {r.run.slice(9, 11)}:{r.run.slice(11, 13)}</td><td className="k">{r.run.slice(16)}</td><td className="d">{r.complete ? "complete" : "INCOMPLETE"} · <a href={`/api/recordings/${r.run}/telemetry.csv`} target="_blank" rel="noreferrer">telemetry</a> · <a href={`/api/recordings/${r.run}/layers.csv`} target="_blank" rel="noreferrer">layers</a> · <a href={`/api/recordings/${r.run}/events.json`} target="_blank" rel="noreferrer">events</a></td></tr>
          ))}</tbody></table>
          {runs.length === 0 && <div className="hint">no runs yet</div>}
        </div>
      </>
    ) },
    { id: "events", title: "events", size: "l", node: <EventLog events={status?.events ?? []} title="" /> },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} sizes={sizes} onOrder={onOrder} onResize={onResize} /></div>;
}
