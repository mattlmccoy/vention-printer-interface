import { useEffect, useState } from "react";
import { api, type PrimingPayload } from "../lib/api.ts";
import type { Gates } from "../lib/format.ts";
import { primingSteps, type PrimingSettings } from "../lib/priming.ts";
import type { Call } from "./views/types.ts";

/** Powder-prep ("priming") SETUP routine: edit the script's parameters, preview the plain-language
 *  sequence and step count, and run it through the same guarded step engine a print uses. The routine
 *  emits a hold step, so it PAUSES for the operator to load powder; a Resume continues it. */
export function PrimingPanel({ gates, call, printState }: { gates: Gates; call: Call; printState?: string }) {
  const ok = gates.controllable && !gates.printActive;
  const [p, setP] = useState<PrimingPayload | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true;
    api.priming().then((x) => live && setP(x)).catch(() => {});
    return () => { live = false; };
  }, []);
  const s = p?.settings;
  const invalid = (p?.validation.length ?? 0) > 0;
  const paused = printState === "paused";
  const save = () =>
    call("save priming", () => {
      const patch: Record<string, number> = {};
      for (const [k, v] of Object.entries(edit)) if (v !== "") patch[k] = Number(v);
      return api.setPriming(patch).then((np) => { setP(np); setEdit({}); });
    });
  const field = (k: string, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" value={edit[k] ?? ""} placeholder={String(s?.[k] ?? "")} disabled={!ok}
        onChange={(e) => setEdit((prev) => ({ ...prev, [k]: e.target.value }))} />
    </>
  );
  return (
    <>
      <div className="kv" style={{ marginTop: 0 }}>
        <span>passes</span><span>{p?.n_level_passes ?? "—"}</span>
        <span>steps</span><span>{p?.n_steps ?? "—"}</span>
      </div>
      {s && (
        <ol className="body" style={{ marginTop: 6, paddingLeft: 18 }}>
          {primingSteps(s as unknown as PrimingSettings).map((line, i) => <li key={i}>{line}</li>)}
        </ol>
      )}
      {invalid && <div className="lock">{p?.validation.join("; ")}</div>}
      <details style={{ marginTop: 6 }}>
        <summary>parameters</summary>
        <div className="body row">
          {field("feed_cavity_mm", "feed cavity")}
          {field("part_top_mm", "part top")}
          {field("level_recoat_end_mm", "level recoat end")}
          {field("level_recoat_return_mm", "level recoat return")}
          {field("n_level_passes", "level passes")}
          <button className="small" disabled={!ok || Object.keys(edit).length === 0} onClick={save}>save</button>
        </div>
      </details>
      <div className="actions tight" style={{ marginTop: 8 }}>
        <button className="cta" disabled={!ok || invalid}
          onClick={() => { if (window.confirm("Run the priming SETUP routine? It positions the pistons, then PAUSES for you to load powder before leveling. Pistons are never homed.")) call("run priming", api.primingRun); }}>
          RUN PRIMING
        </button>
        {paused && (
          <button className="cta" disabled={!gates.connected} onClick={() => call("resume priming", api.printResume)}>
            Powder loaded — resume
          </button>
        )}
        <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>Run this first, before a print, to prime the bed. It pauses to load powder, then levels. It never homes a piston (that ejects powder).</div>
    </>
  );
}
