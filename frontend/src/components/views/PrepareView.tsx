import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import { estimateDurationS, heaterOnTimeS } from "../../lib/estimate.ts";
import { fmtSecs, type Gates } from "../../lib/format.ts";
import { PHASES, compileRecipe, totalLayers, totalThickness, validate, type PhasePlan, type RecipePlan } from "../../lib/recipe.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import type { Call } from "./types.ts";

const BUDGET = 145;
function num(v: string, fb: number): number { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fb; }

export function PrepareView({ status, gates, call, onStarted }: { status: StatusPayload | null; gates: Gates; call: Call; onStarted: () => void }) {
  const [plan, setPlan] = useState<RecipePlan | null>(null);
  const [serverValidation, setServerValidation] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [dry, setDry] = useState(true);
  const [single, setSingle] = useState(false);
  const [name, setName] = useState("print");
  const [notes, setNotes] = useState("");
  const load = () => api.recipe().then((r) => { setPlan(r.plan as unknown as RecipePlan); setServerValidation(r.validation); setDirty(false); }).catch(() => undefined);
  useEffect(() => { load(); }, [gates.reachable]);
  const running = gates.recipeActive;
  if (!plan) return <section className="view prepare"><div><div className="hint">{gates.reachable ? "loading recipe…" : "operator unreachable"}</div></div></section>;
  const reasons = validate(plan);
  const total = totalThickness(plan);
  const layers = totalLayers(plan);
  const over = total > plan.feed_end_mm;
  const pct = (mm: number) => `${Math.min(100, (100 * mm) / BUDGET)}%`;
  const setPhase = (ph: (typeof PHASES)[number], k: keyof PhasePlan, v: string) => { setPlan({ ...plan, [ph]: { ...plan[ph], [k]: num(v, plan[ph][k]) } }); setDirty(true); };
  const setField = (k: keyof RecipePlan, v: string | boolean) => { setPlan({ ...plan, [k]: typeof v === "boolean" ? v : num(v, plan[k] as number) }); setDirty(true); };
  const save = async () => { await call("save recipe", () => api.setRecipe(plan as unknown as Record<string, unknown>).then((r) => { setPlan(r.plan as unknown as RecipePlan); setServerValidation(r.validation); setDirty(false); })); };
  const start = async () => {
    if (dirty) await save();
    if (!dry && !window.confirm(`Start the print on the machine?\n${compileRecipe(plan).length} steps · ${layers} layers · ${total.toFixed(1)} mm\nheater ${plan.heater_enabled ? "ENABLED" : "disabled"} · est. ${fmtSecs(estimateDurationS(plan))}`)) return;
    await call("start", () => api.recipeStart({ dry_run: dry, single_step: single, name, notes }).then(onStarted));
  };
  const precoatH = plan.precoat.layer_thickness_mm * plan.precoat.n_layers;
  const printH = plan.printing.layer_thickness_mm * plan.printing.n_layers;
  const postH = plan.postcoat.layer_thickness_mm * plan.postcoat.n_layers;
  return (
    <section className="view prepare">
      <div>
        <div className="card-h">Layer stack<span className="muted">powder budget {BUDGET} mm (feed travel) · feed end {plan.feed_end_mm} mm</span></div>
        <div className="stack">
          <div className="scale">{[0, 25, 50, 75, 100].map((p) => <span key={p} style={{ bottom: `${p}%` }}>{Math.round((BUDGET * p) / 100)}</span>)}</div>
          <div className="col">
            <div className={over ? "over" : "pre"} style={{ bottom: 0, height: pct(precoatH) }}>{precoatH > 0 ? `precoat ${precoatH} mm` : ""}</div>
            <div className={over ? "over" : "lay"} style={{ bottom: pct(precoatH), height: pct(printH) }}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm} mm</div>
            <div className={over ? "over" : "post"} style={{ bottom: pct(precoatH + printH), height: pct(postH) }}>{postH > 0 ? `postcoat ${postH} mm` : ""}</div>
            <div style={{ bottom: pct(plan.feed_end_mm), height: 0, borderTop: "2px dashed var(--err)", background: "none", left: -6, right: -6 }} />
          </div>
          <div className="legend">
            total <b>{total.toFixed(1)} mm</b> of {plan.feed_end_mm} mm<br />layers <b>{layers}</b> ({plan.precoat.n_layers} + {plan.printing.n_layers} + {plan.postcoat.n_layers})<br />
            heater <b>{plan.heater_enabled ? `${plan.n_heater_passes} pass${plan.n_heater_passes === 1 ? "" : "es"} / layer · ${plan.heater_end_mm} mm` : "disabled"}</b><br />
            estimated <b>{fmtSecs(estimateDurationS(plan))}</b><br />printability <b style={{ color: reasons.length ? "var(--err)" : "var(--live)" }}>{reasons.length ? "NOT printable" : "ok"}</b>
          </div>
        </div>
        <div className="form">
          <span /><span className="h">precoat</span><span className="h">print</span><span className="h">postcoat</span>
          <span>layer thickness mm</span>{PHASES.map((ph) => <input key={ph} type="number" step="0.1" value={plan[ph].layer_thickness_mm} disabled={running} onChange={(e) => setPhase(ph, "layer_thickness_mm", e.target.value)} />)}
          <span>layers</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].n_layers} disabled={running} onChange={(e) => setPhase(ph, "n_layers", e.target.value)} />)}
          <span>piston speed mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" step="0.1" value={plan[ph].part_speed} disabled={running} onChange={(e) => { setPhase(ph, "part_speed", e.target.value); setPhase(ph, "feed_speed", e.target.value); }} />)}
          <span>recoater speed mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].recoater_speed} disabled={running} onChange={(e) => setPhase(ph, "recoater_speed", e.target.value)} />)}
          <span>printhead speed mm/s</span>{PHASES.map((ph) => <input key={ph} type="number" value={plan[ph].printhead_speed} disabled={running || ph !== "printing"} onChange={(e) => setPhase(ph, "printhead_speed", e.target.value)} />)}
        </div>
        <div className="form two">
          <span>heater passes / layer</span><input type="number" value={plan.n_heater_passes} disabled={running} onChange={(e) => setField("n_heater_passes", e.target.value)} />
          <span>heater speed mm/s</span><input type="number" value={plan.heater_speed} disabled={running} onChange={(e) => setField("heater_speed", e.target.value)} />
          <span>heater end mm</span><input type="number" value={plan.heater_end_mm} disabled={running} onChange={(e) => setField("heater_end_mm", e.target.value)} />
          <span>settle after feed s</span><input type="number" step="0.1" value={plan.settle_s} disabled={running} onChange={(e) => setField("settle_s", e.target.value)} />
          <span>recoater end mm</span><input type="number" value={plan.recoater_end_mm} disabled={running} onChange={(e) => setField("recoater_end_mm", e.target.value)} />
          <span>printhead end mm</span><input type="number" value={plan.printhead_end_mm} disabled={running} onChange={(e) => setField("printhead_end_mm", e.target.value)} />
          <span>feed end mm</span><input type="number" value={plan.feed_end_mm} disabled={running} onChange={(e) => setField("feed_end_mm", e.target.value)} />
          <span>heater enabled</span><label className="hint"><input type="checkbox" checked={plan.heater_enabled} disabled={running} onChange={(e) => setField("heater_enabled", e.target.checked)} /> switch the relay during dry passes</label>
        </div>
        {reasons.length > 0 ? <div className="errbox">{reasons.map((x) => <div key={x}>{x}</div>)}</div> : <div className="okbox">Printable · every position inside travel{serverValidation.length ? ` · server: ${serverValidation.join("; ")}` : ""}</div>}
      </div>
      <div>
        <div className="card-h">Run this job{dirty && <span className="pill warn">unsaved</span>}</div>
        <div className="est">
          <div><div className="l">estimated duration</div><div className="v">{fmtSecs(estimateDurationS(plan))}</div></div>
          <div><div className="l">steps</div><div className="v">{compileRecipe(plan).length}</div></div>
          <div><div className="l">powder used</div><div className="v">{total.toFixed(0)} <small>mm</small></div></div>
          <div><div className="l">heater on-time</div><div className="v">{plan.heater_enabled ? fmtSecs(heaterOnTimeS(plan)) : "0"}</div></div>
        </div>
        <div className="chk">
          <label><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /> dry run (no heater)</label>
          <label><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> single-step</label>
          <label><input type="checkbox" checked={status?.auto_log ?? true} onChange={(e) => call("auto-log", () => api.setAutoLog(e.target.checked))} /> record run</label>
        </div>
        <div className="form two" style={{ gridTemplateColumns: "auto 1fr" }}><span>run name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} /><span>notes</span><input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        <div className="actions">
          <button className="cta" disabled={running || !dirty} onClick={save}>save plan</button>
          <button className={`cta ${dry ? "" : "primary"}`} disabled={!gates.controllable || reasons.length > 0 || running} onClick={start}>{dry ? "▶ START DRY RUN" : "▶ START PRINT"}</button>
        </div>
        {!gates.controllable && <div className="lock">{gates.connected ? "ARM in the top bar to start" : "connect a controller to start"}</div>}
        <div className="card-h" style={{ marginTop: 22 }}>Sliced job<span className="muted">v2</span></div>
        <div className="lock">import a MetPrint TIFF stack to set layer count and thickness</div>
      </div>
    </section>
  );
}
