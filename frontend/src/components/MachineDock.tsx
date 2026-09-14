import { api } from "../lib/api.ts";
import { fmtSecs, tri, type Gates } from "../lib/format.ts";
import { AXES, TRAVEL_MM, type AxisNo, type StatusPayload } from "../lib/telemetry.ts";
import type { View } from "../lib/console.ts";
import { Elevation } from "./Elevation.tsx";
import { OverviewCameraPanel } from "./OverviewCameraPanel.tsx";
import type { Call } from "./views/types.ts";

const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

/** The persistent right-side machine monitor: live schematic, per-axis position + travel bar,
 *  overview PIP, controller status chips, heater/health, and live print progress with pause/abort.
 *  Dense and always visible so the operator can watch the machine from any view. */
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
  const lim = c?.limits;
  const active = !!r && (r.state === "running" || r.state === "paused");
  const heater = c?.heater.on ?? null;
  const pct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;

  const axisRow = (a: AxisNo) => {
    const unref = t?.referenced?.[String(a)] === false;
    const p = t?.positions[String(a)];
    const moving = t ? t.motion_complete[String(a)] === false : false;
    const tmin = lim?.travel_min[String(a)] ?? 0;
    const tmax = lim?.travel_max[String(a)] ?? TRAVEL_MM[a] ?? 100;
    const frac = typeof p === "number" && tmax > tmin ? Math.max(0, Math.min(1, (p - tmin) / (tmax - tmin))) : 0;
    return (
      <div className="dock-axis" key={a}>
        <div className="r1">
          <span className="k"><i className={SW[a]} />{SHORT[a]}</span>
          <span className={`v${unref ? " unref" : ""}`}>{unref ? "not homed" : typeof p === "number" ? p.toFixed(1) : "—"}{!unref && <small>mm</small>}{moving ? <small> · moving</small> : null}</span>
        </div>
        <div className="trav"><i className={`${SW[a]}${moving ? " mv" : ""}`} style={{ width: `${frac * 100}%` }} /></div>
      </div>
    );
  };

  return (
    <>
      <div className="dock-head">
        <span className="dock-title">machine monitor</span>
        <span className={`dot ${t ? "live" : "warn"}`} />
      </div>
      <div className="dock-body">
        <div className="dock-machine"><Elevation status={status} partZeroMm={r?.part_zero_mm ?? null} /></div>

        {active && (
          <div className="dock-print">
            <div className="dp-row"><span className="dp-state">{r.state === "paused" ? "PAUSED" : r.dry_run ? "DRY RUN" : "PRINTING"}</span><span className="dp-layer num">layer {r.layer}/{r.n_layers}</span></div>
            <div className="bar" style={{ margin: "8px 0 4px" }}><i style={{ width: `${pct}%` }} /></div>
            <div className="bar-lbl">{pct}% · {fmtSecs(r.elapsed_s)} elapsed</div>
            <div className="dock-actions">
              {r.state === "running" && <button className="cta danger" disabled={!gates.connected} onClick={() => call("pause", api.printPause)}>PAUSE</button>}
              {r.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call("resume", api.printResume)}>RESUME</button>}
              <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
            </div>
          </div>
        )}

        <div className="dock-axes">{AXES.map(axisRow)}</div>

        <OverviewCameraPanel base={base} view={view} />

        <div className="dock-status">
          <span className={`chip ${heater ? "bad" : ""}`}>heater {heater === null ? "—" : heater ? `on ${fmtSecs(c?.heater.on_s)}` : "off"}</span>
          <span className={`chip ${t && !t.health_ok ? "bad" : ""}`}>health {t ? (t.health_ok ? "ok" : "bad") : "?"}</span>
          <span className={`chip ${t?.estop_triggered ? "bad" : ""}`}>e-stop {tri(t?.estop_triggered, "asserted", "clear")}</span>
          <span className={`chip ${t?.drives_ready === false ? "bad" : ""}`}>drives {tri(t?.drives_ready, "ready", "off")}</span>
        </div>
      </div>
    </>
  );
}
