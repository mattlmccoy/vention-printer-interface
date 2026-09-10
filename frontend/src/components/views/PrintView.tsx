import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../lib/api.ts";
import { fmtMm, fmtSecs, heightMismatch, tri, type Gates } from "../../lib/format.ts";
import { AXES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { compilePrint, describeStep, totalLayers, totalThickness, validate, type PrintSettings } from "../../lib/print_settings.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { CrossSection } from "../CrossSection.tsx";
import { MachineImage } from "../MachineImage.tsx";
import { RoutinePanel } from "../RoutinePanel.tsx";
import { NumberField } from "../NumberField.tsx";
import { ModuleGrid, type Module } from "../Modules.tsx";
import type { Call } from "./types.ts";

const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };
const LAYER_HEIGHTS = [0.1, 0.15, 0.2];
// Compiled steps that are pure profile/blocking noise; the timeline collapses these away so each
// visible row is one meaningful action (a mark, a move, a home, a heater switch, a dwell).
const TIMELINE_NOISE = new Set(["set_speed", "set_accel", "wait"]);

export function phrase(step: ReturnType<typeof compilePrint>[number] | null, plan: PrintSettings | null): string {
  if (!step || !plan) return "";
  const v = step.value ?? 0;
  switch (step.kind) {
    case "home": return step.axis ? `homing ${({ 1: "build", 2: "feed", 3: "printhead", 4: "recoater" } as Record<number, string>)[step.axis]}` : "homing";
    case "move_rel": return step.axis === 1 ? `build piston down ${v} mm` : `feed piston up ${Math.abs(v)} mm`;
    case "move_abs":
      if (step.axis === 4) return v === plan.recoater_end_mm ? "spreading powder" : v === plan.heater_end_mm ? "heater pass" : "recoater returning";
      if (step.axis === 3) return v === plan.printhead_end_mm ? "printhead pass" : "printhead returning";
      if (step.axis === 2) return `feed piston to ${v} mm`;
      return `build piston to ${v} mm`;
    case "dwell": return "settling";
    case "heater": return v ? "heater on" : "heater off";
    case "wait": return "waiting for motion";
    default: return describeStep(step);
  }
}

export function PrintView({ status, gates, call, order, sizes, onOrder, onResize, onJob }: { status: StatusPayload | null; gates: Gates; call: Call; order?: string[]; sizes?: Record<string, import("../../lib/console.ts").ModuleSize>; onOrder: (ids: string[]) => void; onResize: (id: string, size: import("../../lib/console.ts").ModuleSize) => void; onJob: () => void }) {
  const c = status?.controller;
  const r = status?.print;
  const t = c?.telemetry ?? null;
  const job = status?.job ?? null;
  const plan = (r?.plan as unknown as PrintSettings | null) ?? null;
  const steps = plan ? compilePrint(plan) : [];
  const cur = r?.current_step ? steps[r.current_step.index] ?? null : null;
  const curAction = cur && cur.kind === "wait" ? steps.slice(0, cur.index).reverse().find((s) => s.kind !== "wait" && s.kind !== "mark") ?? cur : cur;
  const next = cur ? steps.slice(cur.index + 1).find((s) => !["wait", "mark", "set_speed", "set_accel"].includes(s.kind)) ?? null : null;
  const active = !!r && (r.state === "running" || r.state === "paused");
  const paused = r?.state === "paused";
  const isMacro = !!r?.macro;

  // ---- Feature 1: manual print (idle, no sliced job) — a focused START module that reuses the
  // print-settings edit/save + api.printStart flow (mirrors JobView, without the job machinery).
  const showManual = !active && !job;
  const [mplan, setMplan] = useState<PrintSettings | null>(null);
  const [mdirty, setMdirty] = useState(false);
  const [mdry, setMdry] = useState(true);
  const [msingle, setMsingle] = useState(false);
  // With no job selected, manual print is the only way to run — so the controls are shown by
  // default (the Print tab "assumes a manual print", reflecting anything staged from the Job tab).
  // The button beneath CHOOSE A JOB still toggles them hidden/shown.
  const [manualOpen, setManualOpen] = useState(true);
  useEffect(() => {
    if (!showManual) return;
    let live = true;
    api.printSettings().then((x) => { if (live) { setMplan(x.plan as unknown as PrintSettings); setMdirty(false); } }).catch(() => undefined);
    return () => { live = false; };
  }, [showManual, gates.reachable]);
  const medit = (patch: Partial<PrintSettings>) => mplan && (setMplan({ ...mplan, ...patch }), setMdirty(true));
  const meditPrinting = (patch: Partial<PrintSettings["printing"]>) => mplan && medit({ printing: { ...mplan.printing, ...patch } });
  // Send ONLY the fields this module owns as a partial patch (the backend deep-merges one level).
  // Sending the full plan would clobber routine fields set elsewhere — e.g. n_jet_passes (multipass)
  // and pre_heater_drop_mm from Routine Parameters — back to their loaded values.
  const mpatch = (p: PrintSettings) => ({ printing: { n_layers: p.printing.n_layers, layer_thickness_mm: p.printing.layer_thickness_mm }, postcoat_enabled: p.postcoat_enabled, heater_enabled: p.heater_enabled });
  const msave = async () => { if (!mplan) return; await call("save print_settings", () => api.setPrintSettings(mpatch(mplan)).then((x) => { setMplan(x.plan as unknown as PrintSettings); setMdirty(false); })); };
  const mReasons = mplan ? validate(mplan) : [];
  const mLayers = mplan ? totalLayers(mplan) : 0;
  const mTotal = mplan ? totalThickness(mplan) : 0;
  const mHeaterOn = !!mplan?.heater_enabled && !mdry;
  const mstart = async () => {
    if (!mplan) return;
    if (mdirty) await msave();
    if (!mdry) {
      const heat = mplan.heater_enabled ? "HEATER ON — fires each printing layer" : "⚠ HEATER OFF — no in-situ heating";
      if (!window.confirm(`Start the manual print on the machine?\n\n${heat}\n${mLayers} layers · ${mTotal.toFixed(1)} mm · ~${fmtSecs(estimateDurationS(mplan))}`)) return;
    }
    await call("start", () => api.printStart({ dry_run: mdry, single_step: msingle, name: "manual print" }));
  };

  const total = plan ? estimateDurationS(plan) : 0;
  const remaining = r && total ? Math.max(0, total * (1 - r.step_index / Math.max(r.n_steps, 1))) : null;
  const thickness = plan && r ? (plan[r.phase as "thin_precoat" | "printing" | "postcoat"]?.layer_thickness_mm ?? 2) : 2;
  const mismatch = r ? heightMismatch(r.part_height_measured_mm, r.part_height_mm, thickness) : false;
  const printLayer = r && r.phase === "printing" ? r.layer - (plan?.thin_precoat.n_layers ?? 0) : 0;
  const shownLayer = active && printLayer > 0 ? printLayer : (job ? 1 : 0);
  const pct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;
  const label = !status ? "OFFLINE" : isMacro && active ? r!.macro!.replace("_", " ").toUpperCase() : r?.state === "running" ? (r.dry_run ? "DRY RUN" : "PRINTING") : r?.state === "paused" ? "PAUSED" : (r?.state ?? "idle").toUpperCase();
  const problems: Array<[string, "bad" | "warn"]> = [];
  if (t?.estop_triggered) problems.push(["e-stop asserted", "bad"]);
  if (t?.estop_triggered === null && gates.connected) problems.push(["e-stop status unknown", "warn"]);
  if (t?.drives_ready === false) problems.push(["drives not ready", "bad"]);
  if (t && !t.health_ok) problems.push(["controller health bad", "bad"]);
  if (c?.read_error) problems.push(["telemetry read error", "bad"]);
  if (job && !job.complete) problems.push([`job missing pages ${job.missing_pages.slice(0, 5).join(", ")}`, "bad"]);
  const narr = active ? `${isMacro ? r!.macro!.replace("_", " ") : `layer ${r!.layer} of ${r!.n_layers}`} · ${phrase(curAction, plan)}` : c?.state === "fault" ? "faulted — follow the steps in the banner" : gates.armed ? "in control · idle" : gates.connected ? "read-only" : "not connected";

  // ---- Feature 3: timeline rows (meaningful actions only), grouped by phase/layer, highlighting
  // the current step; a row is clickable ONLY while paused (jump-to-step is a paused-only action).
  const timelineRows = steps.filter((s) => !TIMELINE_NOISE.has(s.kind));
  const activeStepIdx = r?.current_step?.index ?? -1;
  let curRowIndex = -1;
  for (const s of timelineRows) { if (s.index <= activeStepIdx) curRowIndex = s.index; else break; }
  const timelineNodes: ReactNode[] = [];
  let lastGroup = "";
  for (const s of timelineRows) {
    const group = `${s.phase}${s.layer ? ` · layer ${s.layer}` : ""}`;
    if (group !== lastGroup) { lastGroup = group; timelineNodes.push(<div key={`h${s.index}`} className="tl-head">{group}</div>); }
    const isCur = s.index === curRowIndex;
    timelineNodes.push(
      <button key={s.index} className={`tl-row${isCur ? " on" : ""}`} disabled={!paused}
        onClick={() => { if (paused && window.confirm(`Jump to step ${s.index}? The routine continues from there — you are responsible for the machine state.`)) call("seek", () => api.printSeek(s.index)); }}>
        <span className="n">{s.index}</span><span className="l">{phrase(s, plan) || describeStep(s)}</span>
      </button>
    );
  }

  const modules: Module[] = [
    { id: "layer", title: job ? `${job.name} · layer ${shownLayer} of ${job.layer_count}` : "layer", size: "l", node: (
      <>
        <CrossSection job={job} layer={shownLayer} />
        <div className="bar"><i className="layer" style={{ width: `${job && job.layer_count ? Math.round((100 * (active ? Math.max(printLayer - 1, 0) : 0)) / job.layer_count) : 0}%` }} /></div>
        <div className="bar-lbl">{job ? `${active ? Math.max(printLayer - 1, 0) : 0} of ${job.layer_count} layers printed` : "no job"}</div>
      </>
    ) },
    { id: "run", title: "this print", size: "s", node: (
      <>
        <div className="state" style={{ margin: "0 0 14px" }}><span className={`big ${r?.state === "fault" ? "fault" : ""}`}>{label}</span></div>
        {r?.reason && <div className="hint">{r.reason}</div>}
        <div className="bar" style={{ marginTop: 10 }}><i style={{ width: `${pct}%` }} /></div>
        <div className="bar-lbl">{pct}% · step {r?.step_index ?? 0} of {r?.n_steps ?? 0}</div>
        <div className="kv">
          <span>elapsed</span><span>{fmtSecs(r?.elapsed_s)}</span>
          <span>remaining</span><span>{active && remaining !== null ? `~${fmtSecs(remaining)}` : "—"}</span>
          <span>part height</span><span className={mismatch ? "warnv" : ""}>{fmtMm(r?.part_height_measured_mm, 1)}</span>
          <span>heater</span><span className={c?.heater.on ? "bad" : ""}>{tri(c?.heater.on, `ON ${fmtSecs(c?.heater.on_s)}`, "off", "unknown")}</span>
        </div>
        {active && (
          <label className="row" style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14, fontSize: 13 }} title="Pause after each step. Turning it off resumes continuous running.">
            <input type="checkbox" checked={!!r?.single_step} disabled={!gates.controllable} onChange={(e) => call("single-step", () => api.setSingleStep(e.target.checked))} /> single-step (pause after each step)
          </label>
        )}
        <div className="actions tight">
          {r?.state === "running" && <button className="cta" disabled={!gates.connected} onClick={() => call("pause", api.printPause)}>PAUSE</button>}
          {r?.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call(r.single_step ? "step" : "resume", r.single_step ? api.printStep : api.printResume)}>{r.single_step ? "NEXT STEP" : "RESUME"}</button>}
          {active ? <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
            : <>
                <button className="cta primary" style={{ gridColumn: "1 / -1" }} onClick={onJob}>{job ? "START THIS JOB" : "CHOOSE A JOB"}</button>
                {!job && <button className="cta" style={{ gridColumn: "1 / -1" }} aria-expanded={manualOpen} onClick={() => setManualOpen((v) => !v)}>{manualOpen ? "HIDE MANUAL PRINT" : "MANUAL PRINT (NO JOB)"}</button>}
              </>}
        </div>
      </>
    ) },
    { id: "manual", title: "manual print", size: "s", hidden: !(showManual && manualOpen), node: mplan ? (
      <>
        <div className="hint" style={{ marginTop: 0 }}>Run the print routine straight from these parameters — no sliced job needed.</div>
        <div className="fields" style={{ marginTop: 16, maxWidth: "none" }}>
          <span>print layers</span><span className="row"><NumberField value={mplan.printing.n_layers} disabled={!gates.controllable} style={{ width: 80 }} onChange={(v) => meditPrinting({ n_layers: v })} /></span>
          <span>layer height</span><label className="row">
            <span className="seg">{LAYER_HEIGHTS.map((h) => <button key={h} type="button" className={`small${Math.abs(mplan.printing.layer_thickness_mm - h) < 1e-6 ? " on" : ""}`} aria-pressed={Math.abs(mplan.printing.layer_thickness_mm - h) < 1e-6} disabled={!gates.controllable} onClick={() => meditPrinting({ layer_thickness_mm: h })}>{h}</button>)}</span>
            <NumberField step="0.05" value={mplan.printing.layer_thickness_mm} disabled={!gates.controllable} style={{ width: 72 }} onChange={(v) => meditPrinting({ layer_thickness_mm: v })} /> mm
          </label>
          <span>postcoat</span><label className="row"><input type="checkbox" checked={mplan.postcoat_enabled} disabled={!gates.controllable} onChange={(e) => medit({ postcoat_enabled: e.target.checked })} /> <b>{mplan.postcoat_enabled ? "ON" : "OFF"}</b></label>
          <span>heater</span><label className="row" title="Fires the IR heater during the printing layers. Forced off in a dry run."><input type="checkbox" checked={mHeaterOn} disabled={mdry || !gates.controllable} onChange={(e) => medit({ heater_enabled: e.target.checked })} /> <b>{mHeaterOn ? "ON" : "OFF"}</b>{mdry ? " (off in dry run)" : ""}</label>
        </div>
        <div className="chk" style={{ margin: "16px 0" }}>
          <label><input type="checkbox" checked={mdry} onChange={(e) => setMdry(e.target.checked)} /> dry run (motion only — no heat / no jet)</label>
          <label><input type="checkbox" checked={msingle} onChange={(e) => setMsingle(e.target.checked)} /> single-step</label>
        </div>
        {mReasons.length > 0 ? <div className="errline">{mReasons.join(" · ")}</div> : <div className="okline">{mLayers} layers · {mTotal.toFixed(1)} mm · ~{fmtSecs(estimateDurationS(mplan))}</div>}
        <div className="actions one tight">
          <button className={`cta ${mdry ? "" : "primary"}`} disabled={!gates.controllable || mReasons.length > 0} onClick={mstart}>{mdry ? "START DRY RUN" : "START PRINT"}</button>
          {mdirty && <button className="cta" disabled={!gates.controllable} onClick={msave}>SAVE CHANGES</button>}
        </div>
        {!gates.controllable && <div className="lock">{gates.connected ? "read-only · take control from the connection pill" : "connect a controller to start"}</div>}
      </>
    ) : <div className="hint">loading print_settings…</div> },
    { id: "machine", title: "machine", size: "m", node: (
      <>
        <MachineImage status={status} partZeroMm={r?.part_zero_mm ?? null} />
        <div className="readout">{AXES.map((a) => { const u = t?.referenced?.[String(a)] === false; return <div key={a}><i className={SW[a]} />{SHORT[a]}<b className={u ? "unref" : ""} title={u ? "not homed since power-on — unreferenced" : ""}>{!t ? "—" : u ? "unref" : `${(t.positions[String(a)] ?? 0).toFixed(1)} mm`}</b></div>; })}</div>
        <div className="narr" style={{ marginTop: 14, fontSize: 14 }}>{narr}{active && next && <div className="next">next: {phrase(next, plan)}</div>}</div>
      </>
    ) },
    { id: "timeline", title: "timeline", size: "m", hidden: timelineRows.length === 0, node: (
      <>
        <div className="hint" style={{ marginTop: 0 }}>{paused ? "Paused — click a step to jump the routine there." : "Live step list. Pause to enable jump-to-step."}</div>
        <div className="timeline">{timelineNodes}</div>
      </>
    ) },
    { id: "routine", title: "routine parameters", size: "m", node: <RoutinePanel gates={gates} call={call} /> },
    { id: "problems", title: "attention", size: "s", hidden: problems.length === 0 && !mismatch, node: (
      <div className="chips" style={{ marginTop: 0 }}>{problems.map(([txt, cls]) => <span key={txt} className={`chip ${cls}`}>{txt}</span>)}{mismatch && <span className="chip warn">part height differs from the print_settings ({fmtMm(r?.part_height_mm, 1)})</span>}</div>
    ) },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} sizes={sizes} onOrder={onOrder} onResize={onResize} /></div>;
}
