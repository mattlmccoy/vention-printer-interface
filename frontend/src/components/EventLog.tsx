import type { EventItem } from "../lib/telemetry.ts";
import { describeEvent } from "../lib/eventlog.ts";

function fmtTime(ns: number): string {
  const d = new Date(ns / 1e6);
  return d.toLocaleTimeString([], { hour12: false });
}
export function EventLog({ events, title = "Event log" }: { events: EventItem[]; title?: string }) {
  const rows = [...events].reverse();
  return (
    <div className="log">
      {title && <div className="h">{title}</div>}
      {rows.length === 0 ? <div className="hint">no events yet</div> : (
        <table><tbody>{rows.map((e, i) => (
          <tr key={`${e.host_timestamp_ns}-${i}`} className={/fault|estop|failed|warning/.test(e.label) ? "warn" : ""}><td>{fmtTime(e.host_timestamp_ns)}</td><td className="k">{e.label}</td><td className="d">{describeEvent(e)}</td></tr>
        ))}</tbody></table>
      )}
    </div>
  );
}
