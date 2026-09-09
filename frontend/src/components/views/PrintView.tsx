import { api } from "../../lib/api.ts";
import { fmtMm, fmtSecs, heightMismatch, tri, type Gates } from "../../lib/format.ts";
import { AXES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { compileRecipe, describeStep, type RecipePlan } from "../../lib/recipe.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { CrossSection } from "../CrossSection.tsx";
import { Elevation } from "../Elevation.tsx";
import { ModuleGrid, type Module } from "../Modules.tsx";
import type { Call } from "./types.ts";

const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };

export function phrase(step: ReturnType<typeof compileRecipe>[number] | null, plan: RecipePlan | null): string {
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

export function PrintView({ status, gates, call, order, onOrder, onJob }: { status: StatusPayload | null; gates: Gates; call: Call; order?: string[]; onOrder: (ids: string[]) => void; onJob: () => void }) {
  const c = status?.controller;
  const r = status?.recipe;
  const t = c?.telemetry ?? null;
  const job = status?.job ?? null;
  const plan = (r?.plan as unknown as RecipePlan | null) ?? null;
  const steps = plan ? compileRecipe(plan) : [];
  const cur = r?.current_step ? steps[r.current_step.index] ?? null : null;
  const curAction = cur && cur.kind === "wait" ? steps.slice(0, cur.index).reverse().find((s) => s.kind !== "wait" && s.kind !== "mark") ?? cur : cur;
  const next = cur ? steps.slice(cur.index + 1).find((s) => !["wait", "mark", "set_speed", "set_accel"].includes(s.kind)) ?? null : null;
  const active = !!r && (r.state === "running" || r.state === "paused");
  const isMacro = !!r?.macro;
  const total = plan ? estimateDurationS(plan) : 0;
  const remaining = r && total ? Math.max(0, total * (1 - r.step_index / Math.max(r.n_steps, 1))) : null;
  const thickness = plan && r ? (plan[r.phase as "precoat" | "printing" | "postcoat"]?.layer_thickness_mm ?? 2) : 2;
  const mismatch = r ? heightMismatch(r.part_height_measured_mm, r.part_height_mm, thickness) : false;
  const printLayer = r && r.phase === "printing" ? r.layer - (plan?.precoat.n_layers ?? 0) : 0;
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
        <div className="actions tight">
          {r?.state === "running" && <button className="cta" disabled={!gates.connected} onClick={() => call("pause", api.recipePause)}>PAUSE</button>}
          {r?.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call(r.single_step ? "step" : "resume", r.single_step ? api.recipeStep : api.recipeResume)}>{r.single_step ? "NEXT STEP" : "RESUME"}</button>}
          {active ? <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.recipeAbort)}>ABORT</button>
            : <button className="cta primary" style={{ gridColumn: "1 / -1" }} onClick={onJob}>{job ? "START THIS JOB" : "CHOOSE A JOB"}</button>}
        </div>
      </>
    ) },
    { id: "machine", title: "machine", size: "m", node: (
      <>
        <div className="mini-el"><Elevation status={status} partZeroMm={r?.part_zero_mm ?? null} /></div>
        <div className="readout">{AXES.map((a) => <div key={a}><i className={SW[a]} />{SHORT[a]}<b>{t ? `${(t.positions[String(a)] ?? 0).toFixed(1)} mm` : "—"}</b></div>)}</div>
        <div className="narr" style={{ marginTop: 14, fontSize: 14 }}>{narr}{active && next && <div className="next">next: {phrase(next, plan)}</div>}</div>
      </>
    ) },
    { id: "problems", title: "attention", size: "s", hidden: problems.length === 0 && !mismatch, node: (
      <div className="chips" style={{ marginTop: 0 }}>{problems.map(([txt, cls]) => <span key={txt} className={`chip ${cls}`}>{txt}</span>)}{mismatch && <span className="chip warn">part height differs from the print settings ({fmtMm(r?.part_height_mm, 1)})</span>}</div>
    ) },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} onOrder={onOrder} /></div>;
}
