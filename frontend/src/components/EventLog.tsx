import type { EventItem } from "../lib/telemetry.ts";

function fmtTime(ns: number): string {
  const d = new Date(ns / 1e6);
  return d.toLocaleTimeString([], { hour12: false });
}
function summary(e: EventItem): string {
  const d = e.data;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(d)) {
    if (v === null || v === undefined || v === "") continue;
    parts.push(typeof v === "object" ? `${k}=${JSON.stringify(v)}` : `${k}=${String(v)}`);
  }
  return parts.join(" · ");
}
export function EventLog({ events, title = "Event log" }: { events: EventItem[]; title?: string }) {
  const rows = [...events].reverse();
  return (
    <div className="log">
      <div className="card-h">{title}<span className="muted">{rows.length} recent</span></div>
      {rows.length === 0 ? <div className="hint">no events yet</div> : (
        <table><tbody>{rows.map((e, i) => (
          <tr key={`${e.host_timestamp_ns}-${i}`} className={/fault|estop|failed|warning/.test(e.label) ? "warn" : ""}><td>{fmtTime(e.host_timestamp_ns)}</td><td className="k">{e.label}</td><td className="d">{summary(e)}</td></tr>
        ))}</tbody></table>
      )}
    </div>
  );
}
