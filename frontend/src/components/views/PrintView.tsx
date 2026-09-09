import { api } from "../../lib/api.ts";
import { fmtMm, fmtSecs, heightMismatch, tri, type Gates } from "../../lib/format.ts";
import { AXES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { compileRecipe, describeStep, type RecipePlan } from "../../lib/recipe.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { Elevation } from "../Elevation.tsx";
import type { Call } from "./types.ts";

const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

function phrase(step: ReturnType<typeof compileRecipe>[number] | null, plan: RecipePlan | null): string {
  if (!step || !plan) return "";
  const v = step.value ?? 0;
  switch (step.kind) {
    case "home_all": return "homing every axis";
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

export function PrintView({ status, gates, call, onPrepare }: { status: StatusPayload | null; gates: Gates; call: Call; onPrepare: () => void }) {
  const c = status?.controller;
  const r = status?.recipe;
  const t = c?.telemetry ?? null;
  const plan = (r?.plan as unknown as RecipePlan | null) ?? null;
  const steps = plan ? compileRecipe(plan) : [];
  const cur = r?.current_step ? steps[r.current_step.index] ?? null : null;
  const curAction = cur && cur.kind === "wait" ? steps.slice(0, cur.index).reverse().find((s) => s.kind !== "wait" && s.kind !== "mark") ?? cur : cur;
  const next = cur ? steps.slice(cur.index + 1).find((s) => s.kind !== "wait" && s.kind !== "mark" && s.kind !== "set_speed" && s.kind !== "set_accel") ?? null : null;
  const active = !!r && (r.state === "running" || r.state === "paused");
  const isMacro = !!r?.macro;
  const total = plan ? estimateDurationS(plan) : 0;
  const remaining = r && total ? Math.max(0, total * (1 - r.step_index / Math.max(r.n_steps, 1))) : null;
  const thickness = plan && r ? (plan[r.phase as "precoat" | "printing" | "postcoat"]?.layer_thickness_mm ?? 2) : 2;
  const mismatch = r ? heightMismatch(r.part_height_measured_mm, r.part_height_mm, thickness) : false;
  const layerFrac = (() => {
    if (!cur || !r) return 0;
    let s0 = -1; for (let i = cur.index; i >= 0; i--) if (steps[i].label === "layer_start") { s0 = i; break; }
    if (s0 < 0) return 0;
    const end = steps.findIndex((s, i) => i > s0 && s.label === "layer_end");
    return end > s0 ? (cur.index - s0) / (end - s0) : 0;
  })();
  const label = !status ? "OFFLINE" : isMacro && active ? r!.macro!.replace("_", " ").toUpperCase() : r?.state === "running" ? (r.dry_run ? "DRY RUN" : "PRINTING") : r?.state === "paused" ? "PAUSED" : (r?.state ?? "idle").toUpperCase();
  const problems: Array<[string, "bad" | "warn"]> = [];
  if (t?.estop_triggered) problems.push(["e-stop asserted", "bad"]);
  if (t?.estop_triggered === null && gates.connected) problems.push(["e-stop status unknown", "warn"]);
  if (t?.drives_ready === false) problems.push(["drives not ready", "bad"]);
  if (t && !t.health_ok) problems.push(["controller health bad", "bad"]);
  if (c?.read_error) problems.push(["telemetry read error", "bad"]);
  if (c?.heater.on) problems.push([`heater on ${fmtSecs(c.heater.on_s)} / ${fmtSecs(c.heater.max_on_s)}`, "warn"]);
  return (
    <section className="view print">
      <div className="run">
        <div className="h">Current print{status?.recording.run ? ` · ${status.recording.run.replace(/^\d{8}_\d{6}_/, "")}` : ""}</div>
        <div className="state"><span className={`big ${r?.state === "fault" ? "fault" : ""}`}>{label}</span>{r?.reason && <span className="sub">{r.reason}</span>}</div>
        {!isMacro && <div className="layer-no">{r?.layer ?? 0}<small> / {r?.n_layers || plan?.printing.n_layers || 0}</small></div>}
        {!isMacro && <div className="layer-cap">{active ? `layer · ${r!.phase}` : "layers"}</div>}
        <div className="bar"><i className="layer" style={{ width: `${Math.round(layerFrac * 100)}%` }} /></div>
        <div className="bar-lbl">this layer {Math.round(layerFrac * 100)}%</div>
        <div className="bar"><i style={{ width: `${r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0}%` }} /></div>
        <div className="bar-lbl">{isMacro ? "macro" : "whole print"} {r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0}%</div>
        <div className="kv">
          <span>elapsed</span><span>{fmtSecs(r?.elapsed_s)}</span>
          <span>remaining</span><span>{active && remaining !== null ? `~${fmtSecs(remaining)}` : "—"}</span>
          <span>part height</span><span className={mismatch ? "warnv" : ""}>{fmtMm(r?.part_height_measured_mm, 1)}{mismatch ? ` (recipe ${fmtMm(r?.part_height_mm, 1)})` : ""}</span>
          <span>heater</span><span className={c?.heater.on ? "bad" : ""}>{tri(c?.heater.on, "ON", "off", "unknown")}</span>
        </div>
        {mismatch && <div className="warnline">The build piston was moved outside the recipe.</div>}
        <div className="actions">
          {r?.state === "running" && <button className="cta" disabled={!gates.connected} onClick={() => call("pause", api.recipePause)}>PAUSE</button>}
          {r?.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call(r.single_step ? "step" : "resume", r.single_step ? api.recipeStep : api.recipeResume)}>{r.single_step ? "NEXT STEP" : "RESUME"}</button>}
          {active ? <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.recipeAbort)}>ABORT</button>
            : <button className="cta primary" onClick={onPrepare}>PREPARE A PRINT</button>}
        </div>
        {active && r?.single_step && r.state === "paused" && <div className="lock">single-step: press NEXT STEP for each move, or RESUME to run on</div>}
      </div>
      <div className="machine">
        <Elevation status={status} partZeroMm={r?.part_zero_mm ?? null} />
        <div className="readout">{AXES.map((a) => <div key={a}><i className={SW[a]} />{SHORT[a]}<b>{t ? `${(t.positions[String(a)] ?? 0).toFixed(1)} mm` : "—"}</b></div>)}</div>
        <div className="narr">
          {active ? `${isMacro ? r!.macro!.replace("_", " ") : `Layer ${r!.layer}`} · ${phrase(curAction, plan)}` : c?.state === "fault" ? "Faulted. Follow the steps in the banner." : gates.armed ? "Armed and idle." : gates.connected ? "Connected, read-only. ARM to take control." : "Not connected."}
          {active && next && <div className="next">next: {phrase(next, plan)}</div>}
        </div>
        {problems.length > 0 && <div className="chips">{problems.map(([txt, cls]) => <span key={txt} className={`chip ${cls}`}>{txt}</span>)}</div>}
      </div>
    </section>
  );
}
