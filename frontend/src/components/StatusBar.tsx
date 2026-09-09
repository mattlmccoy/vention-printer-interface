import { fmtSecs, tri } from "../lib/format.ts";

export interface StatusBarProps {
  state: string; backend: string; pollHz: number | null; reachable: boolean;
  estop: boolean | null; drivesReady: boolean | null; heaterOn: boolean | null; heaterOnS: number; heaterMaxS: number;
  recActive: boolean; recRun: string | null; printState: string; version: string | null;
}

/** Bottom status bar (family rule): never shows green; faults red, unknowns amber. */
export function StatusBar(p: StatusBarProps) {
  const unknown = p.estop === null || p.drivesReady === null;
  return (
    <footer className="statusbar">
      <span className={!p.reachable ? "bad" : ""}>operator <b>{p.reachable ? "ok" : "UNREACHABLE"}</b></span>
      <span className={p.state === "fault" ? "bad" : ""}>controller <b>{p.state}</b></span>
      <span className={p.estop ? "bad" : p.estop === null ? "warnv" : ""}>e-stop <b>{tri(p.estop, "ASSERTED", "clear")}</b></span>
      <span className={p.drivesReady === false ? "bad" : p.drivesReady === null ? "warnv" : ""}>drives <b>{tri(p.drivesReady, "ready", "NOT READY")}</b></span>
      <span className={p.heaterOn ? "bad" : p.heaterOn === null ? "warnv" : ""}>heater <b>{tri(p.heaterOn, `ON ${fmtSecs(p.heaterOnS)}`, "off")}</b>{p.heaterOn ? <span className="muted"> / {fmtSecs(p.heaterMaxS)}</span> : null}</span>
      {unknown && p.state !== "disconnected" && <span className="warnv">STATUS UNKNOWN</span>}
      <span className="right">
        {p.printState !== "idle" && <span className={p.printState === "fault" ? "bad" : ""}>print <b>{p.printState}</b></span>}
        {p.recActive && <span title="telemetry, layer times and events are being written to this run folder">logging <b>{p.recRun}</b></span>}
        {p.version && <span className="muted">v{p.version}</span>}
      </span>
    </footer>
  );
}
