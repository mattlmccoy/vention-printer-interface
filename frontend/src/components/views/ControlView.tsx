import { useState } from "react";
import { api } from "../../lib/api.ts";
import { JOG_STEPS } from "../../lib/console.ts";
import { fmtAccel, fmtSecs, fmtSpeed, gantryJogLabels, tri, type Gates } from "../../lib/format.ts";
import { AXIS_NAMES, GANTRY_HOME_SIDE, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import type { Call } from "./types.ts";

const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

function Axis({ a, status, ok, call, step }: { a: AxisNo; status: StatusPayload | null; ok: boolean; call: Call; step: number }) {
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(a)];
  const unref = t?.referenced?.[String(a)] === false;
  const moving = t ? t.motion_complete[String(a)] === false : false;
  const piston = a === 1 || a === 2;
  const lim = status?.controller.limits;
  const am = status?.axis_motion[String(a)];
  const [target, setTarget] = useState("");
  const [speed, setSpeed] = useState("");
  const [accel, setAccel] = useState("");
  const jog = piston ? { toHome: "▲ UP", away: "▼ DOWN" } : gantryJogLabels(GANTRY_HOME_SIDE[a as 3 | 4]);
  const rel = (sign: 1 | -1) => call(`jog ${AXIS_NAMES[a]}`, () => api.move(a, "rel", sign * step));
  const abs = (mm: number) => call(`move ${AXIS_NAMES[a]}`, () => api.move(a, "abs", mm));
  return (
    <div className="axis" style={{ borderTop: "none", paddingTop: 6 }}>
      <span className="nm"><i className={SW[a]} />{AXIS_NAMES[a]}</span>
      <span className="pos">{unref ? <b className="unref">unref</b> : typeof pos === "number" ? pos.toFixed(1) : "—"} <small>mm{moving ? " · moving" : unref ? " · not homed" : ""}</small></span>
      <div className="tune">
        <span className="lbl">spd</span>
        <input className="inp" type="number" value={speed} placeholder={String(am?.max_speed ?? "")} disabled={!ok} onChange={(e) => setSpeed(e.target.value)} />
        <button className="small" disabled={!ok || speed === ""} onClick={() => call("set speed", () => api.setAxisMotion(a, { max_speed: Number(speed) }).then(() => setSpeed("")))}>set</button>
        <span className="cap">≤ {fmtSpeed(lim?.max_speed[String(a)])}</span>
        <span className="lbl">acc</span>
        <input className="inp" type="number" value={accel} placeholder={String(am?.max_accel ?? "")} disabled={!ok} onChange={(e) => setAccel(e.target.value)} />
        <button className="small" disabled={!ok || accel === ""} onClick={() => call("set accel", () => api.setAxisMotion(a, { max_accel: Number(accel) }).then(() => setAccel("")))}>set</button>
        <span className="cap">≤ {fmtAccel(lim?.max_accel[String(a)])}</span>
      </div>
      <div className="jog">
        <button disabled={!ok} onClick={() => rel(-1)}>{jog.toHome}</button>
        <button disabled={!ok} onClick={() => rel(1)}>{jog.away}</button>
        <button className="home" disabled={!ok} title={piston ? "home this piston — EJECTS POWDER (drives it fully up/flush)" : "home this axis"} onClick={() => { if (!piston || window.confirm(`Home the ${AXIS_NAMES[a]}? This drives it fully up (0 mm) = flush with the substrate and EJECTS any powder in the cylinder. Continue?`)) call(`home ${AXIS_NAMES[a]}`, () => api.home([a])); }}>⌂</button>
      </div>
      <div className="goto" style={{ gridColumn: "1 / -1", display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
        <input type="number" style={{ flex: 1, minWidth: 0 }} value={target} placeholder="go to mm" onChange={(e) => setTarget(e.target.value)} disabled={!ok} />
        <button className="small" style={{ flex: "0 0 auto" }} disabled={!ok || target === ""} onClick={() => abs(Number(target))}>go</button>
      </div>
    </div>
  );
}

export function ControlView({ status, gates, call, gantryStep, pistonStep, setGantryStep, setPistonStep }: { status: StatusPayload | null; gates: Gates; call: Call; gantryStep: number; pistonStep: number; setGantryStep: (s: number) => void; setPistonStep: (s: number) => void }) {
  const c = status?.controller;
  const t = c?.telemetry;
  const ok = gates.controllable && !gates.printActive;
  const anyUnref = t?.referenced ? Object.values(t.referenced).some((v) => v === false) : false;
  const lock = !gates.controllable ? (gates.connected ? "read-only · take control from the connection pill" : "connect a controller to jog") : gates.printActive ? "a print is running · manual motion is locked" : null;
  const stepper = (v: number, set: (s: number) => void) => <div className="stepper" style={{ marginBottom: 8 }}>step {JOG_STEPS.map((s) => <button key={s} className={s === v ? "on" : ""} onClick={() => set(s)}>{s} mm</button>)}</div>;
  return (
    <div className="view fixed-page control-view">
      <div className="sec-h">axes</div>
      {/* 2×2 banner layout: gantries on top (printhead left, recoater right), pistons below
          (feed left, build right) — printhead TL, recoater TR, feed BL, build BR. */}
      <div className="axes-2x2">
        <div className="card">
          <h3>gantries</h3>
          {stepper(gantryStep, setGantryStep)}
          <div className="axis-pair">
            <Axis a={3} status={status} ok={ok} call={call} step={gantryStep} />
            <Axis a={4} status={status} ok={ok} call={call} step={gantryStep} />
          </div>
          {lock && <div className="lock">{lock}</div>}
        </div>
        <div className="card">
          <h3>pistons</h3>
          {stepper(pistonStep, setPistonStep)}
          <div className="axis-pair">
            <Axis a={2} status={status} ok={ok} call={call} step={pistonStep} />
            <Axis a={1} status={status} ok={ok} call={call} step={pistonStep} />
          </div>
        </div>
      </div>

      <div className="sec-h">operations</div>
      <div className="cards-3">
        <div className="card">
          <h3>motion</h3>
          <div className="actions" style={{ marginTop: 0 }}>
            <button className="cta" disabled={!ok} onClick={() => { if (window.confirm("Home the printhead gantry?")) call("home printhead", () => api.home([3])); }}>HOME PRINTHEAD</button>
            <button className="cta" disabled={!ok} onClick={() => { if (window.confirm("Home the recoater gantry?")) call("home recoater", () => api.home([4])); }}>HOME RECOATER</button>
          </div>
          <div className="actions" style={{ marginTop: 8 }}>
            <button className="cta danger" disabled={!gates.connected} onClick={() => call("stop", api.stop)}>STOP</button>
            <button className={`cta${anyUnref ? " primary" : ""}`} disabled={!ok} title="Reference every axis at its CURRENT reported position WITHOUT homing — only when the machine kept power and the positions match its own display." onClick={() => { if (window.confirm("Reference ALL axes at their CURRENT positions WITHOUT homing?\n\nOnly do this if the machine KEPT POWER and the positions shown match the machine's own HMI. If power was lost (positions read ~0), home instead.")) call("reference at current", api.referenceCurrent); }}>REFERENCE AT CURRENT{anyUnref ? " ⚠" : ""}</button>
          </div>
          <div className="hint" style={{ marginTop: 10 }}>Home one gantry at a time (pistons ejecting powder). Or, if the machine kept power and the positions are correct, <b>reference at current</b> to trust them without homing.</div>
        </div>
        <div className="card">
          <h3>heater</h3>
          <div className="kv" style={{ marginTop: 0 }}><span>relay</span><span className={c?.heater.on ? "bad" : ""}>{tri(c?.heater.on, `ON ${fmtSecs(c?.heater.on_s)}`, "off", "not observed")}</span><span>watchdog</span><span>{fmtSecs(c?.heater.max_on_s)}</span><span>io module</span><span className="warnv">{Array.isArray(status?.device.heater_io) ? (status!.device.heater_io as number[]).join(" / ") : "—"} unverified</span></div>
          <div className="actions tight">
            <button className="cta danger" disabled={!ok} title={`Turns the IR heater ON; it switches off after ${fmtSecs(c?.heater.max_on_s)} or on any fault.`} onClick={() => call("heater on", api.heaterOn)}>HEATER ON</button>
            <button className="cta" disabled={!gates.connected} onClick={() => call("heater off", api.heaterOff)}>HEATER OFF</button>
          </div>
        </div>
        <div className="card">
          <h3>controller</h3>
          <div className="chips" style={{ marginTop: 0 }}>
            <span className={`chip ${t?.estop_triggered ? "bad" : t?.estop_triggered === null ? "warn" : ""}`}>e-stop {tri(t?.estop_triggered, "asserted", "clear")}</span>
            <span className={`chip ${t?.drives_ready === false ? "bad" : t?.drives_ready === null ? "warn" : ""}`}>drives {tri(t?.drives_ready, "ready", "not ready")}</span>
            <span className={`chip ${t && !t.health_ok ? "bad" : ""}`}>health {t ? (t.health_ok ? "ok" : "bad") : "?"}</span>
            <span className={`chip ${c?.read_error ? "bad" : ""}`}>read {c?.read_error ? "error" : "ok"}</span>
            <span className="chip">{String((status?.device as { version?: string })?.version ?? "")} · {c?.backend ?? "none"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
