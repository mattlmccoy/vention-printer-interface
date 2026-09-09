import { useState } from "react";
import { api } from "../../lib/api.ts";
import { JOG_STEPS } from "../../lib/console.ts";
import { fmtSecs, fmtSpeed, tri, type Gates } from "../../lib/format.ts";
import { AXIS_NAMES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import type { Call } from "./types.ts";

const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

function Axis({ a, status, ok, call, step }: { a: AxisNo; status: StatusPayload | null; ok: boolean; call: Call; step: number }) {
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(a)];
  const moving = t ? t.motion_complete[String(a)] === false : false;
  const piston = a === 1 || a === 2;
  const lim = status?.controller.limits;
  const [target, setTarget] = useState("");
  const [speed, setSpeed] = useState("");
  const rel = (sign: 1 | -1) => call(`jog ${AXIS_NAMES[a]}`, () => api.move(a, "rel", sign * step));
  const abs = (mm: number) => call(`move ${AXIS_NAMES[a]}`, () => api.move(a, "abs", mm));
  return (
    <div className="axis">
      <span className="nm"><i className={SW[a]} />{AXIS_NAMES[a]}</span>
      <span className="pos">{typeof pos === "number" ? pos.toFixed(1) : "—"} <small>mm{moving ? " · moving" : ""}</small></span>
      <div className="jog">
        <button disabled={!ok} onClick={() => rel(-1)}>{piston ? "▲ UP" : "◀ TOWARD HOME"}</button>
        <button disabled={!ok} onClick={() => rel(1)}>{piston ? "▼ DOWN" : "AWAY ▶"}</button>
        <button className="home" disabled={!ok} title="home this axis" onClick={() => call(`home ${AXIS_NAMES[a]}`, () => api.home([a]))}>⌂</button>
      </div>
      <details style={{ gridColumn: "1 / -1", marginTop: 4 }}>
        <summary>more</summary>
        <div className="body row">
          go to <input type="number" value={target} placeholder="mm" onChange={(e) => setTarget(e.target.value)} disabled={!ok} /><button className="small" disabled={!ok || target === ""} onClick={() => abs(Number(target))}>go</button>
          <span>speed</span><input type="number" value={speed} placeholder={String(status?.axis_motion[String(a)]?.max_speed ?? "")} onChange={(e) => setSpeed(e.target.value)} disabled={!ok} /><button className="small" disabled={!ok || speed === ""} onClick={() => call("set speed", () => api.setAxisMotion(a, { max_speed: Number(speed) }))}>set</button><span>limit {fmtSpeed(lim?.max_speed[String(a)])}</span>
        </div>
      </details>
    </div>
  );
}

export function ControlView({ status, gates, call, gantryStep, pistonStep, setGantryStep, setPistonStep }: { status: StatusPayload | null; gates: Gates; call: Call; gantryStep: number; pistonStep: number; setGantryStep: (s: number) => void; setPistonStep: (s: number) => void }) {
  const c = status?.controller;
  const t = c?.telemetry;
  const ok = gates.controllable && !gates.recipeActive;
  return (
    <section className="view control">
      <div className="col">
        <div className="h">Gantries</div>
        <div className="stepper">step {JOG_STEPS.map((s) => <button key={s} className={s === gantryStep ? "on" : ""} onClick={() => setGantryStep(s)}>{s} mm</button>)}</div>
        <Axis a={3} status={status} ok={ok} call={call} step={gantryStep} />
        <Axis a={4} status={status} ok={ok} call={call} step={gantryStep} />
        <div className="actions"><button className="cta" disabled={!ok} onClick={() => call("home all", () => api.home([]))}>HOME ALL</button><button className="cta danger" disabled={!gates.connected} onClick={() => call("stop", api.stop)}>STOP</button></div>
        {!gates.controllable && <div className="lock">{gates.connected ? "read-only · ARM in the top bar to jog" : "connect a controller to jog"}</div>}
        {gates.recipeActive && <div className="lock">a print or macro is running · manual motion is locked</div>}
      </div>
      <div className="col">
        <div className="h">Pistons</div>
        <div className="stepper">step {JOG_STEPS.map((s) => <button key={s} className={s === pistonStep ? "on" : ""} onClick={() => setPistonStep(s)}>{s} mm</button>)}</div>
        <Axis a={1} status={status} ok={ok} call={call} step={pistonStep} />
        <Axis a={2} status={status} ok={ok} call={call} step={pistonStep} />
        <div className="h" style={{ marginTop: 26 }}>Park</div>
        <div className="actions" style={{ marginTop: 0 }}>
          <button className="cta" disabled={!ok} onClick={() => { if (window.confirm("Home all axes, then lower BOTH pistons to the bottom of travel?")) call("load cart", () => api.macro("load_cart")); }}>LOAD CART</button>
          <button className="cta" disabled={!ok} onClick={() => call("clear bed", () => api.macro("clear_bed"))}>CLEAR BED</button>
        </div>
        <div className="hint" style={{ marginTop: 10 }}>Load cart lowers both pistons and homes the gantries. Then jog the pistons into place.</div>
        <details>
          <summary>Heater and I/O</summary>
          <div className="body">
            <div className="row">heater {tri(c?.heater.on, `ON ${fmtSecs(c?.heater.on_s)}`, "off", "not observed")} · watchdog {fmtSecs(c?.heater.max_on_s)} · io {Array.isArray(status?.device.heater_io) ? (status!.device.heater_io as number[]).join("/") : "—"} (unverified)</div>
            <div className="actions" style={{ marginTop: 12 }}>
              <button className="cta danger" disabled={!ok} onClick={() => { if (window.confirm(`Turn the IR heater ON? It switches off after ${fmtSecs(c?.heater.max_on_s)} or on any fault.`)) call("heater on", api.heaterOn); }}>HEATER ON</button>
              <button className="cta" disabled={!gates.connected} onClick={() => call("heater off", api.heaterOff)}>HEATER OFF</button>
            </div>
            <div className="chips">
              <span className={`chip ${t?.estop_triggered ? "bad" : t?.estop_triggered === null ? "warn" : ""}`}>e-stop {tri(t?.estop_triggered, "asserted", "clear")}</span>
              <span className={`chip ${t?.drives_ready === false ? "bad" : t?.drives_ready === null ? "warn" : ""}`}>drives {tri(t?.drives_ready, "ready", "not ready")}</span>
              <span className={`chip ${t && !t.health_ok ? "bad" : ""}`}>health {t ? (t.health_ok ? "ok" : "bad") : "?"}</span>
              <span className={`chip ${c?.read_error ? "bad" : ""}`}>read {c?.read_error ? "error" : "ok"}</span>
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}
