import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { fmtSecs, type Gates } from "../../lib/format.ts";
import { compileRecipe, totalLayers, totalThickness, validate, type RecipePlan } from "../../lib/recipe.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import type { Call } from "./types.ts";

const BUDGET = 145;
function num(v: string, fb: number): number { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fb; }

export function PrepareView({ status, gates, call, onStarted }: { status: StatusPayload | null; gates: Gates; call: Call; onStarted: () => void }) {
  const [plan, setPlan] = useState<RecipePlan | null>(null);
  const [dirty, setDirty] = useState(false);
  const [dry, setDry] = useState(true);
  const [single, setSingle] = useState(false);
  const [name, setName] = useState("print");
  useEffect(() => { api.recipe().then((r) => { setPlan(r.plan as unknown as RecipePlan); setDirty(false); }).catch(() => undefined); }, [gates.reachable]);
  const running = gates.recipeActive;
  if (!plan) return <section className="view prepare"><div><div className="hint">{gates.reachable ? "loading recipe…" : "operator unreachable"}</div></div></section>;
  const reasons = validate(plan);
  const total = totalThickness(plan);
  const layers = totalLayers(plan);
  const over = total > plan.feed_end_mm;
  const pct = (mm: number) => `${Math.min(100, (100 * mm) / BUDGET)}%`;
  const edit = (patch: Partial<RecipePlan>) => { setPlan({ ...plan, ...patch }); setDirty(true); };
  const editPh = (ph: "precoat" | "printing" | "postcoat", patch: Partial<RecipePlan["precoat"]>) => edit({ [ph]: { ...plan[ph], ...patch } } as Partial<RecipePlan>);
  const save = async () => { await call("save recipe", () => api.setRecipe(plan as unknown as Record<string, unknown>).then((r) => { setPlan(r.plan as unknown as RecipePlan); setDirty(false); })); };
  const start = async () => {
    if (dirty) await save();
    if (!dry && !window.confirm(`Start the print on the machine?\n${layers} layers · ${total.toFixed(1)} mm · heater ${plan.heater_enabled ? "ENABLED" : "off"} · about ${fmtSecs(estimateDurationS(plan))}`)) return;
    await call("start", () => api.recipeStart({ dry_run: dry, single_step: single, name }).then(onStarted));
  };
  const pre = plan.precoat.layer_thickness_mm * plan.precoat.n_layers, pr = plan.printing.layer_thickness_mm * plan.printing.n_layers, post = plan.postcoat.layer_thickness_mm * plan.postcoat.n_layers;
  const speedAll = (v: string) => { const s = num(v, plan.printing.recoater_speed); edit({ precoat: { ...plan.precoat, recoater_speed: s }, printing: { ...plan.printing, recoater_speed: s }, postcoat: { ...plan.postcoat, recoater_speed: s } }); };
  const pistonAll = (v: string) => { const s = num(v, plan.printing.part_speed); const u = (p: RecipePlan["precoat"]) => ({ ...p, part_speed: s, feed_speed: s }); edit({ precoat: u(plan.precoat), printing: u(plan.printing), postcoat: u(plan.postcoat) }); };
  return (
    <section className="view prepare">
      <div>
        <div className="h">Layer stack</div>
        <div className="stack">
          <div className="scale">{[0, 50, 100, 145].map((mm) => <span key={mm} style={{ bottom: pct(mm) }}>{mm}</span>)}</div>
          <div className="col">
            <div className={over ? "over" : "pre"} style={{ bottom: 0, height: pct(pre) }}>{pre > 0 ? `precoat ${pre}` : ""}</div>
            <div className={over ? "over" : "lay"} style={{ bottom: pct(pre), height: pct(pr) }}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm} mm</div>
            <div className={over ? "over" : "post"} style={{ bottom: pct(pre + pr), height: pct(post) }}>{post > 0 ? `postcoat ${post}` : ""}</div>
          </div>
          <div className="legend">
            <b>{total.toFixed(1)} mm</b> of {plan.feed_end_mm} mm powder<br /><b>{layers}</b> layers<br />heater <b>{plan.heater_enabled ? `${plan.n_heater_passes} pass${plan.n_heater_passes === 1 ? "" : "es"} per layer` : "off"}</b>
          </div>
        </div>
        <div className="fields">
          <span>layer thickness</span><span className="row"><input type="number" step="0.1" value={plan.printing.layer_thickness_mm} disabled={running} onChange={(e) => editPh("printing", { layer_thickness_mm: num(e.target.value, plan.printing.layer_thickness_mm) })} /> mm</span>
          <span>print layers</span><input type="number" value={plan.printing.n_layers} disabled={running} onChange={(e) => editPh("printing", { n_layers: num(e.target.value, plan.printing.n_layers) })} />
          <span>precoat</span><span className="row"><input type="number" step="0.5" value={pre} disabled={running} onChange={(e) => editPh("precoat", { layer_thickness_mm: num(e.target.value, pre), n_layers: 1 })} /> mm</span>
          <span>postcoat</span><span className="row"><input type="number" step="0.5" value={post} disabled={running} onChange={(e) => editPh("postcoat", { layer_thickness_mm: num(e.target.value, post), n_layers: 1 })} /> mm</span>
          <span>heater</span><label className="row"><input type="checkbox" checked={plan.heater_enabled} disabled={running} onChange={(e) => edit({ heater_enabled: e.target.checked })} /> dry each layer with <input type="number" value={plan.n_heater_passes} disabled={running || !plan.heater_enabled} onChange={(e) => edit({ n_heater_passes: num(e.target.value, plan.n_heater_passes) })} style={{ width: 64 }} /> pass(es)</label>
        </div>
        {reasons.length > 0 ? <div className="errline">{reasons.join(" · ")}</div> : <div className="okline">Printable</div>}
        <details>
          <summary>Advanced</summary>
          <div className="body fields adv">
            <span>piston speed</span><span className="row"><input type="number" step="0.1" value={plan.printing.part_speed} disabled={running} onChange={(e) => pistonAll(e.target.value)} /> mm/s</span>
            <span>recoater speed</span><span className="row"><input type="number" value={plan.printing.recoater_speed} disabled={running} onChange={(e) => speedAll(e.target.value)} /> mm/s</span>
            <span>printhead speed</span><span className="row"><input type="number" value={plan.printing.printhead_speed} disabled={running} onChange={(e) => editPh("printing", { printhead_speed: num(e.target.value, plan.printing.printhead_speed) })} /> mm/s</span>
            <span>heater speed</span><span className="row"><input type="number" value={plan.heater_speed} disabled={running} onChange={(e) => edit({ heater_speed: num(e.target.value, plan.heater_speed) })} /> mm/s</span>
            <span>recoater end</span><span className="row"><input type="number" value={plan.recoater_end_mm} disabled={running} onChange={(e) => edit({ recoater_end_mm: num(e.target.value, plan.recoater_end_mm) })} /> mm</span>
            <span>printhead end</span><span className="row"><input type="number" value={plan.printhead_end_mm} disabled={running} onChange={(e) => edit({ printhead_end_mm: num(e.target.value, plan.printhead_end_mm) })} /> mm</span>
            <span>heater end</span><span className="row"><input type="number" value={plan.heater_end_mm} disabled={running} onChange={(e) => edit({ heater_end_mm: num(e.target.value, plan.heater_end_mm) })} /> mm</span>
            <span>feed end</span><span className="row"><input type="number" value={plan.feed_end_mm} disabled={running} onChange={(e) => edit({ feed_end_mm: num(e.target.value, plan.feed_end_mm) })} /> mm</span>
            <span>settle after feed</span><span className="row"><input type="number" step="0.1" value={plan.settle_s} disabled={running} onChange={(e) => edit({ settle_s: num(e.target.value, plan.settle_s) })} /> s</span>
          </div>
        </details>
      </div>
      <div className="side">
        <div className="est"><div><div className="l">about</div><div className="v">{fmtSecs(estimateDurationS(plan))}</div></div><div><div className="l">steps</div><div className="v">{compileRecipe(plan).length}</div></div></div>
        <div className="chk">
          <label><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /> dry run — motion only, heater stays off</label>
          <label><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> single-step — pause after every move</label>
          <label><input type="checkbox" checked={status?.auto_log ?? true} onChange={(e) => call("auto-log", () => api.setAutoLog(e.target.checked))} /> record the run</label>
        </div>
        <div className="fields" style={{ marginTop: 0 }}><span>name</span><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="actions one">
          <button className={`cta ${dry ? "" : "primary"}`} disabled={!gates.controllable || reasons.length > 0 || running} onClick={start}>{dry ? "START DRY RUN" : "START PRINT"}</button>
          {dirty && <button className="cta" disabled={running} onClick={save}>SAVE CHANGES</button>}
        </div>
        {!gates.controllable && <div className="lock">{gates.connected ? "ARM in the top bar to start" : "connect a controller to start"}</div>}
      </div>
    </section>
  );
}
