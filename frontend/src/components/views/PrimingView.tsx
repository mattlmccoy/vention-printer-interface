import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { fillDepthMm, cavityFillPct, FEED_TRAVEL_MM, type FillSource } from "../../lib/powder.ts";
import { WALKTHROUGH_STEPS, stepHeading } from "../../lib/walkthrough.ts";
import { PrimingFields, usePriming } from "../PrimingPanel.tsx";
import type { Call } from "./types.ts";

/** Priming tab: the mockup's clean two-panel guided flow — a Steps rail (left) + the current
 *  step's content (right). The live machine + overview are watched in the persistent dock, so no
 *  machine is duplicated here. The walkthrough shows its OWN step position ("Step 3 of 6"), never
 *  the compiled priming macro's raw step count. RUN PRIMING (auto) + ABORT stay available. */
const STEP_SUB: Record<string, string> = {
  amount: "feed-cavity target",
  "build-up": "raise build to the bed",
  "open-feed": "lower feed to load",
  load: "manual — hold to confirm",
  level: "pack the bed",
  finish: "capture & go to Print",
};

export function PrimingView({ status, gates, call, onJob, onPrint }: { status: StatusPayload | null; gates: Gates; call: Call; onJob: () => void; onPrint: () => void }) {
  const { p, s, invalid, edit, setEdit, save, setParam } = usePriming(call);
  const ok = gates.controllable && !gates.printActive;
  const r = status?.print ?? null;
  const paused = r?.state === "paused";
  const macroRunning = r?.macro === "priming" && (r.state === "running" || r.state === "paused");
  const macroPct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;

  const [step, setStep] = useState(() => {
    const raw = typeof location !== "undefined" ? new URLSearchParams(location.search).get("step") : null;
    const q = raw === null || raw === "" ? NaN : Number(raw); // Number(null)===0 trap
    return Number.isInteger(q) && q >= 0 && q < WALKTHROUGH_STEPS.length ? q : 0; // capture/deep-link aid
  });
  const cur = WALKTHROUGH_STEPS[step];

  const [source, setSource] = useState<FillSource>("job");
  const [marginMm, setMarginMm] = useState("5");
  const [nLayers, setNLayers] = useState("");
  const [layerThicknessMm, setLayerThicknessMm] = useState("");
  const [manualDepthMm, setManualDepthMm] = useState("");
  const [jobThicknessMm, setJobThicknessMm] = useState<number | null>(null);
  const [primed, setPrimed] = useState<{ part_mm: number; feed_mm: number; captured_at: number } | null>(null);
  const [jogStep, setJogStep] = useState("20"); // recoater jog step (mm) for the leveling step
  const [feedAmt, setFeedAmt] = useState(""); // editable feed-supply amount (mm); blank = saved default
  const [rcSpeed, setRcSpeed] = useState("");
  const [rcAccel, setRcAccel] = useState("");
  const am4 = status?.axis_motion?.["4"]; // recoater current max speed/accel

  useEffect(() => {
    let live = true;
    api.printSettings().then((x) => live && setJobThicknessMm(x.total_thickness_mm)).catch(() => {});
    return () => { live = false; };
  }, [status?.job?.path]);
  useEffect(() => {
    let live = true;
    api.primed().then((x) => live && setPrimed(x.primed)).catch(() => {});
    return () => { live = false; };
  }, []);

  const n = (v: string) => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const depth = fillDepthMm({ source, totalThicknessMm: jobThicknessMm ?? 0, nLayers: n(nLayers), layerThicknessMm: n(layerThicknessMm), manualDepthMm: n(manualDepthMm), marginMm: n(marginMm) });
  const pct = cavityFillPct(depth);

  const num = (v: string, set: (s: string) => void, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" inputMode="decimal" value={v} onChange={(e) => set(e.target.value)} />
    </>
  );
  const srcBtn = (value: FillSource, label: string) => (
    <button className={`small${source === value ? " on" : ""}`} aria-pressed={source === value} onClick={() => setSource(value)}>{label}</button>
  );
  const target = (k: string): number | null => (s ? s[k] ?? null : null);
  const fmt = (mm: number | null) => (mm === null ? "—" : `${mm} mm`);
  const skip = () => setStep((x) => Math.min(WALKTHROUGH_STEPS.length - 1, x + 1));
  // Feed-supply amount for the level step: the editable field, else the saved feed/precoat default.
  const feedSupplyMm = n(feedAmt) > 0 ? n(feedAmt) : (target("thick_feed_mm") ?? 0);

  return (
    <div className="view fixed-page priming-view">
      <div className="sec-h">prime the bed · powder loading + leveling · watch the machine in the dock →</div>
      <div className="setup-grid">
        <div className="card">
          <h3>steps</h3>
          <ol className="srail" aria-label="priming walkthrough steps">
            {WALKTHROUGH_STEPS.map((w, i) => (
              <li key={w.id} className={i === step ? "on" : i < step ? "done" : ""} aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)}>
                <span className="n">{i < step ? "✓" : i + 1}</span>
                <div><div className="t">{w.title}</div><div className="sd">{STEP_SUB[w.id] ?? ""}</div></div>
              </li>
            ))}
          </ol>
        </div>

        <div className="card">
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
              <span className="reason">capture the primed bed, then start printing</span>
              <button className="cta primary small" disabled={!gates.controllable} style={{ marginLeft: "auto" }}
                onClick={() => call("capture primed", () => api.primedCapture().then((x) => { setPrimed(x.primed); onPrint(); }))}>Capture &amp; go to Print →</button>
            </div>
          )}

          <h3>{stepHeading(step)}<span className="num" style={{ color: "var(--faint)", textTransform: "none", letterSpacing: 0 }}>{step + 1} / {WALKTHROUGH_STEPS.length}</span></h3>

          <div className="grid-gap cap">
            {cur.id === "amount" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>How much powder should the feed cavity hold? Pick a source.</div>
                <div className="seg">{srcBtn("job", "paired to job")}{srcBtn("layers", "layers × thickness")}{srcBtn("depth", "depth (mm)")}</div>
                {source === "job" && (
                  <>
                    <div className="fields">
                      <span>selected job</span><span className="ro">{status?.job ? status.job.name : "none selected"}</span>
                      <span>{status?.job ? "job total thickness" : "print-settings thickness"}</span><span className="ro">{fmt(jobThicknessMm)}</span>
                      {num(marginMm, setMarginMm, "margin")}
                    </div>
                    {!status?.job && <div className="hint">No sliced job is loaded, so this uses the current print-settings thickness. Pick a job for an exact amount: <button className="linklike" onClick={onJob}>open the Job tab →</button></div>}
                  </>
                )}
                {source === "layers" && (
                  <>
                    <div className="fields">{num(nLayers, setNLayers, "layers")}{num(layerThicknessMm, setLayerThicknessMm, "layer thickness")}{num(marginMm, setMarginMm, "margin")}</div>
                    <div className="hint">Include the precoat layers (runway + build-piston fill), not just the part slices.</div>
                  </>
                )}
                {source === "depth" && <div className="fields">{num(manualDepthMm, setManualDepthMm, "depth")}</div>}
                <div className="kv"><span>feed-cavity fill depth</span><span>{depth.toFixed(1)} mm</span></div>
                <div className="bar"><i style={{ width: `${pct}%` }} /></div>
                <div className="bar-lbl">{pct}% of {FEED_TRAVEL_MM} mm feed travel</div>
                <div className="kv"><span>saved feed cavity</span><span>{fmt(target("feed_cavity_mm"))}</span></div>
                <div className="btnrow">
                  <button className="cta primary" disabled={!ok || depth <= 0} onClick={() => setParam({ feed_cavity_mm: depth }, "set feed cavity")}>Set as feed cavity</button>
                  <button className="cta" onClick={skip}>Next →</button>
                </div>
              </>
            )}

            {cur.id === "build-up" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>Raise the build (part) piston to the top so the recoater can spread over it.</div>
                <div className="kv"><span>target · part top</span><span>{fmt(target("part_top_mm"))}</span></div>
                <div className="btnrow">
                  <button className="cta primary" disabled={!ok || target("part_top_mm") === null} onClick={() => call("build up", () => api.move(1, "abs", target("part_top_mm") as number))}>Run this step</button>
                  <button className="cta" onClick={skip}>Skip →</button>
                </div>
              </>
            )}

            {cur.id === "open-feed" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>Lower the feed piston to open a powder cavity of the depth you set.</div>
                <div className="kv"><span>target · feed cavity</span><span>{fmt(target("feed_cavity_mm"))}</span></div>
                <div className="btnrow">
                  <button className="cta primary" disabled={!ok || target("feed_cavity_mm") === null} onClick={() => call("open feed cavity", () => api.move(2, "abs", target("feed_cavity_mm") as number))}>Run this step</button>
                  <button className="cta" onClick={skip}>Skip →</button>
                </div>
              </>
            )}

            {cur.id === "load" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>Pour powder into the open feed cavity until it is full and level with the bed. No motor moves here — this is a hold.</div>
                {paused && <div className="lock">A priming macro is paused for this hold. Resume it once powder is loaded.</div>}
                <div className="btnrow">
                  <button className="cta primary" onClick={skip}>Powder loaded — next →</button>
                  {paused && <button className="cta" disabled={!gates.connected} onClick={() => call("resume priming", api.printResume)}>Resume paused macro</button>}
                </div>
              </>
            )}

            {cur.id === "level" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>Each thick precoat runs three moves in order — the build piston stays fixed. The feed amount in ② is editable (defaults to the saved feed / precoat); change it per coat as the bed fills. Repeat until even.</div>
                <div className="kv">
                  <span>thick precoats</span><span>{target("n_thick_precoats") ?? "—"}</span>
                  <span>feed / precoat</span><span>{fmt(target("thick_feed_mm"))}</span>
                  <span>start (past feed)</span><span>{fmt(target("level_recoat_start_mm"))}</span>
                  <span>spread to</span><span>{fmt(target("level_recoat_end_mm"))}</span>
                </div>
                {/* the primary 3-move precoat sequence, IN ORDER: recoater clear of feed → raise powder
                    → spread. Step ② carries an EDITABLE feed amount (▲ supply / ▼ down) for real control. */}
                <div className="seq">
                  <button className="cta primary" disabled={!ok || target("level_recoat_start_mm") === null} title="① Move the recoater past the feed piston to the start position, clear of the powder about to be raised." onClick={() => call("move to start", () => api.move(4, "abs", target("level_recoat_start_mm") as number))}><b>①</b> Move to start</button>
                  <span className="seq-arrow" aria-hidden="true">→</span>
                  <span className="seq-feed">
                    <b>②</b> Feed
                    <input type="number" inputMode="decimal" value={feedAmt} placeholder={target("thick_feed_mm") != null ? String(target("thick_feed_mm")) : "mm"} onChange={(e) => setFeedAmt(e.target.value)} style={{ width: 64 }} aria-label="feed supply amount (mm)" />
                    <span className="hint" style={{ marginTop: 0 }}>mm</span>
                    <button className="cta primary" disabled={!ok || feedSupplyMm <= 0} title="Raise the feed piston by the amount shown to supply powder above the bed." onClick={() => call("advance feed", () => api.move(2, "rel", -feedSupplyMm))}>▲ supply</button>
                    <button className="cta" disabled={!ok || feedSupplyMm <= 0} title="Lower the feed piston by the amount shown (retract)." onClick={() => call("lower feed", () => api.move(2, "rel", feedSupplyMm))}>▼ down</button>
                  </span>
                  <span className="seq-arrow" aria-hidden="true">→</span>
                  <button className="cta primary" disabled={!ok || target("level_recoat_end_mm") === null} title="③ Sweep the recoater across the bed, dragging the raised powder to fill the runway and build cavity." onClick={() => call("spread", () => api.move(4, "abs", target("level_recoat_end_mm") as number))}><b>③</b> Spread ▶</button>
                </div>
                {/* recoater fine adjustment — tucked away so the sequence stays clear */}
                <details className="params" style={{ marginTop: 16 }}>
                  <summary>fine adjust · recoater jog &amp; rates</summary>
                  <div className="body">
                    <div className="btnrow">
                      <span className="hint" style={{ marginTop: 0, minWidth: 84 }}>recoater jog</span>
                      <input type="number" inputMode="decimal" value={jogStep} onChange={(e) => setJogStep(e.target.value)} style={{ width: 70 }} />
                      <span className="hint" style={{ marginTop: 0 }}>mm</span>
                      <button className="cta" disabled={!ok || n(jogStep) <= 0} onClick={() => call("jog recoater away", () => api.move(4, "rel", n(jogStep)))}>◀ away</button>
                      <button className="cta" disabled={!ok || n(jogStep) <= 0} onClick={() => call("jog recoater home", () => api.move(4, "rel", -n(jogStep)))}>home ▶</button>
                    </div>
                    <div className="btnrow">
                      <span className="hint" style={{ marginTop: 0, minWidth: 84 }}>recoater rate</span>
                      <input type="number" inputMode="decimal" value={rcSpeed} placeholder={am4?.max_speed != null ? String(am4.max_speed) : "mm/s"} disabled={!ok} onChange={(e) => setRcSpeed(e.target.value)} style={{ width: 90 }} />
                      <button className="small" disabled={!ok || rcSpeed === ""} onClick={() => call("set recoater speed", () => api.setAxisMotion(4, { max_speed: Number(rcSpeed) }).then(() => setRcSpeed("")))}>set speed</button>
                      <input type="number" inputMode="decimal" value={rcAccel} placeholder={am4?.max_accel != null ? String(am4.max_accel) : "mm/s²"} disabled={!ok} onChange={(e) => setRcAccel(e.target.value)} style={{ width: 90 }} />
                      <button className="small" disabled={!ok || rcAccel === ""} onClick={() => call("set recoater accel", () => api.setAxisMotion(4, { max_accel: Number(rcAccel) }).then(() => setRcAccel("")))}>set accel</button>
                    </div>
                  </div>
                </details>
              </>
            )}

            {cur.id === "finish" && (
              <>
                <div className="hint" style={{ marginTop: 0 }}>When the bed is evenly primed, capture the primed piston positions. The Print tab then starts from these.</div>
                <div className="btnrow">
                  <button className="cta primary" disabled={!ok} onClick={() => call("capture primed", () => api.primedCapture().then((x) => setPrimed(x.primed)))}>Bed is primed — capture</button>
                </div>
                {primed ? (
                  <>
                    <div className="kv"><span>captured part</span><span>{primed.part_mm} mm</span><span>captured feed</span><span>{primed.feed_mm} mm</span></div>
                    <div className="btnrow"><button className="cta primary" onClick={onPrint}>Priming complete — go to Print →</button></div>
                  </>
                ) : <div className="hint">No primed bed captured yet. The Print tab starts from the captured bed.</div>}
              </>
            )}
          </div>

          <div className="step-nav">
            <button className="small" disabled={step === 0} onClick={() => setStep((x) => Math.max(0, x - 1))}>Back</button>
            <button className="small" disabled={step === WALKTHROUGH_STEPS.length - 1} onClick={skip}>Next</button>
          </div>

          <details className="params">
            <summary>priming parameters</summary>
            <PrimingFields s={s} edit={edit} setEdit={setEdit} ok={ok} save={save} />
            {invalid && <div className="lock">{p?.validation.join("; ")}</div>}
          </details>

          <div className="escape">
            <div className="h">automatic</div>
            <div className="btnrow">
              <button className="cta" disabled={!ok || invalid} onClick={() => { if (window.confirm("Run the full priming routine automatically? It positions the pistons, PAUSES for you to load powder, then levels. Pistons are never homed.")) call("run priming", api.primingRun); }}>RUN PRIMING</button>
              <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
