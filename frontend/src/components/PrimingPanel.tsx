import { useEffect, useState } from "react";
import { api, type PrimingPayload } from "../lib/api.ts";
import type { Call } from "./views/types.ts";

/** Owns the priming SETUP routine's data + save handler: loads the script's parameters, tracks
 *  pending edits, and PUTs a patch through the same guarded API a print uses. Shared by the
 *  full-page Priming view so the GET/PUT happen exactly once, not once per region. The routine
 *  emits a hold step, so it PAUSES for the operator to load powder; a print Resume continues it. */
export function usePriming(call: Call) {
  const [p, setP] = useState<PrimingPayload | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true;
    api.priming().then((x) => live && setP(x)).catch(() => {});
    return () => { live = false; };
  }, []);
  const s = p?.settings ?? null;
  const invalid = (p?.validation.length ?? 0) > 0;
  const save = () =>
    call("save priming", () => {
      const patch: Record<string, number> = {};
      for (const [k, v] of Object.entries(edit)) if (v !== "") patch[k] = Number(v);
      return api.setPriming(patch).then((np) => { setP(np); setEdit({}); });
    });
  /** PUT a direct numeric patch (e.g. {feed_cavity_mm}) and refresh `p` — used by the Amount step
   *  to commit a computed feed-cavity depth without routing through the text `edit` map. */
  const setParam = (patch: Record<string, number>, label = "set priming") =>
    call(label, () => api.setPriming(patch).then((np) => setP(np)));
  return { p, s, invalid, edit, setEdit, save, setParam };
}

/** The editable priming parameters (feed cavity, part top, level recoat end/start, level passes)
 *  with the save button. State, validation and the save handler come from usePriming; `ok` gates
 *  every input exactly as the print routine editor does. */
export function PrimingFields({ s, edit, setEdit, ok, save }: {
  s: Record<string, number> | null;
  edit: Record<string, string>;
  setEdit: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  ok: boolean;
  save: () => void;
}) {
  const field = (k: string, label: string) => (
    <>
      <span>{label}</span>
      <input type="number" value={edit[k] ?? ""} placeholder={String(s?.[k] ?? "")} disabled={!ok}
        onChange={(e) => setEdit((prev) => ({ ...prev, [k]: e.target.value }))} />
    </>
  );
  return (
    <div className="fields" style={{ marginTop: 0 }}>
      {field("feed_cavity_mm", "feed cavity")}
      {field("part_top_mm", "part top")}
      {field("level_recoat_end_mm", "level recoat end")}
      {field("level_recoat_start_mm", "level start (past feed)")}
      {field("n_level_passes", "level passes")}
      <button className="small" style={{ gridColumn: "1 / -1", justifySelf: "start" }}
        disabled={!ok || Object.keys(edit).length === 0} onClick={save}>save</button>
    </div>
  );
}
