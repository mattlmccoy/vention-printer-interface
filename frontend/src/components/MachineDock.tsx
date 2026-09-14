import { api } from "../lib/api.ts";
import { fmtSecs, type Gates } from "../lib/format.ts";
import { type AxisNo, type StatusPayload } from "../lib/telemetry.ts";
import type { View } from "../lib/console.ts";
import { DockMachine } from "./DockMachine.tsx";
import { OverviewCameraPanel } from "./OverviewCameraPanel.tsx";
import type { Call } from "./views/types.ts";

const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };
const AXCLS: Record<AxisNo, string> = { 1: "ax-build", 2: "ax-feed", 3: "ax-ph", 4: "ax-rc" };
// Chip order matches the mockup: gantries first (printhead, recoater), then pistons (build, feed).
const CHIP_ORDER: AxisNo[] = [3, 4, 1, 2];

/** The persistent right-side machine monitor — mockup layout: a LARGE, clear machine schematic on
 *  top (the centrepiece), then compact 2x2 axis chips, an on-demand overview PIP, heater/health,
 *  and pause/abort while a print runs. Kept clean and uncluttered. */
export function MachineDock({ status, base, gates, call, view }: {
  status: StatusPayload | null;
  base: string;
  gates: Gates;
  call: Call;
  view: View;
}) {
  const c = status?.controller;
  const t = c?.telemetry ?? null;
  const r = status?.print;
  const active = !!r && (r.state === "running" || r.state === "paused");
  const heater = c?.heater.on ?? null;
  const health = t ? (t.health_ok ? "ok" : "bad") : "—";
  const pct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;

  return (
    <>
      <div className="dock-head">
        <span className="dock-title">machine monitor</span>
        <span className={`dot ${t ? "live" : "warn"}`} />
      </div>
      <div className="dock-body">
        <div className="dock-machine"><DockMachine status={status} /></div>

        {active && (
          <div className="dock-print">
            <div className="dp-row"><span className="dp-state">{r.state === "paused" ? "PAUSED" : r.dry_run ? "DRY RUN" : "PRINTING"}</span><span className="dp-layer num">layer {r.layer}/{r.n_layers}</span></div>
            <div className="bar" style={{ margin: "8px 0 4px" }}><i style={{ width: `${pct}%` }} /></div>
            <div className="bar-lbl">{pct}% · {fmtSecs(r.elapsed_s)}</div>
          </div>
        )}

        <div className="dock-axes">
          {CHIP_ORDER.map((a) => {
            const unref = t?.referenced?.[String(a)] === false;
            const p = t?.positions[String(a)];
            return (
              <div className={`dock-chip ${AXCLS[a]}`} key={a}>
                <span className="k">{SHORT[a]}</span>
                <span className={`v${unref ? " unref" : ""}`}>{unref ? "—" : typeof p === "number" ? p.toFixed(1) : "—"}<small> mm</small></span>
              </div>
            );
          })}
        </div>

        <OverviewCameraPanel base={base} view={view} />

        <div className="dock-mini">
          <div className={`dm${heater ? " hot" : ""}`}><span className="k">heater</span><span className="v">{heater === null ? "—" : heater ? `on ${fmtSecs(c?.heater.on_s)}` : "off"}</span></div>
          <div className={`dm${health === "bad" ? " bad" : ""}`}><span className="k">health</span><span className="v">{health}</span></div>
        </div>

        {active && (
          <div className="dock-actions">
            {r.state === "running" && <button className="cta danger" disabled={!gates.connected} onClick={() => call("pause", api.printPause)}>PAUSE</button>}
            {r.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call("resume", api.printResume)}>RESUME</button>}
            <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
          </div>
        )}
      </div>
    </>
  );
}
