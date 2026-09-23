import { useEffect, useState, type ReactElement } from "react";
import { api } from "../../lib/api.ts";
import { fmtMmAuto, type Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { fillDepthMm, cavityFillPct, thickPrecoatFeedMm, FEED_TRAVEL_MM, type FillSource } from "../../lib/powder.ts";
import { WALKTHROUGH_STEPS, stepHeading } from "../../lib/walkthrough.ts";
import { primingBudget, primingStatusLine, stepMoves, type StepMove } from "../../lib/priming_page.ts";
import type { PrimeStatus } from "../../lib/print_flow.ts";
import { PrimingFields, usePriming } from "../PrimingPanel.tsx";
import type { Call } from "./types.ts";

/** Priming tab: a Steps rail (left) + the current step (right). Every step uses the same shape —
 *  the step-5 pattern — a numbered row of the physical moves it runs, each target editable inline
 *  and run in place. Pinned on every step: the powder budget (needed vs in the feed) and ONE
 *  status line for the machine/macro (no banners appearing and disappearing); Back/Next pinned at
 *  the bottom. The walkthrough shows its own position ("Step 3 of 6"), never the macro's raw count.
 *  RUN PRIMING (auto) + ABORT stay available below. */
const STEP_SUB: Record<string, string> = {
  amount: "feed-cavity target",
  "build-up": "raise build to the bed",
  "open-feed": "lower feed to load",
  load: "manual — hold to confirm",
  level: "pack the bed",
  finish: "capture & go to Print",
};
const STEP_INTRO: Record<string, string> = {
  amount: "How much powder the feed cavity must hold: the print's feed, the thick precoats' feed and a margin.",
  "build-up": "Raise the build (part) piston to the top so the recoater can spread over it.",
  "open-feed": "Lower the feed piston to open a powder cavity of the depth you set.",
  load: "Pour powder into the open feed cavity until it is full and level with the bed. No motor moves here.",
  level: "Each thick precoat runs these three moves in order; the build piston stays fixed. Change the feed per coat as the bed fills, and repeat until the bed is even.",
  finish: "When the bed is evenly primed, capture the primed piston positions. The Print tab starts from them — for this plan only.",
};
const LEVEL_STEP = WALKTHROUGH_STEPS.findIndex((w) => w.id === "level");
const CIRCLED = ["①", "②", "③", "④"];

export function PrimingView({ status, gates, call, onJob, onPrint }: { status: StatusPayload | null; gates: Gates; call: Call; onJob: () => void; onPrint: () => void }) {
  const { p, s, invalid, edit, setEdit, save, setParam } = usePriming(call);
  const ok = gates.controllable && !gates.printActive;
  const r = status?.print ?? null;

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
  const [feedDemandMm, setFeedDemandMm] = useState<number | null>(null); // the print's feed consumption
  const [primed, setPrimed] = useState<{ part_mm: number; feed_mm: number; captured_at: number } | null>(null);
  const [primeStatus, setPrimeStatus] = useState<PrimeStatus | null>(null);
  const [targets, setTargets] = useState<Record<string, string>>({}); // inline target edits, by setting key
  const [jogStep, setJogStep] = useState("20"); // recoater jog step (mm) for the leveling step
  const [feedAmt, setFeedAmt] = useState(""); // per-coat feed amount (mm); blank = saved default
  const [rcSpeed, setRcSpeed] = useState("");
  const [rcAccel, setRcAccel] = useState("");
  const am4 = status?.axis_motion?.["4"]; // recoater current max speed/accel

  useEffect(() => {
    let live = true;
    api.printSettings().then((x) => live && setFeedDemandMm(x.feed_demand_mm ?? null)).catch(() => {});
    return () => { live = false; };
  }, [status?.job?.path]);
  const loadPrimed = () => api.primed().then((x) => { setPrimed(x.primed); setPrimeStatus(x.status ?? null); }).catch(() => {});
  useEffect(() => { loadPrimed(); }, []);

  const n = (v: string) => { const x = Number(v); return Number.isFinite(x) ? x : 0; };
  const target = (k: string): number | null => (s ? s[k] ?? null : null);
  const thickFeedMm = thickPrecoatFeedMm(target("n_thick_precoats"), target("thick_feed_mm"));
  const depth = fillDepthMm({ source, feedDemandMm: feedDemandMm ?? 0, thickPrecoatFeedMm: thickFeedMm, nLayers: n(nLayers), layerThicknessMm: n(layerThicknessMm), manualDepthMm: n(manualDepthMm), marginMm: n(marginMm) });
  const pct = cavityFillPct(depth);
  const fmt = (mm: number | null) => fmtMmAuto(mm);

  // pinned: powder budget + one status line
  const tel = status?.controller?.telemetry;
  const budget = primingBudget({
    feedDemandMm, thickFeedMm, marginMm: n(marginMm),
    feedPosMm: tel?.positions?.["2"] ?? null, feedReferenced: tel?.referenced?.["2"] === true,
    afterPrecoats: step >= LEVEL_STEP,
  });
  const barPct = (mm: number | null) => (mm == null ? 0 : Math.min(100, (100 * mm) / FEED_TRAVEL_MM));
  const line = primingStatusLine(r, gates.connected);
  const capture = () => call("capture primed", () => api.primedCapture().then((x) => { setPrimed(x.primed); setPrimeStatus(x.status ?? null); }));

  const num = (v: string, set: (s: string) => void, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" inputMode="decimal" value={v} onChange={(e) => set(e.target.value)} />
    </>
  );
  const srcBtn = (value: FillSource, label: string) => (
    <button className={`small${source === value ? " on" : ""}`} aria-pressed={source === value} onClick={() => setSource(value)}>{label}</button>
  );
  const next = () => setStep((x) => Math.min(WALKTHROUGH_STEPS.length - 1, x + 1));
  const feedOverride = n(feedAmt) > 0 ? n(feedAmt) : null;

  // One numbered move: its target inline and a Run button.
  const moveRow = (m: StepMove) => {
    const isFeedCoat = m.key === "thick_feed_mm";
    const shown = isFeedCoat ? feedAmt : (targets[m.key] ?? (m.value == null ? "" : String(m.value)));
    // The target the operator typed (absolute moves) stays in the field — it is exactly what Run
    // moves to (WYSIWYG) and it is saved to the priming settings on blur/Enter. Never cleared on
    // blur: clicking Run blurs first, and a cleared edit would let the click run the OLD target.
    const edited = !isFeedCoat && targets[m.key] !== undefined && targets[m.key] !== "" && Number.isFinite(Number(targets[m.key]))
      ? Number(targets[m.key]) : null;
    const commit = () => { if (edited != null && edited !== target(m.key)) setParam({ [m.key]: edited }, `set ${m.key}`); };
    const runValue = edited ?? m.value;
    return (
      <span className="seq-feed" key={m.n}>
        <b>{CIRCLED[m.n - 1]}</b> {m.label}
        <input type="number" inputMode="decimal" style={{ width: 72 }} aria-label={`${m.label} (mm)`}
          value={shown} placeholder={isFeedCoat && target("thick_feed_mm") != null ? String(target("thick_feed_mm")) : "mm"}
          onChange={(e) => (isFeedCoat ? setFeedAmt(e.target.value) : setTargets((t) => ({ ...t, [m.key]: e.target.value })))}
          onBlur={() => { if (!isFeedCoat) commit(); }} onKeyDown={(e) => { if (e.key === "Enter" && !isFeedCoat) commit(); }} />
        <span className="hint" style={{ marginTop: 0 }}>mm</span>
        <button className="cta primary" disabled={!ok || runValue == null}
          title={edited != null ? "saves this target, then runs the move" : undefined}
          onClick={() => { if (edited != null) commit(); call(m.label, () => api.move(m.axis, m.mode, runValue as number)); }}>
          {isFeedCoat ? "▲ supply" : "Run"}
        </button>
        {isFeedCoat && <button className="cta" disabled={!ok || m.value == null} title="Lower the feed piston by the amount shown (retract)." onClick={() => call("lower feed", () => api.move(2, "rel", -(m.value as number)))}>▼ down</button>}
      </span>
    );
  };
  const moves = stepMoves(cur.id, s, feedOverride);
  const arrow = (k: string) => <span className="seq-arrow" aria-hidden="true" key={k}>→</span>;
  const row = (items: ReactElement[]) => <div className="seq">{items.flatMap((el, i) => (i ? [arrow(`a${i}`), el] : [el]))}</div>;

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

        <div className="card prime-card">
          <div className="prime-pinned">
            <div className="prime-budget" data-tip="Feed powder needed vs. the powder column in the feed piston now (its depth below flush). Before the thick precoats the need includes their feed and your margin.">
              <div className="bar"><i className={`b-${budget.tone}`} style={{ width: `${barPct(budget.haveMm)}%` }} />{budget.needMm != null && <span className="need-mark" style={{ left: `${barPct(budget.needMm)}%` }} />}</div>
              <div className={`bar-lbl tone-${budget.tone}`}>powder · {budget.text}</div>
            </div>
            <div className={`prime-status tone-${line.tone}`} role="status">
              <span className="txt">{line.text}</span>
              {line.actions.includes("resume") && <button className="small" disabled={!gates.connected} onClick={() => call("resume priming", api.printResume)}>Resume</button>}
              {line.actions.includes("capture") && <button className="small primary" disabled={!gates.controllable} onClick={() => { capture().then(() => setStep(WALKTHROUGH_STEPS.length - 1)); }}>Capture primed bed</button>}
              {line.actions.includes("abort") && <button className="small" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>Abort</button>}
            </div>
          </div>

          <h3>{stepHeading(step)}</h3>
          <div className="grid-gap cap">
            <div className="hint" style={{ marginTop: 0 }}>{STEP_INTRO[cur.id]}</div>

            {cur.id === "amount" && (
              <>
                <div className="seg">{srcBtn("job", "paired to job")}{srcBtn("layers", "layers × feed")}{srcBtn("depth", "depth (mm)")}</div>
                {source === "job" && (
                  <>
                    <div className="fields">
                      <span>selected job</span><span className="ro">{status?.job ? status.job.name : "none selected"}</span>
                      <span data-tip="Feed the print consumes: feed advance per layer × layers (thin precoats + printing + postcoat if on). The feed rises more than the build drops each layer.">{status?.job ? "job feed needed" : "print feed needed"}</span><span className="ro">{fmt(feedDemandMm)}</span>
                      <span data-tip="Priming spends this before the print: thick precoats × feed per precoat.">thick precoats' feed</span><span className="ro">{target("n_thick_precoats") ?? "—"} × {fmt(target("thick_feed_mm"))} = {fmt(thickFeedMm)}</span>
                      {num(marginMm, setMarginMm, "margin")}
                    </div>
                    {!status?.job && <div className="hint">No sliced job is loaded, so this uses the current print settings. Pick a job for an exact amount: <button className="linklike" onClick={onJob}>open the Job tab →</button></div>}
                  </>
                )}
                {source === "layers" && (
                  <>
                    <div className="fields">{num(nLayers, setNLayers, "layers")}{num(layerThicknessMm, setLayerThicknessMm, "feed per layer")}{num(marginMm, setMarginMm, "margin")}</div>
                    <div className="hint">Use the FEED advance per layer (larger than the layer thickness), count the precoat layers too, and add the thick precoats' feed to the margin.</div>
                  </>
                )}
                {source === "depth" && <div className="fields">{num(manualDepthMm, setManualDepthMm, "depth")}</div>}
                {row([
                  <span className="seq-feed" key="d"><b>①</b> fill depth <b className="num">{depth.toFixed(1)} mm</b><span className="hint" style={{ marginTop: 0 }}>{pct}% of {FEED_TRAVEL_MM} mm travel</span></span>,
                  <span className="seq-feed" key="s"><b>②</b> <button className="cta primary" disabled={!ok || depth <= 0} onClick={() => setParam({ feed_cavity_mm: depth }, "set feed cavity")}>Set as feed cavity</button><span className="hint" style={{ marginTop: 0 }}>saved: {fmt(target("feed_cavity_mm"))}</span></span>,
                ])}
              </>
            )}

            {(cur.id === "build-up" || cur.id === "open-feed") && row(moves.map(moveRow))}

            {cur.id === "load" && row([
              <span className="seq-feed" key="p"><b>①</b> pour powder until full and level</span>,
              <span className="seq-feed" key="c"><b>②</b> <button className="cta primary" onClick={next}>Powder loaded ✓</button></span>,
            ])}

            {cur.id === "level" && (
              <>
                <div className="kv" style={{ marginTop: 0 }}>
                  <span>thick precoats</span><span>{target("n_thick_precoats") ?? "—"} × {fmt(target("thick_feed_mm"))} feed</span>
                </div>
                {row(moves.map(moveRow))}
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
                {row([
                  <span className="seq-feed" key="c"><b>①</b> <button className="cta primary" disabled={!ok} onClick={capture}>Bed is primed — capture</button></span>,
                  <span className="seq-feed" key="g"><b>②</b> <button className="cta primary" disabled={!primed} onClick={onPrint}>Go to Print →</button></span>,
                ])}
                {primed ? (
                  <div className="kv">
                    <span>captured part</span><span>{fmtMmAuto(primed.part_mm)}</span>
                    <span>captured feed</span><span>{fmtMmAuto(primed.feed_mm)}</span>
                    <span>for the print</span><span className={primeStatus?.state === "ready" ? "" : "warn-text"}>{primeStatus?.reason ?? "the operator didn't report which plan"}</span>
                  </div>
                ) : <div className="hint">No primed bed captured yet. The Print tab starts from the captured bed.</div>}
              </>
            )}
          </div>

          <div className="step-nav prime-nav">
            <button className="small" disabled={step === 0} onClick={() => setStep((x) => Math.max(0, x - 1))}>Back</button>
            <span className="hint" style={{ marginTop: 0 }}>{step + 1} / {WALKTHROUGH_STEPS.length}</span>
            <button className="small" disabled={step === WALKTHROUGH_STEPS.length - 1} onClick={next}>Next</button>
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
