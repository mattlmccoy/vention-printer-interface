import { useEffect, useState } from "react";
import { api, type Discovery, type RecipePayload, SITE_MODE } from "../lib/api.ts";
import { armHint, fmtMm, fmtSecs, fmtSpeed, type Gates } from "../lib/format.ts";
import { AXES, AXIS_NAMES, AXIS_SHORT, type AxisNo, type StatusPayload } from "../lib/telemetry.ts";
import { PHASES, type PhasePlan, type RecipePlan, compileRecipe, describeStep, validate } from "../lib/recipe.ts";

export type Call = (label: string, fn: () => Promise<unknown>) => Promise<void>;
interface Common { status: StatusPayload | null; gates: Gates; call: Call }

// ---- connection ----------------------------------------------------------------------------
export function ConnectionSection({ status, gates, call, baseInput, setBaseInput, applyBase, version }: Common & { baseInput: string; setBaseInput: (s: string) => void; applyBase: () => void; version: string | null }) {
  const [disc, setDisc] = useState<Discovery | null>(null);
  const [choice, setChoice] = useState("simulated");
  const [ip, setIp] = useState("192.168.0.2");
  const [heaterIo, setHeaterIo] = useState("1,0");
  const refresh = () => api.discovery().then(setDisc).catch(() => setDisc(null));
  useEffect(() => { refresh(); }, [gates.reachable]);
  const [dev, pin] = heaterIo.split(",").map((s) => parseInt(s.trim(), 10));
  const heaterOk = Number.isInteger(dev) && Number.isInteger(pin) && dev >= 1 && dev <= 8 && pin >= 0 && pin <= 3;
  return (
    <>
      {SITE_MODE && (
        <div className="row" style={{ marginBottom: 8 }}>
          <label className="hint">operator</label>
          <input type="text" value={baseInput} onChange={(e) => setBaseInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") applyBase(); }} placeholder="http://localhost:8020" />
          <button className="secondary" onClick={applyBase}>apply</button>
        </div>
      )}
      <div className="kv">
        <span>state</span><span className="v">{status?.controller.state ?? "—"}</span>
        <span>backend</span><span className="v plain">{status?.controller.backend ?? "—"}</span>
        <span>controller</span><span className="v plain">{String((status?.device as { version?: string })?.version ?? "—")}</span>
        <span>operator</span><span className="v plain">{version ? `v${version}` : "—"}</span>
      </div>
      {!gates.connected ? (
        <>
          <div className="row" style={{ marginTop: 8 }}>
            <select value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="simulated">simulator</option>
              <option value="ethernet">MachineMotion — Ethernet</option>
              <option value="usb">MachineMotion — USB</option>
              <option value="custom">MachineMotion — custom IP</option>
            </select>
            <button className="secondary" onClick={refresh} title="Probe 192.168.0.2 / 192.168.7.2 on port 8000">rescan</button>
          </div>
          {choice === "custom" && <div className="row" style={{ marginTop: 6 }}><label className="hint">ip</label><input type="text" value={ip} onChange={(e) => setIp(e.target.value)} /></div>}
          <div className="row" style={{ marginTop: 6 }}>
            <label className="hint" title="IO module id,pin of the heater relay — UNVERIFIED default; confirm during commissioning">heater io</label>
            <input type="text" value={heaterIo} onChange={(e) => setHeaterIo(e.target.value)} style={{ width: 60 }} />
          </div>
          {disc && <ul className="help" style={{ margin: "6px 0" }}>{disc.candidates.map((c) => <li key={`${c.backend}${c.ip}`} className={c.reachable ? "" : "muted"}>{c.label ?? c.backend}{c.ip ? ` ${c.ip}` : ""}: {c.reachable ? "reachable" : "not reachable"}</li>)}</ul>}
          <button className="primary" disabled={!gates.reachable || !heaterOk} onClick={() => call("connect", () => api.connect({
            backend: choice === "simulated" ? "simulated" : "machinemotion",
            ip: choice === "ethernet" ? "192.168.0.2" : choice === "usb" ? "192.168.7.2" : choice === "custom" ? ip : null,
            heater_io: [dev, pin],
          }))}>connect (read-only)</button>
          <div className="hint" style={{ marginTop: 4 }}>Connecting is read-only. Check positions against the machine, then ARM.</div>
        </>
      ) : (
        <button className="secondary" style={{ marginTop: 8 }} onClick={() => call("disconnect", api.disconnect)}>disconnect</button>
      )}
    </>
  );
}

// ---- arm / e-stop --------------------------------------------------------------------------
export function ArmSection({ status, gates, call }: Common) {
  const c = status?.controller;
  return (
    <>
      <button className="danger estop" disabled={!gates.connected} onClick={() => call("e-stop", api.estop)} title="Stop all motion, heater off, controller e-stop. Never gated.">■ E-STOP</button>
      <div className="row" style={{ marginTop: 8 }}>
        {gates.armed
          ? <button className="secondary" onClick={() => call("disarm", api.disarm)}>● ARMED — click to DISARM</button>
          : <button className="primary" disabled={!gates.connected || gates.faulted} onClick={() => call("arm", api.arm)}>▲ ARM — take control</button>}
        <button className="secondary" disabled={!gates.connected} onClick={() => call("stop", api.stop)}>STOP motion</button>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>{armHint(gates, c?.fault_reasons ?? [])}</div>
      {gates.faulted && (
        <div className="row" style={{ marginTop: 6 }}>
          {c?.telemetry?.estop_triggered !== false && <button className="secondary" onClick={() => call("release e-stop", api.estopRelease)}>release e-stop + reset drives</button>}
          <button className="secondary" onClick={() => call("clear fault", api.clearFault)}>clear fault</button>
        </div>
      )}
      {c && c.warnings.length > 0 && <div className="warnbox" style={{ marginTop: 6 }}>{c.warnings.join("; ")}</div>}
      {c?.read_error && <div className="errbox" style={{ marginTop: 6 }}>read error: {c.read_error}</div>}
    </>
  );
}

// ---- axes ----------------------------------------------------------------------------------
function AxisRow({ a, status, gates, call }: Common & { a: AxisNo }) {
  const tel = status?.controller.telemetry;
  const p = tel?.positions[String(a)];
  const done = tel?.motion_complete[String(a)];
  const lim = status?.controller.limits;
  const am = status?.axis_motion[String(a)];
  const [target, setTarget] = useState("");
  const [speed, setSpeed] = useState("");
  const [accel, setAccel] = useState("");
  const rel = (mm: number) => call(`jog ${AXIS_SHORT[a]} ${mm}`, () => api.move(a, "rel", mm));
  return (
    <div className="axis-row">
      <span className="nm"><span className={`sw ${["", "part", "feed", "ph", "rc"][a]}`} />{AXIS_NAMES[a]} {done === false && <span className="badge warn">moving</span>}</span>
      <span className="pos">{fmtMm(p)}</span>
      <div className="ctl">
        <button className="secondary" disabled={!gates.controllable} onClick={() => call(`home ${AXIS_SHORT[a]}`, () => api.home([a]))}>home</button>
        {[-10, -1, 1, 10].map((d) => <button key={d} className="secondary" disabled={!gates.controllable} onClick={() => rel(d)}>{d > 0 ? `+${d}` : d}</button>)}
        <input type="number" placeholder="mm" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!gates.controllable} />
        <button className="secondary" disabled={!gates.controllable || target === ""} onClick={() => call(`move ${AXIS_SHORT[a]}`, () => api.move(a, "abs", Number(target)))}>go</button>
      </div>
      <div className="ctl">
        <span className="hint">speed</span>
        <input type="number" placeholder={am?.max_speed != null ? String(am.max_speed) : "?"} value={speed} onChange={(e) => setSpeed(e.target.value)} disabled={!gates.controllable} title={`limit ${fmtSpeed(lim?.max_speed[String(a)])}`} />
        <span className="hint">accel</span>
        <input type="number" placeholder={am?.max_accel != null ? String(am.max_accel) : "?"} value={accel} onChange={(e) => setAccel(e.target.value)} disabled={!gates.controllable} title={`limit ${lim?.max_accel[String(a)] ?? "?"} mm/s²`} />
        <button className="secondary" disabled={!gates.controllable || (speed === "" && accel === "")} onClick={() => call(`set ${AXIS_SHORT[a]} motion`, () => api.setAxisMotion(a, { ...(speed !== "" ? { max_speed: Number(speed) } : {}), ...(accel !== "" ? { max_accel: Number(accel) } : {}) }))}>apply</button>
        <span className="hint">≤ {fmtSpeed(lim?.max_speed[String(a)])}</span>
      </div>
    </div>
  );
}

export function AxesSection(p: Common) {
  return (
    <>
      <div className="row" style={{ marginBottom: 6 }}>
        <button className="primary" disabled={!p.gates.controllable} onClick={() => p.call("home all", () => api.home([]))}>home all (G28)</button>
        <button className="secondary" disabled={!p.gates.connected} onClick={() => p.call("stop", api.stop)}>stop</button>
      </div>
      {AXES.map((a) => <AxisRow key={a} a={a} {...p} />)}
      <div className="hint">Speeds/accels are clamped to the safety limits (tighten-only). Relative jogs need a fresh sample and an idle axis.</div>
    </>
  );
}

// ---- heater --------------------------------------------------------------------------------
export function HeaterSection({ status, gates, call }: Common) {
  const h = status?.controller.heater;
  const on = h?.on ?? null;
  return (
    <>
      <div className="kv">
        <span>relay (observed)</span><span className={`v${on === true ? "" : " plain"}`}>{on === null ? "unknown" : on ? "ON" : "off"}</span>
        <span>commanded</span><span className="v plain">{h?.commanded_on ? "on" : "off"}</span>
        <span>on-time</span><span className="v plain">{fmtSecs(h?.on_s)} / {fmtSecs(h?.max_on_s)} watchdog</span>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="danger" disabled={!gates.controllable || gates.recipeActive} onClick={() => { if (window.confirm(`Turn the IR heater ON now? It switches off automatically after ${fmtSecs(h?.max_on_s)} or on any fault.`)) call("heater on", api.heaterOn); }}>heater ON</button>
        <button className="secondary" disabled={!gates.connected} onClick={() => call("heater off", api.heaterOff)}>heater OFF</button>
      </div>
      <div className="hint" style={{ marginTop: 4 }}>The relay's IO module/pin is unverified until commissioning; "unknown" means the broker has not echoed its state.</div>
    </>
  );
}

// ---- recipe --------------------------------------------------------------------------------
function num(v: string, fb: number): number { const n = Number(v); return Number.isFinite(n) && v !== "" ? n : fb; }

export function RecipeSection({ status, gates, call }: Common) {
  const [rp, setRp] = useState<RecipePayload | null>(null);
  const [draft, setDraft] = useState<RecipePlan | null>(null);
  const [dry, setDry] = useState(true);
  const [single, setSingle] = useState(false);
  const load = () => api.recipe().then((r) => { setRp(r); setDraft(r.plan as unknown as RecipePlan); }).catch(() => undefined);
  useEffect(() => { load(); }, [gates.reachable]);
  const r = status?.recipe;
  const running = gates.recipeActive;
  const plan = draft;
  const reasons = plan ? validate(plan) : [];
  const setPhase = (ph: (typeof PHASES)[number], k: keyof PhasePlan, v: string) => plan && setDraft({ ...plan, [ph]: { ...plan[ph], [k]: num(v, plan[ph][k]) } });
  const setField = (k: keyof RecipePlan, v: string | boolean) => plan && setDraft({ ...plan, [k]: typeof v === "boolean" ? v : num(v, plan[k] as number) });
  const save = () => plan && call("save recipe", () => api.setRecipe(plan as unknown as Record<string, unknown>).then((res) => { setRp(res); setDraft(res.plan as unknown as RecipePlan); }));
  const start = () => {
    if (!dry && !window.confirm(`Start the print recipe on the machine? ${plan ? compileRecipe(plan).length : "?"} steps, heater ${plan?.heater_enabled ? "ENABLED" : "disabled"}. A run will be recorded.`)) return;
    call("start recipe", () => api.recipeStart({ dry_run: dry, single_step: single }));
  };
  const stepsPlan = (r?.plan as unknown as RecipePlan | null) ?? plan;
  const step = stepsPlan ? compileRecipe(stepsPlan) : [];
  const cur = r && r.current_step ? step[r.current_step.index] ?? null : null;
  return (
    <>
      {r && r.state !== "idle" && (
        <div style={{ marginBottom: 8 }}>
          <div className="row"><span className={`badge ${r.state === "fault" ? "bad" : r.state === "running" ? "warn" : "lib"}`}>{r.state}{r.dry_run ? " · dry run" : ""}{r.single_step ? " · single-step" : ""}</span><span className="muted">{fmtSecs(r.elapsed_s)}</span></div>
          <div className="progressbar" style={{ margin: "6px 0" }}><div className="progressbar-fill" style={{ width: `${r.n_steps ? (100 * r.step_index) / r.n_steps : 0}%` }} /></div>
          <div className="kv">
            <span>layer</span><span className="v">{r.layer} / {r.n_layers} <span className="muted">{r.phase}</span></span>
            <span>step</span><span className="v plain">{r.step_index} / {r.n_steps} — {describeStep(cur ?? (r.current_step as unknown as typeof cur))}</span>
            <span>part height</span><span className="v plain">{fmtMm(r.part_height_mm, 1)}</span>
            {r.reason && <><span>reason</span><span className="v plain">{r.reason}</span></>}
          </div>
        </div>
      )}
      <div className="row" style={{ marginBottom: 8 }}>
        {!running && <>
          <label className="hint"><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /> dry run (no heater)</label>
          <label className="hint"><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> single-step</label>
          <button className={dry ? "secondary" : "danger"} disabled={!gates.controllable || reasons.length > 0} onClick={start}>{dry ? "start dry run" : "▶ START PRINT"}</button>
        </>}
        {running && r?.state === "running" && <button className="secondary" onClick={() => call("pause", api.recipePause)}>pause</button>}
        {running && r?.state === "paused" && <>
          <button className="primary" disabled={!gates.controllable} onClick={() => call("resume", api.recipeResume)}>resume</button>
          <button className="secondary" disabled={!gates.controllable} onClick={() => call("step", api.recipeStep)}>step ▸</button>
        </>}
        {running && <button className="danger" onClick={() => call("abort", api.recipeAbort)}>abort</button>}
      </div>
      {plan && (
        <>
          <div className="phase-grid">
            <span className="h"></span>{PHASES.map((ph) => <span key={ph} className="h">{ph}</span>)}
            <span>thickness mm</span>{PHASES.map((ph) => <input key={ph} type="number" step="0.1" value={plan[ph].layer_thickness_mm} disabled={running} onChange={(e) => setPhase(ph, "layer_thickness_mm", e.target.value)} />)}
            <span>layers</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].n_layers} disabled={running} onChange={(e) => setPhase(ph, "n_layers", e.target.value)} />)}
            <span>part mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" step="0.1" value={plan[ph].part_speed} disabled={running} onChange={(e) => setPhase(ph, "part_speed", e.target.value)} />)}
            <span>recoater mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].recoater_speed} disabled={running} onChange={(e) => setPhase(ph, "recoater_speed", e.target.value)} />)}
            <span>printhead mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].printhead_speed} disabled={running} onChange={(e) => setPhase(ph, "printhead_speed", e.target.value)} />)}
          </div>
          <div className="kv" style={{ marginTop: 8 }}>
            {(["feed_end_mm", "recoater_end_mm", "printhead_end_mm", "heater_end_mm", "heater_speed", "n_heater_passes", "settle_s"] as const).map((k) => (
              <span key={k} style={{ display: "contents" }}><span>{k.replace(/_/g, " ")}</span><input type="number" value={plan[k]} disabled={running} onChange={(e) => setField(k, e.target.value)} style={{ width: 80, justifySelf: "end" }} /></span>
            ))}
            <span>heater enabled</span><input type="checkbox" checked={plan.heater_enabled} disabled={running} onChange={(e) => setField("heater_enabled", e.target.checked)} style={{ justifySelf: "end" }} />
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="secondary" disabled={running} onClick={save}>save plan</button>
            <span className="hint">{compileRecipe(plan).length} steps · {PHASES.reduce((s, ph) => s + plan[ph].n_layers, 0)} layers · {PHASES.reduce((s, ph) => s + plan[ph].n_layers * plan[ph].layer_thickness_mm, 0).toFixed(1)} mm</span>
          </div>
          {reasons.length > 0 ? <div className="errbox" style={{ marginTop: 6 }}>{reasons.map((x) => <div key={x}>{x}</div>)}</div> : <div className="okbox" style={{ marginTop: 6 }}>printable{rp?.validation.length ? " (server: " + rp.validation.join("; ") + ")" : ""}</div>}
        </>
      )}
    </>
  );
}

// ---- recording -----------------------------------------------------------------------------
export function RecordingSection({ status, gates, call }: Common) {
  const [name, setName] = useState("run");
  const [runs, setRuns] = useState<Array<{ run: string; complete: boolean; size_bytes: number }>>([]);
  const refresh = () => api.recordings().then((r) => setRuns(r.runs)).catch(() => undefined);
  useEffect(() => { refresh(); }, [status?.recording.active]);
  const rec = status?.recording;
  return (
    <>
      <div className="row">
        {rec?.active
          ? <button className="secondary" onClick={() => call("stop recording", api.recordingStop)}>■ stop {rec.run}</button>
          : <><input type="text" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 120 }} /><button className="secondary" disabled={!gates.connected} onClick={() => call("start recording", () => api.recordingStart({ name, notes: "" }))}>● record</button></>}
        <label className="hint"><input type="checkbox" checked={status?.auto_log ?? true} onChange={(e) => call("auto-log", () => api.setAutoLog(e.target.checked))} /> auto-log recipes</label>
      </div>
      <ul className="help" style={{ marginTop: 6 }}>{runs.slice(-8).reverse().map((r) => <li key={r.run}>{r.run} <span className={r.complete ? "muted" : "badge bad"}>{r.complete ? "complete" : "INCOMPLETE"}</span> <a href={`/api/recordings/${r.run}/telemetry.csv`} target="_blank" rel="noreferrer">csv</a></li>)}</ul>
    </>
  );
}
