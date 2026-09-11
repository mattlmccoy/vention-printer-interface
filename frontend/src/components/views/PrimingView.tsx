import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import { AXES, type AxisNo, type StatusPayload } from "../../lib/telemetry.ts";
import { fillDepthMm, cavityFillPct, FEED_TRAVEL_MM, type FillSource } from "../../lib/powder.ts";
import { WALKTHROUGH_STEPS, stepHeading } from "../../lib/walkthrough.ts";
import { Elevation } from "../Elevation.tsx";
import { PrimingFields, usePriming } from "../PrimingPanel.tsx";
import type { Call } from "./types.ts";

/** Priming tab: a guided, stepped powder-loading + leveling walkthrough. A persistent live
 *  Elevation (with on-diagram piston ▲/▼ + recoater ◀/▶ nudge controls) is the centrepiece; a
 *  six-step stepper on the left walks the operator through picking an amount, opening the cavity,
 *  loading powder, leveling, and capturing the primed bed. The walkthrough shows its OWN step
 *  position ("Step 3 of 6"), never the compiled priming macro's raw step count. A RUN PRIMING
 *  (auto) escape hatch + ABORT stay available, but the stepper is the primary flow. */
const SW: Record<AxisNo, string> = { 1: "sw-part", 2: "sw-feed", 3: "sw-ph", 4: "sw-rc" };
const SHORT: Record<AxisNo, string> = { 1: "build", 2: "feed", 3: "printhead", 4: "recoater" };

export function PrimingView({ status, gates, call, onJob, onPrint }: { status: StatusPayload | null; gates: Gates; call: Call; onJob: () => void; onPrint: () => void }) {
  const { p, s, invalid, edit, setEdit, save, setParam } = usePriming(call);
  const ok = gates.controllable && !gates.printActive;
  const r = status?.print ?? null;
  const t = status?.controller.telemetry ?? null;
  const paused = r?.state === "paused";
  // Live state of the automatic RUN PRIMING macro. Surfaced as a banner so the button visibly
  // does something — the macro's progress otherwise only shows on the Print tab.
  const macroRunning = r?.macro === "priming" && (r.state === "running" || r.state === "paused");
  const macroPct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;

  const [step, setStep] = useState(0);
  const cur = WALKTHROUGH_STEPS[step];

  // Amount inputs. "job" reads the loaded print's total thickness; the manual sources are operator mm.
  // Inputs are RAW STRINGS so they clear + type normally (empty allowed); parsed to numbers for the calc.
  const [source, setSource] = useState<FillSource>("job");
  const [marginMm, setMarginMm] = useState("5");
  const [nLayers, setNLayers] = useState("");
  const [layerThicknessMm, setLayerThicknessMm] = useState("");
  const [manualDepthMm, setManualDepthMm] = useState("");
  const [jobThicknessMm, setJobThicknessMm] = useState<number | null>(null);

  const [primed, setPrimed] = useState<{ part_mm: number; feed_mm: number; captured_at: number } | null>(null);

  // Re-pull the print's total powder thickness whenever the selected job changes (selecting a job in
  // the Job tab updates the print settings), so "paired to job" reflects the current job live.
  useEffect(() => {
    let live = true;
    api.printSettings().then((x) => live && setJobThicknessMm(x.total_thickness_mm)).catch(() => {});
    return () => { live = false; };
  }, [status?.job?.path]);
  // Any previously captured primed bed (once).
  useEffect(() => {
    let live = true;
    api.primed().then((x) => live && setPrimed(x.primed)).catch(() => {});
    return () => { live = false; };
  }, []);

  const n = (v: string) => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const depth = fillDepthMm({ source, totalThicknessMm: jobThicknessMm ?? 0, nLayers: n(nLayers), layerThicknessMm: n(layerThicknessMm), manualDepthMm: n(manualDepthMm), marginMm: n(marginMm) });
  const pct = cavityFillPct(depth);
  const nudgeOpts = [0.5, 1, 5];
  const [nudgeStepMm, setNudgeStepMm] = useState(1);

  const num = (v: string, set: (s: string) => void, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" inputMode="decimal" value={v} onChange={(e) => set(e.target.value)} />
    </>
  );

  const srcBtn = (value: FillSource, label: string) => (
    <button className={`small${source === value ? " on" : ""}`} aria-pressed={source === value}
      onClick={() => setSource(value)}>{label}</button>
  );

  const target = (k: string): number | null => (s ? s[k] ?? null : null);
  const fmt = (mm: number | null) => (mm === null ? "—" : `${mm} mm`);

  return (
    <div className="view priming-walk">
      <section className="step-col">
        <div className="h">prime the bed · powder loading + leveling</div>

        {macroRunning && (
          <div className={`banner ${paused ? "warn" : ""}`} style={{ marginBottom: 12 }}>
            <b>PRIMING {paused ? "PAUSED" : "RUNNING"}</b>
            <span className="reason">{paused ? (r?.reason || "load powder into the feed cavity, then Resume") : `step ${r?.step_index ?? 0} of ${r?.n_steps ?? 0} · ${macroPct}%`}</span>
            {paused && <button className="small" disabled={!gates.connected} style={{ marginLeft: "auto" }} onClick={() => call("resume priming", api.printResume)}>Resume</button>}
            <button className="small" disabled={!gates.connected} style={{ marginLeft: paused ? 6 : "auto" }} onClick={() => call("abort", api.printAbort)}>Abort</button>
          </div>
        )}
        {r?.macro === "priming" && r.state === "done" && (
          <div className="banner" style={{ marginBottom: 12 }}>
            <b>PRIMING COMPLETE</b>
            <span className="reason">capture the primed bed (sends the final build + feed positions to the print), then start printing</span>
            <button className="cta primary small" disabled={!gates.controllable} style={{ marginLeft: "auto" }}
              onClick={() => call("capture primed", () => api.primedCapture().then((x) => { setPrimed(x.primed); onPrint(); }))}>Capture &amp; go to Print →</button>
          </div>
        )}

        {/* walkthrough's OWN progress — never the compiled macro step count */}
        <ol className="step-rail" aria-label="priming walkthrough steps">
          {WALKTHROUGH_STEPS.map((w, i) => (
            <li key={w.id} className={i === step ? "on" : i < step ? "done" : ""}
              aria-current={i === step ? "step" : undefined}>
              <span className="n">{i + 1}</span><span className="t">{w.title}</span>
            </li>
          ))}
        </ol>

        <div className="step-head">{stepHeading(step)}</div>

        <div className="step-body">
          {cur.id === "amount" && (
            <>
              <div className="hint">How much powder should the feed cavity hold? Pick a source.</div>
              <div className="seg">
                {srcBtn("job", "paired to job")}
                {srcBtn("layers", "layers × thickness")}
                {srcBtn("depth", "depth (mm)")}
              </div>
              {source === "job" && (
                <>
                  <div className="fields">
                    <span>selected job</span>
                    <span className="ro">{status?.job ? status.job.name : "none selected"}</span>
                    <span>{status?.job ? "job total thickness" : "print-settings thickness"}</span>
                    <span className="ro">{fmt(jobThicknessMm)}</span>
                    {num(marginMm, setMarginMm, "margin")}
                  </div>
                  {!status?.job && (
                    <div className="hint">No sliced job is loaded, so this uses the current print-settings thickness.
                      Pick a job for an exact amount: <button className="linklike" onClick={onJob}>open the Job tab →</button></div>
                  )}
                </>
              )}
              {source === "layers" && (
                <>
                  <div className="fields">
                    {num(nLayers, setNLayers, "layers")}
                    {num(layerThicknessMm, setLayerThicknessMm, "layer thickness")}
                    {num(marginMm, setMarginMm, "margin")}
                  </div>
                  <div className="hint">Include the precoat layers (runway + build-piston fill), not just the part slices.</div>
                </>
              )}
              {source === "depth" && (
                <div className="fields">
                  {num(manualDepthMm, setManualDepthMm, "depth")}
                </div>
              )}
              <div className="kv">
                <span>feed-cavity fill depth</span><span>{depth.toFixed(1)} mm</span>
              </div>
              <div className="bar"><i style={{ width: `${pct}%` }} /></div>
              <div className="bar-lbl">{pct}% of {FEED_TRAVEL_MM} mm feed travel</div>
              <div className="actions one">
                <button className="cta primary" disabled={!ok || depth <= 0}
                  onClick={() => setParam({ feed_cavity_mm: depth }, "set feed cavity")}>Set as feed cavity</button>
              </div>
              <div className="kv"><span>saved feed cavity</span><span>{fmt(target("feed_cavity_mm"))}</span></div>
            </>
          )}

          {cur.id === "build-up" && (
            <>
              <div className="hint">Raise the build (part) piston to the top so the recoater can spread over it.</div>
              <div className="kv"><span>target · part top</span><span>{fmt(target("part_top_mm"))}</span></div>
              <div className="actions one">
                <button className="cta primary" disabled={!ok || target("part_top_mm") === null}
                  onClick={() => call("build up", () => api.move(1, "abs", target("part_top_mm") as number))}>Run this step</button>
              </div>
              <div className="hint">You can also fine-tune with the ▲/▼ build-piston controls on the diagram.</div>
            </>
          )}

          {cur.id === "open-feed" && (
            <>
              <div className="hint">Lower the feed piston to open a powder cavity of the depth you set.</div>
              <div className="kv"><span>target · feed cavity</span><span>{fmt(target("feed_cavity_mm"))}</span></div>
              <div className="actions one">
                <button className="cta primary" disabled={!ok || target("feed_cavity_mm") === null}
                  onClick={() => call("open feed cavity", () => api.move(2, "abs", target("feed_cavity_mm") as number))}>Run this step</button>
              </div>
              <div className="hint">Or open it by hand with the ▲/▼ feed-piston controls on the diagram.</div>
            </>
          )}

          {cur.id === "load" && (
            <>
              <div className="hint">Pour powder into the open feed cavity until it is full and level with the bed. No motor moves here — this is a hold.</div>
              {paused && <div className="lock">A priming macro is paused for this hold. Resume it once powder is loaded.</div>}
              <div className="actions one">
                <button className="cta primary" onClick={() => setStep((n) => n + 1)}>Powder loaded — next</button>
                {paused && (
                  <button className="cta" disabled={!gates.connected}
                    onClick={() => call("resume priming", api.printResume)}>Resume paused macro</button>
                )}
              </div>
            </>
          )}

          {cur.id === "level" && (
            <>
              <div className="step-head">Thick precoats — fill the runway + part cavity, then it's level</div>
              <div className="hint">Each thick precoat moves the recoater to the start position (past the feed piston), then spreads across the bed to fill the runway and the build-piston cavity. The build piston stays fixed. Repeat for each precoat until the bed is even.</div>
              <div className="kv">
                <span>thick precoats</span><span>{target("n_thick_precoats") ?? "—"}</span>
                <span>feed / precoat</span><span>{fmt(target("thick_feed_mm"))}</span>
                <span>start (past feed)</span><span>{fmt(target("level_recoat_start_mm"))}</span>
                <span>spread to</span><span>{fmt(target("level_recoat_end_mm"))}</span>
              </div>
              <div className="actions">
                <button className="cta primary" disabled={!ok || target("level_recoat_start_mm") === null}
                  onClick={() => call("move to start", () => api.move(4, "abs", target("level_recoat_start_mm") as number))}>Move to start</button>
                <button className="cta" disabled={!ok || target("level_recoat_end_mm") === null}
                  onClick={() => call("spread", () => api.move(4, "abs", target("level_recoat_end_mm") as number))}>Spread ▶</button>
              </div>
              <div className="hint">The ◀/▶ recoater controls on the diagram also work for manual nudges.</div>
            </>
          )}

          {cur.id === "finish" && (
            <>
              <div className="hint">When the bed is evenly primed, capture the primed piston positions. The Print tab then starts from these.</div>
              <div className="actions one">
                <button className="cta primary" disabled={!ok}
                  onClick={() => call("capture primed", () => api.primedCapture().then((x) => setPrimed(x.primed)))}>Bed is primed — finish</button>
              </div>
              {primed ? (
                <>
                  <div className="kv">
                    <span>captured part</span><span>{primed.part_mm} mm</span>
                    <span>captured feed</span><span>{primed.feed_mm} mm</span>
                  </div>
                  <div className="actions one" style={{ marginTop: 12 }}>
                    <button className="cta primary" onClick={onPrint}>Priming complete — go to Print →</button>
                  </div>
                </>
              ) : <div className="hint">No primed bed captured yet. The Print tab starts from the captured bed.</div>}
            </>
          )}
        </div>

        <div className="step-nav">
          <button className="small" disabled={step === 0} onClick={() => setStep((n) => Math.max(0, n - 1))}>Back</button>
          <button className="small" disabled={step === WALKTHROUGH_STEPS.length - 1}
            onClick={() => setStep((n) => Math.min(WALKTHROUGH_STEPS.length - 1, n + 1))}>Next</button>
        </div>

        {/* underlying parameters the operator may want to adjust (part top, feed cavity, level ends) */}
        <details className="params">
          <summary>priming parameters</summary>
          <PrimingFields s={s} edit={edit} setEdit={setEdit} ok={ok} save={save} />
          {invalid && <div className="lock">{p?.validation.join("; ")}</div>}
        </details>

        {/* escape hatch: run the whole routine automatically, or abort */}
        <div className="escape">
          <div className="h">automatic</div>
          <div className="actions">
            <button className="cta" disabled={!ok || invalid}
              onClick={() => { if (window.confirm("Run the full priming routine automatically? It positions the pistons, PAUSES for you to load powder, then levels. Pistons are never homed.")) call("run priming", api.primingRun); }}>RUN PRIMING</button>
            <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
          </div>
        </div>
      </section>

      <section className="diagram-col">
        <div className="h">live machine</div>
        <div className="diagram">
          <Elevation
            status={status}
            partZeroMm={r?.part_zero_mm ?? null}
            mode="live"
            onNudge={(axis, d) => call("nudge", () => api.move(axis, "rel", d))}
            nudgeStepMm={nudgeStepMm}
            controlsEnabled={ok}
          />
        </div>
        <div className="readout">{AXES.map((a) => { const u = t?.referenced?.[String(a)] === false; return <div key={a}><i className={SW[a]} />{SHORT[a]}<b className={u ? "unref" : ""} title={u ? "not homed since power-on — unreferenced" : ""}>{!t ? "—" : u ? "unref" : `${(t.positions[String(a)] ?? 0).toFixed(1)} mm`}</b></div>; })}</div>
        <div className="narr">
          {ok ? "in control" : gates.connected ? "read-only — arm to move" : "not connected"}
          <div className="next">
            <span>nudge step</span>
            {nudgeOpts.map((v) => (
              <button key={v} className={`small${nudgeStepMm === v ? " on" : ""}`} aria-pressed={nudgeStepMm === v}
                onClick={() => setNudgeStepMm(v)}>{v} mm</button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
