import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { fmtSecs, type Gates } from "../../lib/format.ts";
import { totalLayers, totalThickness, validate, type PrintSettings } from "../../lib/print_settings.ts";
import type { JobSnap, StatusPayload } from "../../lib/telemetry.ts";
import { CrossSection } from "../CrossSection.tsx";
import { NumberField } from "../NumberField.tsx";
import { Toggle } from "../Toggle.tsx";
import type { Call } from "./types.ts";

type JobRow = Omit<JobSnap, "current_layer">;
const BUDGET = 145;
function num(v: string, fb: number): number { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fb; }

export function JobView({ status, gates, call, onStarted }: { status: StatusPayload | null; gates: Gates; call: Call; onStarted: () => void }) {
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
  const editPh = (ph: "thin_precoat" | "printing" | "postcoat", patch: Partial<PrintSettings["printing"]>) => plan && edit({ [ph]: { ...plan[ph], ...patch } } as Partial<PrintSettings>);
  // Job tab does NOT own the routine-only fields (multipass n_jet_passes, pre_heater_drop_mm) — those
  // live in Routine Parameters. Strip them from every save so navigating Job never clobbers them.
  const jobPatch = (p: PrintSettings): Record<string, unknown> => { const { n_jet_passes: _a, pre_heater_drop_mm: _b, ...rest } = p as unknown as Record<string, unknown>; return rest; };
  const save = async () => { if (!plan) return; await call("save print_settings", () => api.setPrintSettings(jobPatch(plan)).then((r) => { setPlan(r.plan as unknown as PrintSettings); setDirty(false); })); };
  // Persist unsaved edits when leaving the Job tab, so a manual print configured here carries
  // through to Priming and the Print tab without having to hit START PRINT from this page.
  const planRef = useRef<PrintSettings | null>(null); const dirtyRef = useRef(false); const runningRef = useRef(false);
  useEffect(() => { planRef.current = plan; dirtyRef.current = dirty; runningRef.current = running; }, [plan, dirty, running]);
  useEffect(() => () => {
    if (dirtyRef.current && planRef.current && !runningRef.current) {
      api.setPrintSettings(jobPatch(planRef.current)).catch(() => undefined);
    }
  }, []);
  const reasons = plan ? validate(plan) : [];
  const total = plan ? totalThickness(plan) : 0;
  const layers = plan ? totalLayers(plan) : 0;
  const pct = (mm: number) => `${Math.min(100, (100 * mm) / BUDGET)}%`;
  const thin = plan ? plan.thin_precoat.layer_thickness_mm * plan.thin_precoat.n_layers : 0, pr = plan ? plan.printing.layer_thickness_mm * plan.printing.n_layers : 0, post = plan && plan.postcoat_enabled ? plan.postcoat.layer_thickness_mm * plan.postcoat.n_layers : 0;
  // The job dictates the layer COUNT only; the layer thickness is the operator's standard choice, so
  // a thickness difference is NOT a mismatch — only a layer-count difference is.
  const mismatch = job && plan && plan.printing.n_layers !== job.layer_count;
  const LAYER_HEIGHTS = [0.1, 0.15, 0.2];
  const start = async () => {
    if (!plan) return;
    if (dirty) await save();
    if (!dry) {
      const heat = plan.heater_enabled ? "HEATER ON — fires each printing layer" : "⚠ HEATER OFF — no in-situ heating";
      if (!window.confirm(`Start ${job ? job.name : "the manual print"} on the machine?\n\n${heat}\n${layers} layers · ${total.toFixed(1)} mm · ~${fmtSecs(estimateDurationS(plan))}`)) return;
    }
    await call("start", () => api.printStart({ dry_run: dry, single_step: single, name: name || job?.name || "print" }).then(onStarted));
  };
  return (
    <div className="view fixed-page job-view">
      <div className="sec-h">choose a job</div>
      <div className="cards-2">
        <div className="card">
          <h3>sliced jobs<button className="small" onClick={refresh}>rescan</button></h3>
          <div className="hint" style={{ marginTop: 0, marginBottom: 8 }}>{roots.join(" · ") || "no jobs folder configured (vpi-serve --jobs-root)"}</div>
          <div className="job-list">
            {jobs.map((j) => (
              <button key={j.path} className={job?.path === j.path ? "on" : ""} disabled={running} onClick={() => call("select job", () => api.selectJob(j.path))}>
                <span className="n"><span className={`kind ${(j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")) === "2D" ? "k2d" : "k3d"}`} title={(j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")) === "2D" ? "2D RIP print (single layer, multi-pass)" : "3D sliced part"}>{j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")}</span>{j.name}</span><span className="m">{j.layer_count} × {j.layer_height_mm} mm</span>
                <span className="m">{j.folder.slice(0, 8)} {j.folder.slice(9, 11)}:{j.folder.slice(11, 13)} · {j.bbox_mm.x} × {j.bbox_mm.y} × {j.height_mm} mm</span><span className={`m ${j.complete ? "" : "bad"}`}>{j.complete ? `${j.dpi} dpi` : "missing pages"}</span>
              </button>
            ))}
            {jobs.length === 0 && <div className="hint">no job_info.json folders found. Slice a part with the Meteor RIP tool; its hot-folder archive is scanned.</div>}
          </div>
          {job && <div className="row" style={{ marginTop: 10 }}><button className="small" disabled={running} onClick={() => call("clear job", api.clearJob)}>manual print (no job)</button></div>}
        </div>
        <div className="card">
          <h3>{job ? `${job.name} · preview` : "preview"}</h3>
          <CrossSection job={job} layer={preview} />
          {job && <div className="slider"><span>1</span><input type="range" min={1} max={job.layer_count} value={Math.min(preview, job.layer_count)} onChange={(e) => setPreview(Number(e.target.value))} /><span>{job.layer_count}</span><b style={{ color: "var(--fg-strong)" }}>layer {Math.min(preview, job.layer_count)}</b></div>}
        </div>
      </div>

      <div className="sec-h">configure &amp; start</div>
      <div className="cards-2">
        <div className="card">
          <h3>powder stack</h3>
          {plan ? (
            <>
              <div className="stack compact">
                <div className="scale">{[0, 50, 100, 145].map((mm) => <span key={mm} style={{ bottom: pct(mm) }}>{mm}</span>)}</div>
                <div className="col">
                  <div className={total > plan.feed_end_mm ? "over" : "thin"} style={{ bottom: 0, height: pct(thin) }}>{thin > 0 ? `precoat ${thin.toFixed(1)}` : ""}</div>
                  <div className={total > plan.feed_end_mm ? "over" : "lay"} style={{ bottom: pct(thin), height: pct(pr) }}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm}</div>
                  {plan.postcoat_enabled && <div className={total > plan.feed_end_mm ? "over" : "post"} style={{ bottom: pct(thin + pr), height: pct(post) }}>{post > 0 ? `postcoat ${post.toFixed(1)}` : ""}</div>}
                </div>
                <div className="legend" style={{ lineHeight: 1.7, fontSize: 14 }}><b>{total.toFixed(1)} mm</b> of {plan.feed_end_mm}<br /><b>{layers}</b> layers<br />heater <b>{plan.heater_enabled ? `${plan.n_heater_passes}×` : "off"}</b></div>
              </div>
              <div className="fields" style={{ marginTop: 16, maxWidth: "none" }}>
                <span>precoat</span><span className="row"><NumberField value={plan.thin_precoat.n_layers} disabled={running} onChange={(v) => editPh("thin_precoat", { n_layers: v })} style={{ width: 56 }} /> × <NumberField step="0.05" value={plan.thin_precoat.layer_thickness_mm} disabled={running} onChange={(v) => editPh("thin_precoat", { layer_thickness_mm: v })} style={{ width: 72 }} /> mm <span className="hint">(thin precoat — thick precoats now live in Priming)</span></span>
                <span>postcoat</span><label className="row"><Toggle checked={plan.postcoat_enabled} disabled={running} onChange={(v) => edit({ postcoat_enabled: v })} />{plan.postcoat_enabled && <> · <NumberField value={plan.postcoat.n_layers} disabled={running} onChange={(v) => editPh("postcoat", { n_layers: v })} style={{ width: 56 }} /> × <NumberField step="0.05" value={plan.postcoat.layer_thickness_mm} disabled={running} onChange={(v) => editPh("postcoat", { layer_thickness_mm: v })} style={{ width: 72 }} /> mm</>}</label>
                <span>layer height</span><label className="row">
                  <span className="seg">{LAYER_HEIGHTS.map((h) => <button key={h} type="button" className={`small${Math.abs(plan.printing.layer_thickness_mm - h) < 1e-6 ? " on" : ""}`} aria-pressed={Math.abs(plan.printing.layer_thickness_mm - h) < 1e-6} disabled={running} onClick={() => editPh("printing", { layer_thickness_mm: h })}>{h}</button>)}</span>
                  <input type="number" step="0.05" value={plan.printing.layer_thickness_mm} disabled={running} onChange={(e) => editPh("printing", { layer_thickness_mm: num(e.target.value, plan.printing.layer_thickness_mm) })} style={{ width: 72 }} /> mm{job ? <span className="hint" style={{ marginLeft: 6 }}>slicer: {job.layer_height_mm} mm</span> : null}
                </label>
                {!job && <><span>print layers</span><input type="number" value={plan.printing.n_layers} disabled={running} onChange={(e) => editPh("printing", { n_layers: num(e.target.value, plan.printing.n_layers) })} /></>}
                <span>heater</span><label className="row"><Toggle checked={plan.heater_enabled} disabled={running} onChange={(v) => edit({ heater_enabled: v })} /> <span className="hint">fire the IR heater each printing layer,</span> <input type="number" value={plan.n_heater_passes} disabled={running || !plan.heater_enabled} onChange={(e) => edit({ n_heater_passes: num(e.target.value, plan.n_heater_passes) })} style={{ width: 56 }} /> pass(es)</label>
              </div>
              {reasons.length > 0 ? <div className="errline">{reasons.join(" · ")}</div> : <div className="okline">printable</div>}
            </>
          ) : <div className="hint">loading print_settings…</div>}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {job && plan && (
            <div className="card">
              <h3>job → motion</h3>
              <div className="job-map" style={{ marginTop: 0 }}>
                <span>layers</span><span className={mismatch ? "warnv" : ""}>{job.layer_count}{mismatch ? " ≠ print" : ""}</span>
                <span>slicer layer height</span><span>{job.layer_height_mm} mm</span>
                <span>part height</span><span>{job.height_mm} mm</span>
                <span>footprint</span><span>{job.bbox_mm.x} × {job.bbox_mm.y} mm</span>
                <span>print_settings</span><span className={mismatch ? "warnv" : ""}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm} mm{mismatch ? " ≠ job" : ""}</span>
                <span>MetPrint</span><span className="warnv">queue the job's TIFFs in the hot folder (v2 automates this)</span>
              </div>
            </div>
          )}
          <div className="card">
            <h3>start</h3>
            {plan ? (
              <>
                <div className="est" style={{ gridTemplateColumns: "1fr 1fr" }}><div><div className="l">about</div><div className="v" style={{ fontSize: 26 }}>{fmtSecs(estimateDurationS(plan))}</div></div><div><div className="l">layers</div><div className="v" style={{ fontSize: 26 }}>{layers}</div></div></div>
                <div className="chk" style={{ margin: "16px 0" }}>
                  <label><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} /> dry run (motion only — no heat / no jet)</label>
                  <label title="Fires the IR heater during the printing layers (after the precoats). Forced off in a dry run."><Toggle label="heater" danger checked={plan.heater_enabled && !dry} disabled={dry || running} onChange={(v) => edit({ heater_enabled: v })} />{dry ? <span className="hint">&nbsp;(off in dry run)</span> : null}</label>
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
            ) : <div className="hint">loading…</div>}
          </div>
        </div>
      </div>

      <details className="rp-drawer">
        <summary>print_settings · speeds and positions</summary>
        <div className="body">
          {plan ? (
            <div className="fields adv" style={{ marginTop: 0 }}>
              <span>piston speed</span><span className="row"><input type="number" step="0.1" value={plan.printing.part_speed} disabled={running} onChange={(e) => { const s = num(e.target.value, plan.printing.part_speed); const u = (p: PrintSettings["printing"]) => ({ ...p, part_speed: s, feed_speed: s }); edit({ thin_precoat: u(plan.thin_precoat), printing: u(plan.printing), postcoat: u(plan.postcoat) }); }} /> mm/s</span>
              <span>recoater speed</span><span className="row"><input type="number" value={plan.printing.recoater_speed} disabled={running} onChange={(e) => { const s = num(e.target.value, plan.printing.recoater_speed); edit({ thin_precoat: { ...plan.thin_precoat, recoater_speed: s }, printing: { ...plan.printing, recoater_speed: s }, postcoat: { ...plan.postcoat, recoater_speed: s } }); }} /> mm/s</span>
              <span>printhead speed</span><span className="row"><input type="number" value={plan.printing.printhead_speed} disabled={running} onChange={(e) => editPh("printing", { printhead_speed: num(e.target.value, plan.printing.printhead_speed) })} /> mm/s</span>
              <span>heater speed</span><span className="row"><input type="number" value={plan.heater_speed} disabled={running} onChange={(e) => edit({ heater_speed: num(e.target.value, plan.heater_speed) })} /> mm/s</span>
              <span>recoater end</span><span className="row"><input type="number" value={plan.recoater_end_mm} disabled={running} onChange={(e) => edit({ recoater_end_mm: num(e.target.value, plan.recoater_end_mm) })} /> mm</span>
              <span>printhead end</span><span className="row"><input type="number" value={plan.printhead_end_mm} disabled={running} onChange={(e) => edit({ printhead_end_mm: num(e.target.value, plan.printhead_end_mm) })} /> mm</span>
              <span>heater end</span><span className="row"><input type="number" value={plan.heater_end_mm} disabled={running} onChange={(e) => edit({ heater_end_mm: num(e.target.value, plan.heater_end_mm) })} /> mm</span>
              <span>settle</span><span className="row"><input type="number" step="0.1" value={plan.settle_s} disabled={running} onChange={(e) => edit({ settle_s: num(e.target.value, plan.settle_s) })} /> s</span>
            </div>
          ) : <div className="hint">loading…</div>}
        </div>
      </details>
    </div>
  );
}
