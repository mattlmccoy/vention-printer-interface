import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../lib/api.ts";
import { fmtMm, fmtSecs, heightMismatch, type Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { compilePrint, describeStep, totalLayers, totalThickness, validate, type PrintSettings } from "../../lib/print_settings.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { CrossSection } from "../CrossSection.tsx";
import { RoutinePanel } from "../RoutinePanel.tsx";
import { NumberField } from "../NumberField.tsx";
import { Toggle } from "../Toggle.tsx";
import { parseCaptures, type Capture } from "../../lib/vision.ts";
import { layerAccuracySummary, parseLayerAccuracy, type LayerAccuracy } from "../../lib/motion.ts";
import { LAYER_HEIGHTS_MM, snapLayerHeightMm } from "../../lib/layer_height.ts";
import type { Call } from "./types.ts";

const CMP_STAGES = ["pre_jet", "post_jet", "post_heat"] as const;
const CMP_STAGE_LABEL: Record<string, string> = { pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat" };

const LAYER_HEIGHTS = LAYER_HEIGHTS_MM;
const PHASE_LABEL: Record<string, string> = { thin_precoat: "precoat", printing: "printing", postcoat: "postcoat", setup: "setup", finish: "finishing" };
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

export function PrintView({ status, gates, call, base, onJob, onRuns }: { status: StatusPayload | null; gates: Gates; call: Call; base: string; onJob: () => void; onRuns: () => void }) {
  const c = status?.controller;
  const r = status?.print;
  const t = c?.telemetry ?? null;
  const job = status?.job ?? null;
  const plan = (r?.plan as unknown as PrintSettings | null) ?? null;
  const steps = plan ? compilePrint(plan) : [];
  const active = !!r && (r.state === "running" || r.state === "paused");
  const paused = r?.state === "paused";
  const isMacro = !!r?.macro;

  // science-cam stills for the running recording, polled so the CAD-vs-actual compare fills in live.
  const recRun = status?.recording.run ?? null;
  const [caps, setCaps] = useState<Capture[]>([]);
  const [cmpStage, setCmpStage] = useState<string>("post_jet");
  useEffect(() => {
    if (!recRun) { setCaps([]); return; }
    let live = true;
    const load = () => api.visionCaptures(recRun).then((rc) => { if (live) setCaps(parseCaptures(rc)); }).catch(() => undefined);
    load();
    const id = window.setInterval(load, 4000);
    return () => { live = false; window.clearInterval(id); };
  }, [recRun]);

  // ---- manual print (idle, no sliced job): reuses print-settings edit/save + api.printStart.
  const showManual = !active && !job;
  const [mplan, setMplan] = useState<PrintSettings | null>(null);
  const [mdirty, setMdirty] = useState(false);
  const [mdry, setMdry] = useState(true);
  const [msingle, setMsingle] = useState(false);
  useEffect(() => {
    if (!showManual) return;
    let live = true;
    api.printSettings().then((x) => { if (live) { setMplan(x.plan as unknown as PrintSettings); setMdirty(false); } }).catch(() => undefined);
    return () => { live = false; };
  }, [showManual, gates.reachable]);
  const medit = (patch: Partial<PrintSettings>) => mplan && (setMplan({ ...mplan, ...patch }), setMdirty(true));
  const meditPrinting = (patch: Partial<PrintSettings["printing"]>) => mplan && medit({ printing: { ...mplan.printing, ...patch } });
  // Send ONLY the fields this form owns (backend deep-merges one level) so routine fields set
  // elsewhere (n_jet_passes, pre_heater_drop_mm) are never clobbered.
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
  // Only meaningful while printing: at finish the part is driven to part_max, so the measured
  // displacement no longer tracks the layer height.
  const mismatch = active && r ? heightMismatch(r.part_height_measured_mm, r.part_height_mm, thickness) : false;
  const printLayer = r && r.phase === "printing" ? r.layer - (plan?.thin_precoat.n_layers ?? 0) : 0;
  const shownLayer = active && printLayer > 0 ? printLayer : (job ? 1 : 0);

  // Finish summary: shown when a print ends. Build-piston accuracy is pulled from the just-finished
  // run's layer_accuracy.csv (newest recording); a dry run has no meaningful accuracy.
  const finished = r?.state === "done" || r?.state === "aborted" || r?.state === "fault";
  const [finishRows, setFinishRows] = useState<LayerAccuracy[] | null>(null);
  const [accuracyLoading, setAccuracyLoading] = useState(false);
  useEffect(() => {
    if (!finished || r?.dry_run) { setFinishRows(null); setAccuracyLoading(false); return; }
    let live = true;
    setAccuracyLoading(true);
    (async () => {
      try {
        const { runs } = await api.recordings();
        const newest = runs.length ? runs[runs.length - 1] : null;
        const csv = newest ? await api.recordingFileText(newest.run, "layer_accuracy.csv") : "";
        if (live) setFinishRows(csv ? parseLayerAccuracy(csv) : null);
      } catch {
        if (live) setFinishRows(null);
      } finally {
        if (live) setAccuracyLoading(false);
      }
    })();
    return () => { live = false; };
  }, [finished, r?.dry_run, r?.state]);
  const pct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;
  const label = !status ? "OFFLINE" : isMacro && active ? r!.macro!.replace("_", " ").toUpperCase() : r?.state === "running" ? (r.dry_run ? "DRY RUN" : "PRINTING") : r?.state === "paused" ? "PAUSED" : (r?.state ?? "idle").toUpperCase();
  const stagePh = plan && r ? plan[r.phase as "thin_precoat" | "printing" | "postcoat"] : undefined;
  const stageOffset = plan && r ? (r.phase === "printing" ? plan.thin_precoat.n_layers : r.phase === "postcoat" ? plan.thin_precoat.n_layers + plan.printing.n_layers : 0) : 0;
  const stageStep = r ? Math.max(1, r.layer - stageOffset) : 0;
  const stageName = r ? (PHASE_LABEL[r.phase] ?? r.phase) : "";
  const stageLine = !isMacro && r?.state === "done" ? "complete" : (!isMacro && active && stageName) ? `${stageName}${stagePh ? ` · ${stageStep}/${stagePh.n_layers} · ${stagePh.layer_thickness_mm} mm` : ""}` : "";
  const problems: Array<[string, "bad" | "warn"]> = [];
  if (t?.estop_triggered) problems.push(["e-stop asserted", "bad"]);
  if (t?.estop_triggered === null && gates.connected) problems.push(["e-stop status unknown", "warn"]);
  if (t?.drives_ready === false) problems.push(["drives not ready", "bad"]);
  if (t && !t.health_ok) problems.push(["controller health bad", "bad"]);
  if (c?.read_error) problems.push(["telemetry read error", "bad"]);
  if (job && !job.complete) problems.push([`job missing pages ${job.missing_pages.slice(0, 5).join(", ")}`, "bad"]);

  // ---- timeline rows (meaningful actions), grouped by phase/layer; jump-to-step while paused.
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

  const stateCls = r?.state === "fault" ? "fault" : active ? "run" : "idle";
  const shownCap = caps.find((c) => c.layer === shownLayer && c.stage === cmpStage) ?? null;
  const layerHasCaps = caps.some((c) => c.layer === shownLayer);
  const imaging = (
    <div className="card imaging-card">
      <h3>{job ? `${job.name} · layer ${shownLayer}${job.layer_count ? ` of ${job.layer_count}` : ""}` : "layer"}
        {layerHasCaps && <span className="seg sm">{CMP_STAGES.map((s) => <button key={s} type="button" className={cmpStage === s ? "on" : ""} onClick={() => setCmpStage(s)}>{CMP_STAGE_LABEL[s]}</button>)}</span>}
      </h3>
      {shownCap ? (
        <div className="compare-2">
          <div className="cmp"><div className="cmp-h">CAD slice</div><CrossSection job={job} layer={shownLayer} /></div>
          <div className="cmp"><div className="cmp-h">science cam · {CMP_STAGE_LABEL[cmpStage]}</div><img className="cam-panel-img cmp-img" src={`${base}${shownCap.url}`} alt={`science cam layer ${shownLayer} ${cmpStage}`} onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} /></div>
        </div>
      ) : (
        <>
          <CrossSection job={job} layer={shownLayer} />
          <div className="hint" style={{ marginTop: 10 }}>The science-cam still appears here beside the CAD slice once the science camera captures this layer/stage (during a recorded print).</div>
        </>
      )}
      <div className="bar" style={{ marginTop: 12 }}><i className="layer" style={{ width: `${job && job.layer_count ? Math.round((100 * (active ? Math.max(printLayer - 1, 0) : 0)) / job.layer_count) : 0}%` }} /></div>
      <div className="bar-lbl">{job ? `${active ? Math.max(printLayer - 1, 0) : 0} of ${job.layer_count} layers printed` : "no job selected"}</div>
    </div>
  );
  const timeline = timelineRows.length > 0 ? (
    <div className="card timeline-card">
      <h3>timeline<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>{paused ? "click a step to jump" : "pause to jump"}</span></h3>
      <div className="timeline">{timelineNodes}</div>
    </div>
  ) : null;

  return (
    <div className="view print-view">
      {/* command strip — state, progress, primary actions (always) */}
      <div className="cmdbar">
        <span className={`state-pill ${stateCls}`}>{label}</span>
        <span className="cmd-name">{job ? job.name : "manual print"}</span>
        {stageLine && <span className="stage-badge">{stageLine}</span>}
        {active && (
          <div className="cmd-prog">
            <div className="bar" style={{ margin: 0 }}><i style={{ width: `${pct}%` }} /></div>
            <div className="bar-lbl" style={{ marginTop: 4 }}>{pct}% · step {r?.step_index ?? 0} of {r?.n_steps ?? 0}{remaining !== null ? ` · ~${fmtSecs(remaining)} left` : ""}</div>
          </div>
        )}
        <span className="spacer" />
        <div className="cmd-actions">
          {r?.state === "running" && <button className="cta sm danger" disabled={!gates.connected} onClick={() => call("pause", api.printPause)}>PAUSE</button>}
          {r?.state === "paused" && <button className="cta sm primary" disabled={!gates.controllable} onClick={() => call(r.single_step ? "step" : "resume", r.single_step ? api.printStep : api.printResume)}>{r.single_step ? "NEXT STEP" : "RESUME"}</button>}
          {active
            ? <button className="cta sm danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
            : <button className="cta sm primary" onClick={onJob}>{job ? "START THIS JOB" : "CHOOSE A JOB"}</button>}
        </div>
      </div>

      {(problems.length > 0 || mismatch) && (
        <div className="chips">{problems.map(([txt, cls]) => <span key={txt} className={`chip ${cls}`}>{txt}</span>)}{mismatch && <span className="chip warn">part height differs from print_settings ({fmtMm(r?.part_height_mm, 1)})</span>}</div>
      )}

      {finished && r && (() => {
        const label2 = r.state === "done" ? "PRINT COMPLETE" : r.state === "aborted" ? "PRINT ABORTED" : "PRINT FAULTED";
        const cls = r.state === "done" ? "done" : "bad";
        const layersDone = r.state === "done" ? r.n_layers : r.layer;
        const acc = finishRows ? layerAccuracySummary(finishRows) : null;
        const hasAcc = acc !== null && acc.n > 0;
        // Measured height = the last known settled build-piston displacement from the run (NOT live
        // status, which reads part_max after the finish move). Commanded = the compiled height.
        const measuredRows = (finishRows ?? []).filter((x) => x.actual_cum_mm != null);
        const measuredFinal = measuredRows.length ? (measuredRows.at(-1)!.actual_cum_mm as number) : null;
        const dHeight = measuredFinal != null ? measuredFinal - r.part_height_mm : null;
        const accCell = hasAcc ? `${acc!.meanAbsDevMm!.toFixed(3)} mm` : r.dry_run ? "n/a" : accuracyLoading ? "…" : "—";
        return (
          <div className={`card finish-card ${cls}`}>
            <div className="finish-head">
              <span className={`state-pill ${cls === "done" ? "run" : "fault"}`}>{label2}</span>
              <span className="cmd-name">{job ? job.name : "manual print"}{r.dry_run ? " · dry run" : ""}</span>
              <span className="spacer" />
              <button className="cta sm" onClick={onRuns}>View in Runs →</button>
              <button className="cta sm primary" onClick={onJob}>{job ? "Print again" : "New print"}</button>
            </div>
            {r.state === "aborted" && r.reason ? <div className="finish-reason">stopped: {r.reason}</div> : null}
            <div className="finish-stats">
              <div className="fstat"><b>{layersDone}<small> / {r.n_layers}</small></b><span>layers</span></div>
              <div className="fstat"><b>{fmtSecs(r.elapsed_s)}</b><span>duration</span></div>
              <div className="fstat"><b>{fmtMm(r.part_height_mm, 2)}</b><span>commanded height</span></div>
              <div className="fstat"><b>{measuredFinal != null ? fmtMm(measuredFinal, 2) : (r.dry_run ? "n/a" : "—")}</b><span>measured height</span></div>
              <div className="fstat"><b>{dHeight != null ? `${dHeight >= 0 ? "+" : ""}${dHeight.toFixed(2)} mm` : "—"}</b><span>height Δ (meas − cmd)</span></div>
              <div className="fstat"><b>{accCell}</b><span>build-piston mean |dev|{hasAcc ? ` · n=${acc!.n}` : ""}</span></div>
              <div className="fstat"><b>{hasAcc ? `${acc!.maxAbsDevMm!.toFixed(3)} mm` : "—"}</b><span>max |dev|{hasAcc && acc!.maxLayer != null ? ` · layer ${acc!.maxLayer}` : ""}</span></div>
            </div>
            {!hasAcc && !r.dry_run && !accuracyLoading ? <div className="hint" style={{ marginTop: 10 }}>Per-layer build-piston accuracy appears here from the recorded run (needs telemetry during the print).</div> : null}
          </div>
        );
      })()}

      {active && (
        <label className="row single-step-row" title="Pause after each step. Off resumes continuous running.">
          <input type="checkbox" checked={!!r?.single_step} disabled={!gates.controllable} onChange={(e) => call("single-step", () => api.setSingleStep(e.target.checked))} /> single-step (pause after each step)
        </label>
      )}

      {/* body — one focused layout per state */}
      {active || job ? (
        <div className="print-grid">
          {imaging}
          {active ? (timeline ?? <div className="card"><h3>ready</h3><div className="hint">the timeline appears when a print is compiled.</div></div>) : (
            <div className="card">
              <h3>ready to print</h3>
              <div className="job-map" style={{ marginTop: 0 }}>
                <span>layers</span><span>{job!.layer_count}</span>
                <span>part height</span><span>{job!.height_mm} mm</span>
                <span>footprint</span><span>{job!.bbox_mm.x} × {job!.bbox_mm.y} mm</span>
                <span>estimate</span><span>~{fmtSecs(total)}</span>
              </div>
              <div className="actions one tight" style={{ marginTop: 18 }}>
                <button className="cta primary" onClick={onJob}>START THIS JOB</button>
              </div>
              <div className="hint" style={{ marginTop: 10 }}>Opens the Job tab to confirm settings and launch.</div>
            </div>
          )}
        </div>
      ) : (
        <div className="card manual-card">
          <h3>manual print<span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>no sliced job</span></h3>
          {mplan ? (
            <>
              <div className="hint" style={{ marginTop: 0 }}>Run the print routine straight from these parameters — no sliced job needed.</div>
              <div className="fields" style={{ marginTop: 16 }}>
                <span>print layers</span><span className="row"><NumberField value={mplan.printing.n_layers} disabled={!gates.controllable} style={{ width: 80 }} onChange={(v) => meditPrinting({ n_layers: v })} /></span>
                <span>layer height</span><label className="row">
                  <span className="seg">{LAYER_HEIGHTS.map((h) => <button key={h} type="button" className={`small${Math.abs(mplan.printing.layer_thickness_mm - h) < 1e-6 ? " on" : ""}`} aria-pressed={Math.abs(mplan.printing.layer_thickness_mm - h) < 1e-6} disabled={!gates.controllable} onClick={() => meditPrinting({ layer_thickness_mm: h })}>{h}</button>)}</span>
                  <NumberField step="0.1" value={mplan.printing.layer_thickness_mm} disabled={!gates.controllable} style={{ width: 72 }} onChange={(v) => meditPrinting({ layer_thickness_mm: snapLayerHeightMm(v) })} /> mm
                </label>
                <span>postcoat</span><label className="row"><Toggle checked={mplan.postcoat_enabled} disabled={!gates.controllable} onChange={(v) => medit({ postcoat_enabled: v })} /></label>
                <span>heater</span><label className="row" title="Fires the IR heater during the printing layers. Forced off in a dry run."><Toggle label="heater" danger checked={mHeaterOn} disabled={mdry || !gates.controllable} onChange={(v) => medit({ heater_enabled: v })} />{mdry ? <span className="hint">&nbsp;(off in dry run)</span> : null}</label>
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
          ) : <div className="hint">loading print_settings…</div>}
        </div>
      )}

      {/* Print Parameters — collapsible drawer, open by default (operators tune these each run) */}
      <details className="rp-drawer" open>
        <summary>Print Parameters</summary>
        <div className="body"><RoutinePanel gates={gates} call={call} /></div>
      </details>
    </div>
  );
}
