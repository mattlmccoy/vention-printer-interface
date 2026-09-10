import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { primingSteps, type PrimingSettings } from "../../lib/priming.ts";
import { Elevation } from "../Elevation.tsx";
import { PrimingFields, usePriming } from "../PrimingPanel.tsx";
import type { Call } from "./types.ts";

/** Full-page Priming: the live machine diagram is the centrepiece. LEFT region = the editable
 *  parameters + the plain-language "what this will do" sequence; CENTER region = a large live
 *  Elevation of the pistons and recoater as the routine runs; RIGHT region = RUN / RESUME / ABORT
 *  with the current state, step, and the powder-load HOLD prompt when the routine is paused.
 *  Layout + composition only — every handler and API call is reused from usePriming and the print
 *  controller (run / resume / abort), unchanged. The centre reads real controller telemetry. */
export function PrimingView({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call }) {
  const { p, s, invalid, edit, setEdit, save } = usePriming(call);
  const ok = gates.controllable && !gates.printActive;
  const r = status?.print ?? null;
  const paused = r?.state === "paused";
  const active = r?.state === "running" || r?.state === "paused";
  const label = !status ? "OFFLINE" : (r?.state ?? "idle").toUpperCase();
  const pct = r && r.n_steps ? Math.round((100 * r.step_index) / r.n_steps) : 0;
  const step = r?.current_step?.label ?? "";

  return (
    <div className="view priming-page">
      <section className="region left">
        <div className="h">priming parameters</div>
        <PrimingFields s={s} edit={edit} setEdit={setEdit} ok={ok} save={save} />
        {invalid && <div className="lock">{p?.validation.join("; ")}</div>}
        <div className="kv" style={{ marginTop: 22 }}>
          <span>level passes</span><span>{p?.n_level_passes ?? "—"}</span>
          <span>total steps</span><span>{p?.n_steps ?? "—"}</span>
        </div>
        <div className="h" style={{ marginTop: 28 }}>what this will do</div>
        {s ? (
          <ol className="body" style={{ margin: 0, paddingLeft: 18 }}>
            {primingSteps(s as unknown as PrimingSettings).map((line, i) => <li key={i}>{line}</li>)}
          </ol>
        ) : <div className="hint">loading the priming script…</div>}
        <div className="hint" style={{ marginTop: 18 }}>Run this first, before a print, to prime the bed. It pauses to load powder, then levels. It never homes a piston (that ejects powder).</div>
      </section>

      <section className="region center">
        <div className="h">live machine</div>
        <div className="diagram"><Elevation status={status} partZeroMm={r?.part_zero_mm ?? null} mode="live" /></div>
        <div className="narr">{active ? `priming · ${step || "running"}` : ok ? "in control · idle" : gates.connected ? "read-only" : "not connected"}</div>
      </section>

      <section className="region right">
        <div className="h">run</div>
        <div className="state"><span className="big">{label}</span></div>
        {r?.reason && <div className="hint">{r.reason}</div>}
        <div className="bar"><i style={{ width: `${pct}%` }} /></div>
        <div className="bar-lbl">step {r?.step_index ?? 0} of {r?.n_steps ?? 0}{step ? ` · ${step}` : ""}</div>
        {paused && <div className="lock">Load powder into the feed cavity, then Resume.</div>}
        <div className="actions tight">
          <button className="cta" disabled={!ok || invalid}
            onClick={() => { if (window.confirm("Run the priming SETUP routine? It positions the pistons, then PAUSES for you to load powder before leveling. Pistons are never homed.")) call("run priming", api.primingRun); }}>
            RUN PRIMING
          </button>
          {paused && (
            <button className="cta primary" disabled={!gates.connected} onClick={() => call("resume priming", api.printResume)}>
              Powder loaded — resume
            </button>
          )}
          <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
        </div>
      </section>
    </div>
  );
}
