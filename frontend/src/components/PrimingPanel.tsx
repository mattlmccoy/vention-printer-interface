import { useEffect, useState } from "react";
import { api, type PrimingPayload } from "../lib/api.ts";
import type { Gates } from "../lib/format.ts";
import type { Call } from "./views/types.ts";

/** Powder-prep ("priming") routine: edit the script's parameters, preview the cycle/step count,
 *  and run it through the same guarded step engine a print uses (pause/abort/telemetry safety). */
export function PrimingPanel({ gates, call }: { gates: Gates; call: Call }) {
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
        <span>cycles</span><span>{p?.n_cycles ?? "—"}</span>
        <span>steps</span><span>{p?.n_steps ?? "—"}</span>
        <span>feed start</span><span>{s ? `${s.feed_start_mm} mm` : "—"}</span>
        <span>recoat</span><span>{s ? `${s.recoater_end_mm} → ${s.recoater_return_mm} mm` : "—"}</span>
      </div>
      {invalid && <div className="lock">{p?.validation.join("; ")}</div>}
      <details style={{ marginTop: 6 }}>
        <summary>parameters</summary>
        <div className="body row">
          {field("feed_start_mm", "feed start")}
          {field("thick_precoat_layer_mm", "thick layer")}
          {field("thick_precoat_count", "thick count")}
          {field("nominal_feed_thickness_mm", "feed step")}
          {field("recoater_end_mm", "recoat end")}
          {field("recoater_return_mm", "recoat return")}
          <button className="small" disabled={!ok || Object.keys(edit).length === 0} onClick={save}>save</button>
        </div>
      </details>
      <div className="actions tight" style={{ marginTop: 8 }}>
        <button className="cta" disabled={!ok || invalid}
          onClick={() => { if (window.confirm("Run the powder-prep (priming) routine? It spreads powder across the bed until the feed piston is exhausted, then homes the recoater. Pistons are never homed.")) call("run priming", api.primingRun); }}>
          RUN PRIMING
        </button>
        <button className="cta danger" disabled={!gates.connected} onClick={() => call("abort", api.printAbort)}>ABORT</button>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>Run this first, before a print, to prime the bed. It never homes a piston (that ejects powder).</div>
    </>
  );
}
