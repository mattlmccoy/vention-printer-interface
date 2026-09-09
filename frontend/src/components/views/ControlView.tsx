import { useState } from "react";
import { api } from "../../lib/api.ts";
import { JOG_STEPS } from "../../lib/console.ts";
import { fmtSecs, fmtSpeed, type Gates } from "../../lib/format.ts";
import { AXIS_NAMES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { HeaterRing } from "../HeaterRing.tsx";
import { IoGrid } from "../IoGrid.tsx";
import type { Call } from "./types.ts";

interface AxisProps { a: AxisNo; status: StatusPayload | null; gates: Gates; call: Call; step: number; setStep: (s: number) => void; pollHz: number | null }
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

function AxisPanel({ a, status, gates, call, step, setStep }: AxisProps) {
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(a)];
  const idle = t ? t.motion_complete[String(a)] !== false : false;
  const lim = status?.controller.limits;
  const am = status?.axis_motion[String(a)];
  const piston = a === 1 || a === 2;
  const [target, setTarget] = useState("");
  const [speed, setSpeed] = useState("");
  const [accel, setAccel] = useState("");
  const ok = gates.controllable && !gates.recipeActive;
  const rel = (sign: 1 | -1) => call(`jog ${AXIS_NAMES[a]}`, () => api.move(a, "rel", sign * step));
  const abs = (mm: number) => call(`move ${AXIS_NAMES[a]}`, () => api.move(a, "abs", mm));
  const far = lim?.travel_max[String(a)] ?? 0;
  const extra = a === 2 && typeof pos === "number" ? ` · ${(far - pos).toFixed(1)} mm powder` : "";
  return (
    <div className="axis">
      <span className="nm"><i className={SW[a]} />{AXIS_NAMES[a]}</span>
      <span className="pos">{typeof pos === "number" ? pos.toFixed(1) : "—"} <small>mm{piston ? " down" : ""} · {t ? (idle ? "idle" : "moving") : "—"}{extra}</small></span>
      <div className="jog">
        <button disabled={!ok} title={piston ? "piston fully up (0)" : "home end (0)"} onClick={() => abs(0)}>{piston ? "▲▲" : "⇤"}</button>
        <button disabled={!ok} onClick={() => rel(-1)}>{piston ? "▲ up" : "◀"}</button>
        <div className="steps">{JOG_STEPS.map((s) => <button key={s} className={s === step ? "on" : ""} onClick={() => setStep(s)}>{s} mm</button>)}</div>
        <button disabled={!ok} onClick={() => rel(1)}>{piston ? "▼ down" : "▶"}</button>
        <button disabled={!ok} title={piston ? `piston bottom (${far})` : `far end (${far})`} onClick={() => abs(far)}>{piston ? "▼▼" : "⇥"}</button>
      </div>
      <div className="row">
        move to <input type="number" value={target} placeholder="mm" onChange={(e) => setTarget(e.target.value)} disabled={!ok} /> <button className="small" disabled={!ok || target === ""} onClick={() => abs(Number(target))}>go</button>
        <span style={{ marginLeft: "auto" }}>speed <input type="number" value={speed} placeholder={am?.max_speed != null ? String(am.max_speed) : "?"} onChange={(e) => setSpeed(e.target.value)} disabled={!ok} /> accel <input type="number" value={accel} placeholder={am?.max_accel != null ? String(am.max_accel) : "?"} onChange={(e) => setAccel(e.target.value)} disabled={!ok} /> <button className="small" disabled={!ok || (speed === "" && accel === "")} onClick={() => call("set motion", () => api.setAxisMotion(a, { ...(speed !== "" ? { max_speed: Number(speed) } : {}), ...(accel !== "" ? { max_accel: Number(accel) } : {}) }))}>set</button> ≤ {fmtSpeed(lim?.max_speed[String(a)])}</span>
      </div>
    </div>
  );
}

export function ControlView({ status, gates, call, pollHz, gantryStep, pistonStep, setGantryStep, setPistonStep }: { status: StatusPayload | null; gates: Gates; call: Call; pollHz: number | null; gantryStep: number; pistonStep: number; setGantryStep: (s: number) => void; setPistonStep: (s: number) => void }) {
  const c = status?.controller;
  const ok = gates.controllable && !gates.recipeActive;
  const common = { status, gates, call, pollHz };
  return (
    <section className="view control">
      <div>
        <div className="card-h">Gantries</div>
        <AxisPanel a={3} {...common} step={gantryStep} setStep={setGantryStep} />
        <AxisPanel a={4} {...common} step={gantryStep} setStep={setGantryStep} />
        <div className="actions"><button className="cta" disabled={!ok} onClick={() => call("home all", () => api.home([]))}>⌂ HOME ALL (G28)</button><button className="cta" disabled={!gates.connected} onClick={() => call("stop", api.stop)}>■ STOP MOTION</button></div>
        {!gates.controllable && <div className="lock">{gates.connected ? "not armed → controls are read-only. ARM in the top bar." : "connect a controller to jog"}</div>}
        {gates.recipeActive && <div className="lock">a recipe or macro is running → manual motion is locked. Pause or abort it on the Print tab.</div>}
      </div>
      <div>
        <div className="card-h">Pistons<span className="muted">positions grow downward</span></div>
        <AxisPanel a={1} {...common} step={pistonStep} setStep={setPistonStep} />
        <AxisPanel a={2} {...common} step={pistonStep} setStep={setPistonStep} />
        <div className="card-h" style={{ marginTop: 14 }}>Park</div>
        <div className="actions">
          <button className="cta" disabled={!ok} onClick={() => { if (window.confirm("Load cart: home all axes, then drive BOTH pistons to the bottom of travel. Continue?")) call("load cart", () => api.macro("load_cart")); }}>LOAD CART · pistons ▼▼</button>
          <button className="cta" disabled={!ok} onClick={() => call("clear bed", () => api.macro("clear_bed"))}>CLEAR BED · home all</button>
        </div>
        <div className="hint" style={{ marginTop: 6 }}>After loading, jog the pistons into place by hand, then Prepare a print.</div>
      </div>
      <div>
        <div className="card-h">Heater (manual)</div>
        <div className="heater"><HeaterRing on={c?.heater.on ?? null} onS={c?.heater.on_s ?? 0} maxS={c?.heater.max_on_s ?? 0} /><div className="hkv"><span>relay</span><span>{c?.heater.on === null ? "not observed" : c?.heater.on ? "observed ON" : "observed off"}</span><span>commanded</span><span>{c?.heater.commanded_on ? "on" : "off"}</span><span>io module</span><span>{Array.isArray(status?.device.heater_io) ? (status!.device.heater_io as number[]).join(" · pin ") : "—"} <span style={{ color: "var(--warn)" }}>unverified</span></span><span>watchdog</span><span>{fmtSecs(c?.heater.max_on_s)}</span></div></div>
        <div className="actions">
          <button className="cta danger" disabled={!ok} onClick={() => { if (window.confirm(`Turn the IR heater ON now? It switches off automatically after ${fmtSecs(c?.heater.max_on_s)} or on any fault.`)) call("heater on", api.heaterOn); }}>HEATER ON</button>
          <button className="cta" disabled={!gates.connected} onClick={() => call("heater off", api.heaterOff)}>HEATER OFF</button>
        </div>
        <div className="card-h" style={{ marginTop: 20 }}>Machine I/O</div>
        <IoGrid status={status} pollHz={pollHz} />
      </div>
    </section>
  );
}
