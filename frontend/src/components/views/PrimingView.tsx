import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
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
export function PrimingView({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call }) {
  const { p, s, invalid, edit, setEdit, save, setParam } = usePriming(call);
  const ok = gates.controllable && !gates.printActive;
  const r = status?.print ?? null;
  const paused = r?.state === "paused";

  const [step, setStep] = useState(0);
  const cur = WALKTHROUGH_STEPS[step];

  // Amount inputs. "job" reads the loaded print's total thickness; the manual sources are operator mm.
  const [source, setSource] = useState<FillSource>("job");
  const [marginMm, setMarginMm] = useState(5);
  const [nLayers, setNLayers] = useState(0);
  const [layerThicknessMm, setLayerThicknessMm] = useState(0);
  const [manualDepthMm, setManualDepthMm] = useState(0);
  const [jobThicknessMm, setJobThicknessMm] = useState<number | null>(null);

  const [primed, setPrimed] = useState<{ part_mm: number; feed_mm: number; captured_at: number } | null>(null);

  // Pull the loaded job's total powder thickness once, plus any previously captured primed bed.
  useEffect(() => {
    let live = true;
    api.printSettings().then((x) => live && setJobThicknessMm(x.total_thickness_mm)).catch(() => {});
    api.primed().then((x) => live && setPrimed(x.primed)).catch(() => {});
    return () => { live = false; };
  }, []);

  const depth = fillDepthMm({ source, totalThicknessMm: jobThicknessMm ?? 0, nLayers, layerThicknessMm, manualDepthMm, marginMm });
  const pct = cavityFillPct(depth);
  const nudgeOpts = [0.5, 1, 5];
  const [nudgeStepMm, setNudgeStepMm] = useState(1);

  const num = (v: number, set: (n: number) => void, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" value={Number.isFinite(v) ? v : ""}
        onChange={(e) => set(e.target.value === "" ? 0 : Number(e.target.value))} />
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
                <div className="fields">
                  <span>job total thickness</span><span className="ro">{fmt(jobThicknessMm)}</span>
                  {num(marginMm, setMarginMm, "margin")}
                </div>
              )}
              {source === "layers" && (
                <>
                  <div className="fields">
                    {num(nLayers, setNLayers, "layers")}
                    {num(layerThicknessMm, setLayerThicknessMm, "layer thickness")}
                    {num(marginMm, setMarginMm, "margin")}
                  </div>
                  <div className="hint">Include the precoat layers (runway + part-piston fill), not just the part slices.</div>
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
              <div className="hint">Spread the powder across the bed, then return the recoater. Repeat as many passes as it takes to get an even layer.</div>
              <div className="kv">
                <span>spread to</span><span>{fmt(target("level_recoat_end_mm"))}</span>
                <span>return to</span><span>{fmt(target("level_recoat_return_mm"))}</span>
              </div>
              <div className="actions">
                <button className="cta primary" disabled={!ok || target("level_recoat_end_mm") === null}
                  onClick={() => call("spread", () => api.move(4, "abs", target("level_recoat_end_mm") as number))}>Spread</button>
                <button className="cta" disabled={!ok || target("level_recoat_return_mm") === null}
                  onClick={() => call("return recoater", () => api.move(4, "abs", target("level_recoat_return_mm") as number))}>Return</button>
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
                <div className="kv">
                  <span>captured part</span><span>{primed.part_mm} mm</span>
                  <span>captured feed</span><span>{primed.feed_mm} mm</span>
                </div>
              ) : <div className="hint">No primed bed captured yet.</div>}
              <div className="hint">Switch to the Print tab to start a print from the captured bed.</div>
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
