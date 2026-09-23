import { cleanNum } from "./format.ts";
import { AXIS_NAMES, type AxisNo, type EventItem } from "./telemetry.ts";

function axisName(a: unknown): string {
  return typeof a === "number" && (a as AxisNo) in AXIS_NAMES ? AXIS_NAMES[a as AxisNo] : `axis ${a}`;
}
function axisList(v: unknown): string {
  if (v === "all") return "all axes";
  if (Array.isArray(v)) return v.map(axisName).join(", ");
  return axisName(v);
}
function rawSummary(d: Record<string, unknown>): string {
  return Object.entries(d).filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => (typeof v === "object" ? `${k}=${JSON.stringify(v)}` : `${k}=${v}`)).join(" · ");
}

/** Plain-language one-liner for an event; falls back to key=value for labels we don't special-case. */
export function describeEvent(e: EventItem): string {
  const d = e.data as Record<string, unknown>;
  switch (e.label) {
    case "home": return `Homed ${axisList(d.axes)}`;
    case "move": return `Moved ${axisName(d.axis)} ${typeof d.applied_mm === "number" ? cleanNum(d.applied_mm, 3) : d.applied_mm} mm`;
    case "stop": return "Stopped all motion";
    case "heater_on": return "Heater on";
    case "heater_off": return "Heater off";
    case "armed": return "Took control (armed)";
    case "disarmed": return "Released control (read-only)";
    case "connected": return `Connected to ${d.backend === "simulated" ? "simulator" : "MachineMotion"}${d.ip ? ` (${d.ip})` : ""}`;
    case "disconnected": return "Disconnected";
    case "estop": return "Operator E-STOP — motion halted";
    case "estop_released": return "E-STOP released";
    case "fault_cleared": return "Fault cleared";
    case "fault": return `FAULT — ${Array.isArray(d.reasons) ? d.reasons.join("; ") : rawSummary(d)}`;
    default: return `${e.label}${Object.keys(d).length ? ` · ${rawSummary(d)}` : ""}`;
  }
}
