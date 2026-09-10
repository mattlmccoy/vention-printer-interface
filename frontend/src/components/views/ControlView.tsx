import { useState } from "react";
import { api } from "../../lib/api.ts";
import { JOG_STEPS } from "../../lib/console.ts";
import { fmtAccel, fmtSecs, fmtSpeed, gantryJogLabels, tri, type Gates } from "../../lib/format.ts";
import { AXIS_NAMES, GANTRY_HOME_SIDE, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { ModuleGrid, type Module } from "../Modules.tsx";
import { PrimingPanel } from "../PrimingPanel.tsx";
import type { Call } from "./types.ts";

const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

/** Module-level speed + accel, sitting directly under the step selector. Sets every axis in the
 *  module at once (both gantries, or both pistons); the placeholder shows the shared current value. */
function Tuning({ axes, status, ok, call }: { axes: AxisNo[]; status: StatusPayload | null; ok: boolean; call: Call }) {
  const lim = status?.controller.limits;
  const am = status?.axis_motion;
  const [speed, setSpeed] = useState("");
  const [accel, setAccel] = useState("");
  const shared = (pick: (m: { max_speed: number | null; max_accel: number | null }) => number | null): string => {
    const vals = axes.map((a) => { const m = am ? am[String(a)] : undefined; return m ? pick(m) : null; });
    return vals.every((v) => v === vals[0]) && vals[0] != null ? String(vals[0]) : "";
  };
  const capS = lim ? Math.max(...axes.map((a) => lim.max_speed[String(a)] ?? 0)) : undefined;
  const capA = lim ? Math.max(...axes.map((a) => lim.max_accel[String(a)] ?? 0)) : undefined;
  const apply = (body: Record<string, number>, label: string, clear: () => void) =>
    call(label, () => Promise.all(axes.map((a) => api.setAxisMotion(a, body)))).then(clear);
  return (
    <div className="tune" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
      <span className="tlbl">speed</span>
      <input type="number" style={{ width: 70 }} value={speed} placeholder={shared((m) => m.max_speed)} onChange={(e) => setSpeed(e.target.value)} disabled={!ok} />
      <button className="small" disabled={!ok || speed === ""} onClick={() => apply({ max_speed: Number(speed) }, "set speed", () => setSpeed(""))}>set</button>
      <span className="cap">≤ {fmtSpeed(capS)}</span>
      <span className="tlbl" style={{ marginLeft: 10 }}>accel</span>
      <input type="number" style={{ width: 70 }} value={accel} placeholder={shared((m) => m.max_accel)} onChange={(e) => setAccel(e.target.value)} disabled={!ok} />
      <button className="small" disabled={!ok || accel === ""} onClick={() => apply({ max_accel: Number(accel) }, "set accel", () => setAccel(""))}>set</button>
      <span className="cap">≤ {fmtAccel(capA)}</span>
    </div>
  );
}

function Axis({ a, status, ok, call, step }: { a: AxisNo; status: StatusPayload | null; ok: boolean; call: Call; step: number }) {
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(a)];
  const moving = t ? t.motion_complete[String(a)] === false : false;
  const piston = a === 1 || a === 2;
  const [target, setTarget] = useState("");
  const jog = piston ? { toHome: "▲ UP", away: "▼ DOWN" } : gantryJogLabels(GANTRY_HOME_SIDE[a as 3 | 4]);
  const rel = (sign: 1 | -1) => call(`jog ${AXIS_NAMES[a]}`, () => api.move(a, "rel", sign * step));
  const abs = (mm: number) => call(`move ${AXIS_NAMES[a]}`, () => api.move(a, "abs", mm));
  return (
    <div className="axis" style={{ borderTop: "none", paddingTop: 6 }}>
      <span className="nm"><i className={SW[a]} />{AXIS_NAMES[a]}</span>
      <span className="pos">{typeof pos === "number" ? pos.toFixed(1) : "—"} <small>mm{moving ? " · moving" : ""}</small></span>
      <div className="jog">
        <button disabled={!ok} onClick={() => rel(-1)}>{jog.toHome}</button>
        <button disabled={!ok} onClick={() => rel(1)}>{jog.away}</button>
        <button className="home" disabled={!ok} title={piston ? "home this piston — EJECTS POWDER (drives it fully up/flush)" : "home this axis"} onClick={() => { if (!piston || window.confirm(`Home the ${AXIS_NAMES[a]}? This drives it fully up (0 mm) = flush with the substrate and EJECTS any powder in the cylinder. Continue?`)) call(`home ${AXIS_NAMES[a]}`, () => api.home([a])); }}>⌂</button>
      </div>
      <div className="goto" style={{ gridColumn: "1 / -1", display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
        <input type="number" style={{ width: 90 }} value={target} placeholder="go to mm" onChange={(e) => setTarget(e.target.value)} disabled={!ok} />
        <button className="small" disabled={!ok || target === ""} onClick={() => abs(Number(target))}>go</button>
      </div>
    </div>
  );
}

export function ControlView({ status, gates, call, gantryStep, pistonStep, setGantryStep, setPistonStep, order, sizes, onOrder, onResize }: { status: StatusPayload | null; gates: Gates; call: Call; gantryStep: number; pistonStep: number; setGantryStep: (s: number) => void; setPistonStep: (s: number) => void; order?: string[]; sizes?: Record<string, import("../../lib/console.ts").ModuleSize>; onOrder: (ids: string[]) => void; onResize: (id: string, size: import("../../lib/console.ts").ModuleSize) => void }) {
  const c = status?.controller;
  const t = c?.telemetry;
  const ok = gates.controllable && !gates.printActive;
  const lock = !gates.controllable ? (gates.connected ? "read-only · take control from the connection pill" : "connect a controller to jog") : gates.printActive ? "a print is running · manual motion is locked" : null;
  const stepper = (v: number, set: (s: number) => void) => <div className="stepper" style={{ marginBottom: 8 }}>step {JOG_STEPS.map((s) => <button key={s} className={s === v ? "on" : ""} onClick={() => set(s)}>{s} mm</button>)}</div>;
  const modules: Module[] = [
    { id: "gantries", title: "gantries", size: "m", node: <>{stepper(gantryStep, setGantryStep)}<Tuning axes={[3, 4]} status={status} ok={ok} call={call} /><Axis a={3} status={status} ok={ok} call={call} step={gantryStep} /><Axis a={4} status={status} ok={ok} call={call} step={gantryStep} />{lock && <div className="lock">{lock}</div>}</> },
    { id: "pistons", title: "pistons", size: "m", node: <>{stepper(pistonStep, setPistonStep)}<Tuning axes={[1, 2]} status={status} ok={ok} call={call} /><Axis a={1} status={status} ok={ok} call={call} step={pistonStep} /><Axis a={2} status={status} ok={ok} call={call} step={pistonStep} /></> },
    { id: "motion", title: "motion", size: "s", node: (
      <>
        <div className="actions" style={{ marginTop: 0 }}><button className="cta" disabled={!ok} title="homes the printhead + recoater gantries only (never the pistons — that would eject powder)" onClick={() => call("home gantries", () => api.home([3, 4]))}>HOME GANTRIES</button><button className="cta danger" disabled={!gates.connected} onClick={() => call("stop", api.stop)}>STOP</button></div>
        <div className="actions tight">
          <button className="cta" disabled={!ok} onClick={() => { if (window.confirm("For an EMPTY cart only. Homes the gantries, then drives both pistons to the bottom of travel so you can load the cart. Do NOT run with powder loaded. Continue?")) call("load cart", () => api.macro("load_cart")); }}>LOAD CART (empty)</button>
          <button className="cta" disabled={!ok} onClick={() => call("clear bed", () => api.macro("clear_bed"))}>CLEAR BED</button>
        </div>
        <div className="hint" style={{ marginTop: 10 }}>Load cart lowers both pistons and homes the gantries; then jog the pistons into place.</div>
      </>
    ) },
    { id: "priming", title: "priming (powder prep)", size: "m", node: <PrimingPanel gates={gates} call={call} /> },
    { id: "heater", title: "heater", size: "s", node: (
      <>
        <div className="kv" style={{ marginTop: 0 }}><span>relay</span><span className={c?.heater.on ? "bad" : ""}>{tri(c?.heater.on, `ON ${fmtSecs(c?.heater.on_s)}`, "off", "not observed")}</span><span>watchdog</span><span>{fmtSecs(c?.heater.max_on_s)}</span><span>io module</span><span className="warnv">{Array.isArray(status?.device.heater_io) ? (status!.device.heater_io as number[]).join(" / ") : "—"} unverified</span></div>
        <div className="actions tight">
          <button className="cta danger" disabled={!ok} title={`Turns the IR heater ON; it switches off after ${fmtSecs(c?.heater.max_on_s)} or on any fault.`} onClick={() => call("heater on", api.heaterOn)}>HEATER ON</button>
          <button className="cta" disabled={!gates.connected} onClick={() => call("heater off", api.heaterOff)}>HEATER OFF</button>
        </div>
      </>
    ) },
    { id: "io", title: "controller", size: "s", node: (
      <div className="chips" style={{ marginTop: 0 }}>
        <span className={`chip ${t?.estop_triggered ? "bad" : t?.estop_triggered === null ? "warn" : ""}`}>e-stop {tri(t?.estop_triggered, "asserted", "clear")}</span>
        <span className={`chip ${t?.drives_ready === false ? "bad" : t?.drives_ready === null ? "warn" : ""}`}>drives {tri(t?.drives_ready, "ready", "not ready")}</span>
        <span className={`chip ${t && !t.health_ok ? "bad" : ""}`}>health {t ? (t.health_ok ? "ok" : "bad") : "?"}</span>
        <span className={`chip ${c?.read_error ? "bad" : ""}`}>read {c?.read_error ? "error" : "ok"}</span>
        <span className="chip">{String((status?.device as { version?: string })?.version ?? "")} · {c?.backend ?? "none"}</span>
      </div>
    ) },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} sizes={sizes} onOrder={onOrder} onResize={onResize} /></div>;
}
