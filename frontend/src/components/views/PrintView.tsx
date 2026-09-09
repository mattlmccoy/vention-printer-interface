import { api } from "../../lib/api.ts";
import { cycleIndex, fmtMm, fmtSecs, heightMismatch, type Gates } from "../../lib/format.ts";
import { AXIS_NAMES, AXES, type StatusPayload } from "../../lib/telemetry.ts";
import { compileRecipe, describeStep, type RecipePlan } from "../../lib/recipe.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { Elevation } from "../Elevation.tsx";
import { EventLog } from "../EventLog.tsx";
import { HeaterRing } from "../HeaterRing.tsx";
import { IoGrid } from "../IoGrid.tsx";
import type { Call } from "./types.ts";

const CYCLE = ["build ↓", "spread", "feed ↑", "recoater home", "jet pass", "dry"];

export function PrintView({ status, gates, call, pollHz, onPrepare }: { status: StatusPayload | null; gates: Gates; call: Call; pollHz: number | null; onPrepare: () => void }) {
  const c = status?.controller;
  const r = status?.recipe;
  const plan = (r?.plan as unknown as RecipePlan | null) ?? null;
  const steps = plan ? compileRecipe(plan) : [];
  const cur = r?.current_step ? steps[r.current_step.index] ?? null : null;
  const next = cur ? steps.slice(cur.index + 1).find((s) => s.kind !== "wait" && s.kind !== "mark") ?? null : null;
  const active = r && (r.state === "running" || r.state === "paused");
  const isMacro = !!r?.macro;
  const layerFrac = cur && r ? (() => { const start = steps.slice(0, cur.index + 1).reverse().findIndex((s) => s.label === "layer_start"); const s0 = cur.index - start; const end = steps.findIndex((s, i) => i > s0 && s.label === "layer_end"); return start >= 0 && end > s0 ? (cur.index - s0) / (end - s0) : 0; })() : 0;
  const total = plan ? estimateDurationS(plan) : 0;
  const remaining = r && total ? Math.max(0, total * (1 - r.step_index / Math.max(r.n_steps, 1))) : null;
  const thickness = plan && r ? (plan[(r.phase as "precoat" | "printing" | "postcoat")]?.layer_thickness_mm ?? 0) : 0;
  const mismatch = r ? heightMismatch(r.part_height_measured_mm, r.part_height_mm, thickness || 2) : false;
  const ci = cycleIndex(cur, plan);
  const stateCls = r?.state === "fault" ? "fault" : "";
  const label = !status ? "OFFLINE" : isMacro && active ? r!.macro!.replace("_", " ").toUpperCase() : r?.state === "running" ? (r.dry_run ? "DRY RUN" : "PRINTING") : (r?.state ?? "idle").toUpperCase();
  return (
    <section className="view print">
      <div className="run">
        <div className="card-h">Current print{status?.recording.run && <span className="v">{status.recording.run.replace(/^\d{8}_\d{6}_/, "")}</span>}</div>
        <div className="state"><span className={`big ${stateCls}`}>{label}</span><span className="sub">{r?.single_step ? "single-step · " : ""}{c?.heater.on ? "heater ON" : "heater off"}{r?.reason ? ` · ${r.reason}` : ""}</span></div>
        {!isMacro && <div className="layer-no">{r?.layer ?? 0}<small> / {r?.n_layers ?? 0}</small></div>}
        <div className="bar"><i className="layer" style={{ width: `${Math.round(layerFrac * 100)}%` }} /></div>
        <div className="bar-lbl">this layer · {Math.round(layerFrac * 100)}% · {r?.phase || "—"}</div>
        <div className="bar"><i style={{ width: `${r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0}%` }} /></div>
        <div className="bar-lbl">{isMacro ? "macro" : "whole print"} · step {r?.step_index ?? 0} / {r?.n_steps ?? 0}</div>
        <div className="kv">
          <span>elapsed</span><span>{fmtSecs(r?.elapsed_s)}</span>
          <span>remaining (est.)</span><span>{active && remaining !== null ? fmtSecs(remaining) : "—"}</span>
          <span>part height (measured)</span><span className={mismatch ? "warnv" : ""}>{fmtMm(r?.part_height_measured_mm, 2)}</span>
          <span>part height (recipe)</span><span>{fmtMm(r?.part_height_mm, 1)}{mismatch ? " ≠" : ""}</span>
          <span>recording</span><span className={status?.recording.active ? "bad" : ""}>{status?.recording.active ? `● ${status.recording.run}` : "off"}</span>
        </div>
        {mismatch && <div className="warnbox">Measured part height differs from the recipe by more than half a layer: the build piston was moved outside the recipe.</div>}
        <div className="actions">
          {r?.state === "running" && <button className="cta" disabled={!gates.connected} onClick={() => call("pause", api.recipePause)}>❚❚ PAUSE after step</button>}
          {r?.state === "paused" && <button className="cta primary" disabled={!gates.controllable} onClick={() => call("resume", api.recipeResume)}>▶ RESUME</button>}
          {r?.state === "paused" && r.single_step && <button className="cta" disabled={!gates.controllable} onClick={() => call("step", api.recipeStep)}>STEP ▸</button>}
          {active ? <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.recipeAbort)}>■ ABORT</button>
            : <button className="cta primary" onClick={onPrepare}>PREPARE A PRINT →</button>}
        </div>
      </div>

      <div className="machine">
        <div className="card-h">Machine<span className="muted">front elevation · to scale</span></div>
        <Elevation status={status} partExpectedMm={r?.part_height_mm ?? 0} partZeroMm={r?.part_zero_mm ?? null} />
        <div className="narr">
          <span className="tag">now</span><span>{active ? `${isMacro ? r!.macro : `layer ${r!.layer}`} · ${describeStep(cur)}` : c?.state === "fault" ? "faulted — see banner" : gates.connected ? "idle" : "not connected"}</span>
          {next && <><span className="tag">next</span><span className="muted">{describeStep(next)}</span></>}
        </div>
        {!isMacro && <div className="cycle">{CYCLE.map((name, i) => <div key={name} className={ci === i + 1 ? "now" : active && ci > i + 1 ? "done" : ""}>{i + 1} {name}<small>{["piston +t", `recoater → ${plan?.recoater_end_mm ?? "—"}`, "piston −t", `→ ${plan?.recoater_home_mm ?? "—"}`, `→ ${plan?.printhead_end_mm ?? "—"} → home`, `heater ×${plan?.n_heater_passes ?? "—"}`][i]}</small></div>)}</div>}
      </div>

      <div>
        <div className="card-h">Heater<span className={`pill ${c?.heater.on ? "err" : c?.heater.on === null && gates.connected ? "warn" : ""}`}>{c?.heater.on === null ? "unknown" : c?.heater.on ? "ON" : "off"}</span></div>
        <div className="heater">
          <HeaterRing on={c?.heater.on ?? null} onS={c?.heater.on_s ?? 0} maxS={c?.heater.max_on_s ?? 0} />
          <div className="hkv"><span>relay</span><span>{c?.heater.on === null ? "not observed" : c?.heater.on ? "observed ON" : "observed off"}</span><span>commanded</span><span>{c?.heater.commanded_on ? "on" : "off"}</span><span>watchdog</span><span>{fmtSecs(c?.heater.max_on_s)}</span></div>
        </div>
        {c?.heater.on && <div className="actions" style={{ marginTop: 10 }}><button className="cta" onClick={() => call("heater off", api.heaterOff)}>HEATER OFF</button></div>}
        <div className="card-h" style={{ marginTop: 20 }}>Machine I/O</div>
        <IoGrid status={status} pollHz={pollHz} />
        <div className="card-h" style={{ marginTop: 20 }}>Motion</div>
        <div className="hkv">{AXES.map((a) => <span key={`a${a}`} style={{ display: "contents" }}><span>{AXIS_NAMES[a]}</span><span>{fmtMm(c?.telemetry?.positions[String(a)], 1)}{c?.telemetry ? (c.telemetry.motion_complete[String(a)] ? " · idle" : " · moving") : ""}</span></span>)}</div>
      </div>

      <EventLog events={status?.events ?? []} />
    </section>
  );
}
