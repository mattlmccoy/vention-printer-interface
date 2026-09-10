import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { fmtSecs, type Gates } from "../../lib/format.ts";
import { totalLayers, totalThickness, validate, type PrintSettings } from "../../lib/print_settings.ts";
import type { JobSnap, StatusPayload } from "../../lib/telemetry.ts";
import { CrossSection } from "../CrossSection.tsx";
import { ModuleGrid, type Module } from "../Modules.tsx";
import type { Call } from "./types.ts";

type JobRow = Omit<JobSnap, "current_layer">;
const BUDGET = 145;
function num(v: string, fb: number): number { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fb; }

export function JobView({ status, gates, call, order, sizes, onOrder, onResize, onStarted }: { status: StatusPayload | null; gates: Gates; call: Call; order?: string[]; sizes?: Record<string, import("../../lib/console.ts").ModuleSize>; onOrder: (ids: string[]) => void; onResize: (id: string, size: import("../../lib/console.ts").ModuleSize) => void; onStarted: () => void }) {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [roots, setRoots] = useState<string[]>([]);
  const [plan, setPlan] = useState<PrintSettings | null>(null);
  const [dirty, setDirty] = useState(false);
  const [preview, setPreview] = useState(1);
  const [dry, setDry] = useState(true);
  const [single, setSingle] = useState(false);
  const [name, setName] = useState("");
  const job = status?.job ?? null;
  const running = gates.printActive;
  const refresh = () => { api.jobs().then((r) => { setJobs(r.jobs as JobRow[]); setRoots(r.roots); }).catch(() => undefined); api.printSettings().then((r) => { setPlan(r.plan as unknown as PrintSettings); setDirty(false); }).catch(() => undefined); };
  useEffect(() => { refresh(); }, [gates.reachable, job?.path]);
  const edit = (patch: Partial<PrintSettings>) => plan && (setPlan({ ...plan, ...patch }), setDirty(true));
  const editPh = (ph: "thick_precoat" | "thin_precoat" | "printing" | "postcoat", patch: Partial<PrintSettings["thick_precoat"]>) => plan && edit({ [ph]: { ...plan[ph], ...patch } } as Partial<PrintSettings>);
  const save = async () => { if (!plan) return; await call("save print_settings", () => api.setPrintSettings(plan as unknown as Record<string, unknown>).then((r) => { setPlan(r.plan as unknown as PrintSettings); setDirty(false); })); };
  const reasons = plan ? validate(plan) : [];
  const total = plan ? totalThickness(plan) : 0;
  const layers = plan ? totalLayers(plan) : 0;
  const pct = (mm: number) => `${Math.min(100, (100 * mm) / BUDGET)}%`;
  const pre = plan ? plan.thick_precoat.layer_thickness_mm * plan.thick_precoat.n_layers : 0, thin = plan ? plan.thin_precoat.layer_thickness_mm * plan.thin_precoat.n_layers : 0, pr = plan ? plan.printing.layer_thickness_mm * plan.printing.n_layers : 0, post = plan && plan.postcoat_enabled ? plan.postcoat.layer_thickness_mm * plan.postcoat.n_layers : 0;
  const mismatch = job && plan && (plan.printing.n_layers !== job.layer_count || Math.abs(plan.printing.layer_thickness_mm - job.layer_height_mm) > 1e-6);
  const start = async () => {
    if (!plan) return;
    if (dirty) await save();
    if (!dry && !window.confirm(`Start ${job ? job.name : "the manual print"} on the machine?\n${layers} layers · ${total.toFixed(1)} mm · heater ${plan.heater_enabled ? "ENABLED" : "off"} · about ${fmtSecs(estimateDurationS(plan))}`)) return;
    await call("start", () => api.printStart({ dry_run: dry, single_step: single, name: name || job?.name || "print" }).then(onStarted));
  };
  const modules: Module[] = [
    { id: "pick", title: "sliced jobs", size: "m", node: (
      <>
        <div className="row"><button className="small" onClick={refresh}>rescan</button><span className="hint">{roots.join(" · ") || "no jobs folder configured (vpi-serve --jobs-root)"}</span></div>
        <div className="job-list">
          {jobs.map((j) => (
            <button key={j.path} className={job?.path === j.path ? "on" : ""} disabled={running} onClick={() => call("select job", () => api.selectJob(j.path))}>
              <span className="n">{j.name}</span><span className="m">{j.layer_count} × {j.layer_height_mm} mm</span>
              <span className="m">{j.folder.slice(0, 8)} {j.folder.slice(9, 11)}:{j.folder.slice(11, 13)} · {j.bbox_mm.x} × {j.bbox_mm.y} × {j.height_mm} mm</span><span className={`m ${j.complete ? "" : "bad"}`}>{j.complete ? `${j.dpi} dpi` : "missing pages"}</span>
            </button>
          ))}
          {jobs.length === 0 && <div className="hint">no job_info.json folders found. Slice a part with the Meteor RIP tool; its hot-folder archive is scanned.</div>}
        </div>
        {job && <div className="row" style={{ marginTop: 10 }}><button className="small" disabled={running} onClick={() => call("clear job", api.clearJob)}>manual print (no job)</button></div>}
      </>
    ) },
    { id: "preview", title: job ? `${job.name} · preview` : "preview", size: "l", node: (
      <>
        <CrossSection job={job} layer={preview} />
        {job && <div className="slider"><span>1</span><input type="range" min={1} max={job.layer_count} value={Math.min(preview, job.layer_count)} onChange={(e) => setPreview(Number(e.target.value))} /><span>{job.layer_count}</span><b style={{ color: "var(--fg-strong)" }}>layer {Math.min(preview, job.layer_count)}</b></div>}
      </>
    ) },
    { id: "map", title: "job → motion", size: "s", hidden: !job, node: job && plan ? (
      <div className="job-map" style={{ marginTop: 0 }}>
        <span>layers</span><span>{job.layer_count}</span>
        <span>layer thickness</span><span className={mismatch ? "warnv" : ""}>{job.layer_height_mm} mm</span>
        <span>part height</span><span>{job.height_mm} mm</span>
        <span>footprint</span><span>{job.bbox_mm.x} × {job.bbox_mm.y} mm</span>
        <span>print_settings</span><span className={mismatch ? "warnv" : ""}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm} mm{mismatch ? " ≠ job" : ""}</span>
        <span>MetPrint</span><span className="warnv">queue the job's TIFFs in the hot folder (v2 automates this)</span>
      </div>
    ) : null },
    { id: "stack", title: "powder stack", size: "m", node: plan ? (
      <>
        <div className="stack compact">
          <div className="scale">{[0, 50, 100, 145].map((mm) => <span key={mm} style={{ bottom: pct(mm) }}>{mm}</span>)}</div>
          <div className="col">
            <div className={total > plan.feed_end_mm ? "over" : "pre"} style={{ bottom: 0, height: pct(pre) }}>{pre > 0 ? `precoat ${pre}` : ""}</div>
            <div className={total > plan.feed_end_mm ? "over" : "thin"} style={{ bottom: pct(pre), height: pct(thin) }}>{thin > 0 ? `thin ${thin.toFixed(1)}` : ""}</div>
            <div className={total > plan.feed_end_mm ? "over" : "lay"} style={{ bottom: pct(pre + thin), height: pct(pr) }}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm}</div>
            <div className={total > plan.feed_end_mm ? "over" : "post"} style={{ bottom: pct(pre + thin + pr), height: pct(post) }}>{post > 0 ? `postcoat ${post}` : ""}</div>
          </div>
          <div className="legend" style={{ lineHeight: 1.7, fontSize: 14 }}><b>{total.toFixed(1)} mm</b> of {plan.feed_end_mm}<br /><b>{layers}</b> layers<br />heater <b>{plan.heater_enabled ? `${plan.n_heater_passes}×` : "off"}</b></div>
        </div>
        <div className="fields" style={{ marginTop: 16, maxWidth: "none" }}>
          <span>precoat</span><span className="row"><input type="number" step="0.5" value={pre} disabled={running} onChange={(e) => editPh("thick_precoat", { layer_thickness_mm: num(e.target.value, pre), n_layers: 1 })} /> mm</span>
          <span>postcoat</span><span className="row"><input type="number" step="0.5" value={post} disabled={running} onChange={(e) => editPh("postcoat", { layer_thickness_mm: num(e.target.value, post), n_layers: 1 })} /> mm</span>
          {!job && <><span>print layers</span><input type="number" value={plan.printing.n_layers} disabled={running} onChange={(e) => editPh("printing", { n_layers: num(e.target.value, plan.printing.n_layers) })} />
            <span>layer thickness</span><span className="row"><input type="number" step="0.1" value={plan.printing.layer_thickness_mm} disabled={running} onChange={(e) => editPh("printing", { layer_thickness_mm: num(e.target.value, plan.printing.layer_thickness_mm) })} /> mm</span></>}
          <span>heater</span><label className="row"><input type="checkbox" checked={plan.heater_enabled} disabled={running} onChange={(e) => edit({ heater_enabled: e.target.checked })} /> <b>{plan.heater_enabled ? "ON" : "OFF"}</b> — fire the IR heater each printing layer, <input type="number" value={plan.n_heater_passes} disabled={running || !plan.heater_enabled} onChange={(e) => edit({ n_heater_passes: num(e.target.value, plan.n_heater_passes) })} style={{ width: 56 }} /> pass(es)</label>
        </div>
        {reasons.length > 0 ? <div className="errline">{reasons.join(" · ")}</div> : <div className="okline">printable</div>}
      </>
    ) : <div className="hint">loading print_settings…</div> },
    { id: "start", title: "start", size: "s", node: plan ? (
      <>
        <div className="est" style={{ gridTemplateColumns: "1fr 1fr" }}><div><div className="l">about</div><div className="v" style={{ fontSize: 26 }}>{fmtSecs(estimateDurationS(plan))}</div></div><div><div className="l">layers</div><div className="v" style={{ fontSize: 26 }}>{layers}</div></div></div>
        <div className="chk" style={{ margin: "16px 0" }}>
          <label><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /> dry run (heater off)</label>
          <label><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> single-step</label>
          <label><input type="checkbox" checked={status?.auto_log ?? true} onChange={(e) => call("auto-log", () => api.setAutoLog(e.target.checked))} /> record</label>
        </div>
        <input type="text" placeholder={job?.name ?? "run name"} value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%" }} />
        <div className="actions one tight">
          <button className={`cta ${dry ? "" : "primary"}`} disabled={!gates.controllable || reasons.length > 0 || running} onClick={start}>{dry ? "START DRY RUN" : "START PRINT"}</button>
          {dirty && <button className="cta" disabled={running} onClick={save}>SAVE CHANGES</button>}
        </div>
        {!gates.controllable && <div className="lock">{gates.connected ? "read-only · take control from the connection pill" : "connect a controller to start"}</div>}
      </>
    ) : null },
    { id: "advanced", title: "print_settings · speeds and positions", size: "m", node: plan ? (
      <div className="fields adv" style={{ marginTop: 0 }}>
        <span>piston speed</span><span className="row"><input type="number" step="0.1" value={plan.printing.part_speed} disabled={running} onChange={(e) => { const s = num(e.target.value, plan.printing.part_speed); const u = (p: PrintSettings["thick_precoat"]) => ({ ...p, part_speed: s, feed_speed: s }); edit({ thick_precoat: u(plan.thick_precoat), thin_precoat: u(plan.thin_precoat), printing: u(plan.printing), postcoat: u(plan.postcoat) }); }} /> mm/s</span>
        <span>recoater speed</span><span className="row"><input type="number" value={plan.printing.recoater_speed} disabled={running} onChange={(e) => { const s = num(e.target.value, plan.printing.recoater_speed); edit({ thick_precoat: { ...plan.thick_precoat, recoater_speed: s }, thin_precoat: { ...plan.thin_precoat, recoater_speed: s }, printing: { ...plan.printing, recoater_speed: s }, postcoat: { ...plan.postcoat, recoater_speed: s } }); }} /> mm/s</span>
        <span>printhead speed</span><span className="row"><input type="number" value={plan.printing.printhead_speed} disabled={running} onChange={(e) => editPh("printing", { printhead_speed: num(e.target.value, plan.printing.printhead_speed) })} /> mm/s</span>
        <span>heater speed</span><span className="row"><input type="number" value={plan.heater_speed} disabled={running} onChange={(e) => edit({ heater_speed: num(e.target.value, plan.heater_speed) })} /> mm/s</span>
        <span>recoater end</span><span className="row"><input type="number" value={plan.recoater_end_mm} disabled={running} onChange={(e) => edit({ recoater_end_mm: num(e.target.value, plan.recoater_end_mm) })} /> mm</span>
        <span>printhead end</span><span className="row"><input type="number" value={plan.printhead_end_mm} disabled={running} onChange={(e) => edit({ printhead_end_mm: num(e.target.value, plan.printhead_end_mm) })} /> mm</span>
        <span>heater end</span><span className="row"><input type="number" value={plan.heater_end_mm} disabled={running} onChange={(e) => edit({ heater_end_mm: num(e.target.value, plan.heater_end_mm) })} /> mm</span>
        <span>settle</span><span className="row"><input type="number" step="0.1" value={plan.settle_s} disabled={running} onChange={(e) => edit({ settle_s: num(e.target.value, plan.settle_s) })} /> s</span>
      </div>
    ) : null },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} sizes={sizes} onOrder={onOrder} onResize={onResize} /></div>;
}
