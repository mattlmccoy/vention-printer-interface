import { useEffect, useRef, useState } from "react";
import { api, type MeteorStatus } from "../../lib/api.ts";
import { estimateDurationS } from "../../lib/estimate.ts";
import { fmtSecs, type Gates } from "../../lib/format.ts";
import { CAPTURE_STAGES, CAPTURE_STAGE_LABEL, multipassMismatch, toggleCaptureStage, totalLayers, totalThickness, validate, type PrintSettings } from "../../lib/print_settings.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { NumberField } from "../NumberField.tsx";
import { Toggle } from "../Toggle.tsx";
import { LAYER_HEIGHTS_MM, snapLayerHeightMm } from "../../lib/layer_height.ts";
import { loadOverviewTimelapse, saveOverviewTimelapse } from "../../lib/timelapse_settings.ts";
import type { Call } from "./types.ts";

const BUDGET = 145;
function num(v: string, fb: number): number { const n = Number(v); return v !== "" && Number.isFinite(n) ? n : fb; }

/** Configure + START a print. Lives on the Print tab (the Job tab only queues a job). Works for the
 *  selected sliced job (status.job) or a manual print (no job): edits print_settings, validates,
 *  and calls api.printStart directly — no navigation. `onStarted` fires once a start is accepted. */
export function PrintConfigurator({ status, gates, call, onStarted }: {
  status: StatusPayload | null; gates: Gates; call: Call; onStarted: () => void;
}) {
  const [plan, setPlan] = useState<PrintSettings | null>(null);
  const [dirty, setDirty] = useState(false);
  const [single, setSingle] = useState(false);
  const [name, setName] = useState("");
  const [meteor, setMeteor] = useState<MeteorStatus | null>(null);
  const [primed, setPrimed] = useState<boolean | null>(null); // null = unknown, else bed-primed?
  const [mpDismissed, setMpDismissed] = useState(false); // dismissable multipass-mismatch warning (#7)
  const [minWait, setMinWait] = useState(0.25); // the operator's real wait floor, for a matching estimate (#6)
  const [overviewTl, setOverviewTl] = useState(() => loadOverviewTimelapse(typeof localStorage === "undefined" ? null : localStorage));
  const job = status?.job ?? null;
  const running = gates.printActive;

  const refresh = () => {
    api.printSettings().then((r) => { setPlan(r.plan as unknown as PrintSettings); setMinWait(r.min_wait_s ?? 0.25); setDirty(false); }).catch(() => undefined);
    api.meteorStatus().then(setMeteor).catch(() => setMeteor(null));
    // A print is refused (409) until the bed is primed; fetch it so we can guide to Priming rather
    // than let START fail. The tab remounts this component, so a fresh capture is picked up on return.
    api.primed().then((r) => setPrimed(r.primed !== null)).catch(() => setPrimed(null));
  };
  useEffect(() => { refresh(); }, [gates.reachable, job?.path]);

  const edit = (patch: Partial<PrintSettings>) => plan && (setPlan({ ...plan, ...patch }), setDirty(true));
  const editOverviewTl = (patch: Partial<typeof overviewTl>) => {
    const next = { ...overviewTl, ...patch };
    setOverviewTl(next);
    saveOverviewTimelapse(typeof localStorage === "undefined" ? null : localStorage, next);
  };
  const editPh = (ph: "thin_precoat" | "printing" | "postcoat", patch: Partial<PrintSettings["printing"]>) => plan && edit({ [ph]: { ...plan[ph], ...patch } } as Partial<PrintSettings>);
  const editAllPhases = (patch: Partial<PrintSettings["printing"]>) => plan && edit({
    thin_precoat: { ...plan.thin_precoat, ...patch },
    printing: { ...plan.printing, ...patch },
    postcoat: { ...plan.postcoat, ...patch },
  } as Partial<PrintSettings>);
  // This form does NOT own the routine-only fields (multipass n_jet_passes, pre_heater_drop_mm) —
  // those live in Routine Parameters. Strip them from every save so configuring never clobbers them.
  const jobPatch = (p: PrintSettings): Record<string, unknown> => { const { n_jet_passes: _a, pre_heater_drop_mm: _b, ...rest } = p as unknown as Record<string, unknown>; return rest; };
  const save = async () => { if (!plan) return; await call("save print_settings", () => api.setPrintSettings(jobPatch(plan)).then((r) => { setPlan(r.plan as unknown as PrintSettings); setDirty(false); })); };
  // Persist unsaved edits when leaving, so a configured print carries through to Priming and status.
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
  const thin = plan ? plan.thin_precoat.layer_thickness_mm * plan.thin_precoat.n_layers : 0;
  const pr = plan ? plan.printing.layer_thickness_mm * plan.printing.n_layers : 0;
  const post = plan && plan.postcoat_enabled ? plan.postcoat.layer_thickness_mm * plan.postcoat.n_layers : 0;
  const mismatch = job && plan && plan.printing.n_layers !== job.layer_count;
  const LAYER_HEIGHTS = LAYER_HEIGHTS_MM;

  const start = async () => {
    if (!plan) return;
    if (dirty) await save();
    const heat = plan.heater_enabled ? "HEATER ON — fires each printing layer" : "⚠ HEATER OFF — no in-situ heating";
    if (!window.confirm(`Start ${job ? job.name : "the manual print"} on the machine?\n\n${heat}\n${layers} layers · ${total.toFixed(1)} mm · ~${fmtSecs(estimateDurationS(plan, minWait))}`)) return;
    await call("start", () => api.printStart({ single_step: single, name: name || job?.name || "print" }).then(onStarted));
  };

  return (
    <>
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
                <span data-tip="Thin precoat layers spread before printing — kept very thin to lay a fresh, level powder bed. Count × thickness (mm). Thick priming precoats now live on the Priming tab.">precoat</span><span className="row"><NumberField value={plan.thin_precoat.n_layers} disabled={running} onChange={(v) => editPh("thin_precoat", { n_layers: v })} style={{ width: 56 }} /> × <NumberField step="0.1" value={plan.thin_precoat.layer_thickness_mm} disabled={running} onChange={(v) => editPh("thin_precoat", { layer_thickness_mm: snapLayerHeightMm(v) })} style={{ width: 72 }} /> mm <span className="hint">(thin precoat — thick precoats now live in Priming)</span></span>
                <span data-tip="Capping layers spread after the last printing layer to bury and protect the finished part. Toggle on, then count × thickness (mm).">postcoat</span><label className="row"><Toggle checked={plan.postcoat_enabled} disabled={running} onChange={(v) => edit({ postcoat_enabled: v })} />{plan.postcoat_enabled && <> · <NumberField value={plan.postcoat.n_layers} disabled={running} onChange={(v) => editPh("postcoat", { n_layers: v })} style={{ width: 56 }} /> × <NumberField step="0.1" value={plan.postcoat.layer_thickness_mm} disabled={running} onChange={(v) => editPh("postcoat", { layer_thickness_mm: snapLayerHeightMm(v) })} style={{ width: 72 }} /> mm</>}</label>
                <span data-tip="Printed layer thickness (mm) — how far the build piston drops before each printing layer. Match the slicer's layer height; the segmented buttons are the common presets.">layer height</span><label className="row">
                  <span className="seg">{LAYER_HEIGHTS.map((h) => <button key={h} type="button" className={`small${Math.abs(plan.printing.layer_thickness_mm - h) < 1e-6 ? " on" : ""}`} aria-pressed={Math.abs(plan.printing.layer_thickness_mm - h) < 1e-6} disabled={running} onClick={() => editPh("printing", { layer_thickness_mm: h })}>{h}</button>)}</span>
                  <input type="number" step="0.1" min="0.1" value={plan.printing.layer_thickness_mm} disabled={running} onChange={(e) => editPh("printing", { layer_thickness_mm: snapLayerHeightMm(num(e.target.value, plan.printing.layer_thickness_mm)) })} style={{ width: 72 }} /> mm{job ? <span className="hint" style={{ marginLeft: 6 }}>slicer: {job.layer_height_mm} mm</span> : null}
                </label>
                {!job && <><span data-tip="Number of printing layers to run (manual print only — a sliced job sets this from its layer count).">print layers</span><input type="number" value={plan.printing.n_layers} disabled={running} onChange={(e) => editPh("printing", { n_layers: num(e.target.value, plan.printing.n_layers) })} /></>}
                <span data-tip="Fire the IR heater after each printing layer to drive off binder solvent. Set how many heater sweeps per layer.">heater</span><label className="row"><Toggle checked={plan.heater_enabled} disabled={running} onChange={(v) => edit({ heater_enabled: v })} /> <span className="hint">fire the IR heater each printing layer,</span> <input type="number" value={plan.n_heater_passes} disabled={running || !plan.heater_enabled} onChange={(e) => edit({ n_heater_passes: num(e.target.value, plan.n_heater_passes) })} style={{ width: 56 }} /> pass(es)</label>
                <span data-tip="Emit layerwise vision capture marks (pre-jet / post-jet / post-heat) for the camera on the recoater gantry.">layer captures</span><label className="row"><Toggle checked={plan.capture_stages} disabled={running} onChange={(v) => edit({ capture_stages: v })} /> <span className="hint">record the science camera at each layer stage</span></label>
                {plan.capture_stages && (<>
                  <span data-tip="Choose which of the three per-layer stages to photograph. Fewer stages = less disk. At least one must stay on.">capture stages</span>
                  <span className="row" style={{ gap: 10, flexWrap: "wrap" }}>
                    {CAPTURE_STAGES.map((s) => {
                      const on = plan.capture_stages_enabled.includes(s);
                      const soleOn = on && plan.capture_stages_enabled.length === 1; // keep ≥1 selected
                      return (
                        <label key={s} className="row" style={{ gap: 4 }} data-tip={soleOn ? "at least one stage must stay selected" : undefined}>
                          <input type="checkbox" checked={on} disabled={running || soleOn}
                            onChange={() => edit({ capture_stages_enabled: toggleCaptureStage(plan.capture_stages_enabled, s) })} />
                          {CAPTURE_STAGE_LABEL[s]}
                        </label>
                      );
                    })}
                  </span>
                </>)}
                <span data-tip="Capture the wide overview camera on a timer for whole-print playback under Runs.">overview timelapse</span><label className="row"><Toggle checked={overviewTl.enabled} disabled={running} onChange={(v) => editOverviewTl({ enabled: v })} /> <span className="hint">record wide view every</span> <input type="number" min={0.5} max={60} step={0.5} value={overviewTl.intervalS} disabled={running || !overviewTl.enabled} onChange={(e) => editOverviewTl({ intervalS: Number(e.target.value) || 3 })} style={{ width: 64 }} /> <span className="hint">seconds</span></label>
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
                <span data-tip="Number of printed layers in the selected slicer job. Flagged if it doesn't match the print's layer count.">layers</span><span className={mismatch ? "warnv" : ""}>{job.layer_count}{mismatch ? " ≠ print" : ""}</span>
                <span data-tip="Per-layer thickness the slicer used (informational — the print uses the layer height you set above).">slicer layer height</span><span>{job.layer_height_mm} mm</span>
                <span data-tip="Total part height from the slicer (layers × slicer layer height).">part height</span><span>{job.height_mm} mm</span>
                <span data-tip="Part bounding-box footprint on the bed (X × Y, mm).">footprint</span><span>{job.bbox_mm.x} × {job.bbox_mm.y} mm</span>
                <span data-tip="What THIS print is set to run: printing layers × layer height. Flagged if it differs from the job.">print_settings</span><span className={mismatch ? "warnv" : ""}>{plan.printing.n_layers} × {plan.printing.layer_thickness_mm} mm{mismatch ? " ≠ job" : ""}</span>
                <span data-tip="Whether MetPrint (the printhead RIP) has this job's layers staged in the hot folder and is ready to fire.">MetPrint firing</span>{meteor
                  ? <span className={meteor.ready ? "okv" : "warnv"} data-tip={meteor.detail}>{meteor.ready
                      ? `ready · ${meteor.layers_expected} layers in the hot folder`
                      : `not ready · ${meteor.detail}`}</span>
                  : <span className="warnv">firing status unavailable</span>}
                {job.slicer_multipass != null && <>
                  <span data-tip="Multipass factor declared by the slicer when this file was created.">slicer multipass</span>
                  <span className={multipassMismatch(job.slicer_multipass, plan.n_jet_passes) ? "warnv" : ""}>
                    {job.slicer_multipass}× {plan.n_jet_passes !== job.slicer_multipass ? `(print: ${plan.n_jet_passes}×)` : ""}
                  </span>
                </>}
              </div>
              {job.slicer_multipass != null && multipassMismatch(job.slicer_multipass, plan.n_jet_passes) && !mpDismissed && (
                <div className="errline" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
                  <span>⚠ This file was created with multipass enabled at {job.slicer_multipass}×, but the print is set to {plan.n_jet_passes}×.</span>
                  <button className="cta sm" disabled={running} onClick={() => call("apply multipass", () => api.setPrintSettings({ n_jet_passes: job.slicer_multipass }).then(() => refresh()))}>Apply {job.slicer_multipass}×</button>
                  <button className="small" onClick={() => setMpDismissed(true)}>dismiss</button>
                </div>
              )}
            </div>
          )}
          <div className="card">
            <h3>start</h3>
            {plan ? (
              <>
                <div className="est" style={{ gridTemplateColumns: "1fr 1fr" }}><div><div className="l">about</div><div className="v" style={{ fontSize: 26 }}>{fmtSecs(estimateDurationS(plan, minWait))}</div></div><div><div className="l">layers</div><div className="v" style={{ fontSize: 26 }}>{layers}</div></div></div>
                <div className="chk" style={{ margin: "16px 0" }}>
                  <label data-tip="Fires the IR heater during the printing layers (after the precoats)."><Toggle label="heater" danger checked={plan.heater_enabled} disabled={running} onChange={(v) => edit({ heater_enabled: v })} /></label>
                  <label data-tip="Start paused and advance ONE step at a time (debugging)."><input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> single-step</label>
                  <label><input type="checkbox" checked={status?.auto_log ?? true} onChange={(e) => call("auto-log", () => api.setAutoLog(e.target.checked))} /> record</label>
                </div>
                <input type="text" placeholder={job?.name ?? "run name"} value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%" }} />
                {primed === false && !running && (
                  <div className="errline" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <span>⚠ bed not primed — prime it before printing</span>
                    <button className="cta sm" onClick={() => { window.location.hash = "priming"; }}>Go to Priming →</button>
                  </div>
                )}
                <div className="actions one tight">
                  <button className="cta primary" disabled={!gates.controllable || reasons.length > 0 || running || primed === false} onClick={start}>START PRINT</button>
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
              <span className="grp">pistons</span>
              <span data-tip="Build & feed piston speed for layer moves (drop + advance), mm/s.">piston speed</span><span className="row"><input type="number" step="0.1" value={plan.printing.part_speed} disabled={running} onChange={(e) => { const s = num(e.target.value, plan.printing.part_speed); editAllPhases({ part_speed: s, feed_speed: s }); }} /> mm/s</span>
              <span data-tip="Build & feed piston acceleration, mm/s².">piston accel</span><span className="row"><input type="number" value={plan.printing.part_accel} disabled={running} onChange={(e) => { const a = num(e.target.value, plan.printing.part_accel); editAllPhases({ part_accel: a, feed_accel: a }); }} /> mm/s²</span>
              <span data-tip="Fast feed-piston speed for non-metering repositioning moves, mm/s.">feed fast speed</span><span className="row"><input type="number" value={plan.feed_fast_speed} disabled={running} onChange={(e) => edit({ feed_fast_speed: num(e.target.value, plan.feed_fast_speed) })} /> mm/s</span>
              <span data-tip="Fast feed-piston repositioning acceleration, mm/s².">feed fast accel</span><span className="row"><input type="number" value={plan.feed_fast_accel} disabled={running} onChange={(e) => edit({ feed_fast_accel: num(e.target.value, plan.feed_fast_accel) })} /> mm/s²</span>
              <span data-tip="Top of the primed feed powder column; feed advances start here and drop down, mm.">feed end</span><span className="row"><input type="number" value={plan.feed_end_mm} disabled={running} onChange={(e) => edit({ feed_end_mm: num(e.target.value, plan.feed_end_mm) })} /> mm</span>
              <span data-tip="Deepest build-piston drop = spill-safe max depth; the part's final position, mm.">part max</span><span className="row"><input type="number" value={plan.part_max_mm} disabled={running} onChange={(e) => edit({ part_max_mm: num(e.target.value, plan.part_max_mm) })} /> mm</span>
              <span data-tip="Build-piston anti-backlash: overshoot each layer drop DOWN by this much then return UP to the target, so the drop is approached one-sided and lost-motion is taken up. Backlash varies per cylinder — measure it in Settings → Pistons → Calibrate backlash. A clean sweep on the current cylinder found ~0. 0 = off (single V1.py move).">build backlash</span><span className="row"><input type="number" step="0.05" value={plan.build_backlash_mm} disabled={running} onChange={(e) => edit({ build_backlash_mm: num(e.target.value, plan.build_backlash_mm) })} /> mm</span>
              <span data-tip="Absolute layer height (opt-in fix). Positions the build piston by ABSOLUTE move to the primed datum + cumulative commanded height each layer (instead of stacking relative drops), so per-layer error can't accumulate and the post-heat capture rides the corrected plane. Turn OFF to instantly revert to the classic relative motion if anything looks wrong at the machine.">absolute height</span><label className="row"><Toggle checked={plan.absolute_layer_seat} disabled={running} onChange={(v) => edit({ absolute_layer_seat: v })} /> <span className="hint">re-seat to the absolute target each layer (no drift)</span></label>

              <span className="grp">recoater</span>
              <span data-tip="Recoater gantry speed while spreading a layer, mm/s.">recoater speed</span><span className="row"><input type="number" value={plan.printing.recoater_speed} disabled={running} onChange={(e) => editAllPhases({ recoater_speed: num(e.target.value, plan.printing.recoater_speed) })} /> mm/s</span>
              <span data-tip="Recoater gantry acceleration, mm/s².">recoater accel</span><span className="row"><input type="number" value={plan.printing.recoater_accel} disabled={running} onChange={(e) => editAllPhases({ recoater_accel: num(e.target.value, plan.printing.recoater_accel) })} /> mm/s²</span>
              <span data-tip="Recoater parked / home position, mm.">recoater home</span><span className="row"><input type="number" value={plan.recoater_home_mm} disabled={running} onChange={(e) => edit({ recoater_home_mm: num(e.target.value, plan.recoater_home_mm) })} /> mm</span>
              <span data-tip="Where the recoater returns to after a precoat/postcoat spread, mm.">recoater return</span><span className="row"><input type="number" value={plan.recoater_return_mm} disabled={running} onChange={(e) => edit({ recoater_return_mm: num(e.target.value, plan.recoater_return_mm) })} /> mm</span>
              <span data-tip="Far end the recoater travels to when spreading a layer, mm.">recoater end</span><span className="row"><input type="number" value={plan.recoater_end_mm} disabled={running} onChange={(e) => edit({ recoater_end_mm: num(e.target.value, plan.recoater_end_mm) })} /> mm</span>

              <span className="grp">printhead</span>
              <span data-tip="Printhead gantry speed during jet passes, mm/s.">printhead speed</span><span className="row"><input type="number" value={plan.printing.printhead_speed} disabled={running} onChange={(e) => editAllPhases({ printhead_speed: num(e.target.value, plan.printing.printhead_speed) })} /> mm/s</span>
              <span data-tip="Printhead gantry acceleration, mm/s².">printhead accel</span><span className="row"><input type="number" value={plan.printing.printhead_accel} disabled={running} onChange={(e) => editAllPhases({ printhead_accel: num(e.target.value, plan.printing.printhead_accel) })} /> mm/s²</span>
              <span data-tip="Printhead home position, mm.">printhead home</span><span className="row"><input type="number" value={plan.printhead_home_mm} disabled={running} onChange={(e) => edit({ printhead_home_mm: num(e.target.value, plan.printhead_home_mm) })} /> mm</span>
              <span data-tip="Reference position where the printhead dwells for a nozzle purge (unless a purge position is set), mm.">printhead start</span><span className="row"><input type="number" value={plan.printhead_start_mm} disabled={running} onChange={(e) => edit({ printhead_start_mm: num(e.target.value, plan.printhead_start_mm) })} /> mm</span>
              <span data-tip="Printhead return position between multipass passes; it only homes on the last pass, mm.">printhead multipass return</span><span className="row"><input type="number" value={plan.printhead_multipass_return_mm} disabled={running} onChange={(e) => edit({ printhead_multipass_return_mm: num(e.target.value, plan.printhead_multipass_return_mm) })} /> mm</span>
              <span data-tip="Far end of the printhead jet pass, mm.">printhead end</span><span className="row"><input type="number" value={plan.printhead_end_mm} disabled={running} onChange={(e) => edit({ printhead_end_mm: num(e.target.value, plan.printhead_end_mm) })} /> mm</span>
              <span data-tip="Absolute printhead position for the nozzle-purge dwell. Blank = use the printhead start, mm.">purge position</span><span className="row"><input type="number" value={plan.purge_position_mm ?? ""} placeholder="printhead start" disabled={running} onChange={(e) => edit({ purge_position_mm: e.target.value === "" ? null : num(e.target.value, plan.purge_position_mm ?? 0) })} /> mm</span>

              <span className="grp">heater &amp; timing</span>
              <span data-tip="IR heater gantry sweep speed, mm/s.">heater speed</span><span className="row"><input type="number" value={plan.heater_speed} disabled={running} onChange={(e) => edit({ heater_speed: num(e.target.value, plan.heater_speed) })} /> mm/s</span>
              <span data-tip="IR heater gantry acceleration, mm/s².">heater accel</span><span className="row"><input type="number" value={plan.heater_accel} disabled={running} onChange={(e) => edit({ heater_accel: num(e.target.value, plan.heater_accel) })} /> mm/s²</span>
              <span data-tip="IR heater home position, mm.">heater home</span><span className="row"><input type="number" value={plan.heater_home_mm} disabled={running} onChange={(e) => edit({ heater_home_mm: num(e.target.value, plan.heater_home_mm) })} /> mm</span>
              <span data-tip="Where the IR heater sweep begins, mm.">heater start</span><span className="row"><input type="number" value={plan.heater_start_mm} disabled={running} onChange={(e) => edit({ heater_start_mm: num(e.target.value, plan.heater_start_mm) })} /> mm</span>
              <span data-tip="Where the IR heater sweep ends, mm.">heater end</span><span className="row"><input type="number" value={plan.heater_end_mm} disabled={running} onChange={(e) => edit({ heater_end_mm: num(e.target.value, plan.heater_end_mm) })} /> mm</span>
              <span data-tip="Dwell after the feed-piston move before the recoater spreads, s.">settle</span><span className="row"><input type="number" step="0.1" value={plan.settle_s} disabled={running} onChange={(e) => edit({ settle_s: num(e.target.value, plan.settle_s) })} /> s</span>
            </div>
          ) : <div className="hint">loading…</div>}
        </div>
      </details>
    </>
  );
}
