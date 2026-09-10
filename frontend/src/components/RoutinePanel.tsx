import { useEffect, useState } from "react";
import { api, type PrintSettingsPayload } from "../lib/api.ts";
import type { Gates } from "../lib/format.ts";
import type { Call } from "./views/types.ts";
import { NumberField } from "./NumberField.tsx";

/** Edit the 4-phase print routine (thick/thin precoat, printing multi-pass, postcoat) plus the
 *  heater-exposure inputs, and show the backend-computed IPA exposure readout. Fetches the resolved
 *  print_settings, patches with api.setPrintSettings, and re-reads the exposure from each response. */

interface PhaseDraft { n_layers: number; layer_thickness_mm: number; feed_thickness_mm: number }
interface Draft {
  thick_precoat: PhaseDraft;
  thin_precoat: PhaseDraft;
  printing_feed_thickness_mm: number; // feed advance per printing layer (the powder supply)
  recoater_return_mm: number;
  heater_start_mm: number;
  part_max_mm: number;
  n_jet_passes: number;
  pre_heater_drop_mm: number;
  postcoat_enabled: boolean;
  target_carbon_wt: number;
  part_area_mm2: number;
  heater_section_power_w: number;
}

function n(v: unknown, fb = 0): number { return typeof v === "number" && Number.isFinite(v) ? v : fb; }
function rnd(v: number, d = 2): number { return Number.isFinite(v) ? Number(v.toFixed(d)) : 0; }
function phaseOf(plan: Record<string, unknown>, key: string): PhaseDraft {
  const p = (plan[key] ?? {}) as Record<string, unknown>;
  return { n_layers: n(p.n_layers), layer_thickness_mm: n(p.layer_thickness_mm), feed_thickness_mm: n(p.feed_thickness_mm) };
}
function readDraft(plan: Record<string, unknown>): Draft {
  return {
    thick_precoat: phaseOf(plan, "thick_precoat"),
    thin_precoat: phaseOf(plan, "thin_precoat"),
    printing_feed_thickness_mm: phaseOf(plan, "printing").feed_thickness_mm,
    recoater_return_mm: n(plan.recoater_return_mm, 350),
    heater_start_mm: n(plan.heater_start_mm, 425),
    part_max_mm: n(plan.part_max_mm, 75),
    n_jet_passes: n(plan.n_jet_passes, 1),
    pre_heater_drop_mm: n(plan.pre_heater_drop_mm),
    postcoat_enabled: typeof plan.postcoat_enabled === "boolean" ? plan.postcoat_enabled : true,
    target_carbon_wt: n(plan.target_carbon_wt),
    part_area_mm2: n(plan.part_area_mm2),
    heater_section_power_w: n(plan.heater_section_power_w),
  };
}

export function RoutinePanel({ gates, call }: { gates: Gates; call: Call }) {
  const [p, setP] = useState<PrintSettingsPayload | null>(null);
  const [d, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let live = true;
    api.printSettings().then((x) => { if (live) { setP(x); setDraft(readDraft(x.plan)); } }).catch(() => {});
    return () => { live = false; };
  }, [gates.reachable]);
  const ok = gates.controllable && !gates.printActive;
  const setD = (patch: Partial<Draft>) => d && (setDraft({ ...d, ...patch }), setDirty(true));
  const setPh = (key: "thick_precoat" | "thin_precoat", patch: Partial<PhaseDraft>) => d && setD({ [key]: { ...d[key], ...patch } } as Partial<Draft>);
  const save = () => d && call("set routine", () => {
    const patch = {
      thick_precoat: d.thick_precoat,
      thin_precoat: d.thin_precoat,
      printing: { feed_thickness_mm: d.printing_feed_thickness_mm },
      recoater_return_mm: d.recoater_return_mm,
      heater_start_mm: d.heater_start_mm,
      part_max_mm: d.part_max_mm,
      n_jet_passes: d.n_jet_passes,
      pre_heater_drop_mm: d.pre_heater_drop_mm,
      postcoat_enabled: d.postcoat_enabled,
      target_carbon_wt: d.target_carbon_wt,
      part_area_mm2: d.part_area_mm2,
      heater_section_power_w: d.heater_section_power_w,
    };
    return api.setPrintSettings(patch).then((np) => { setP(np); setDraft(readDraft(np.plan)); setDirty(false); });
  });
  if (!p || !d) return <div className="hint">loading routine…</div>;
  const exp = p.exposure;
  return (
    <>
      <div className="fields" style={{ marginTop: 0, maxWidth: "none" }}>
        <span>thick precoat</span>
        <label className="row"><NumberField value={d.thick_precoat.n_layers} disabled={!ok} style={{ width: 64 }} onChange={(v) => setPh("thick_precoat", { n_layers: v })} /> × <NumberField step="0.1" value={d.thick_precoat.layer_thickness_mm} disabled={!ok} style={{ width: 72 }} onChange={(v) => setPh("thick_precoat", { layer_thickness_mm: v })} /> mm · feed <NumberField step="0.1" value={d.thick_precoat.feed_thickness_mm} disabled={!ok} style={{ width: 72 }} onChange={(v) => setPh("thick_precoat", { feed_thickness_mm: v })} /> mm</label>
        <span>thin precoat</span>
        <label className="row"><NumberField value={d.thin_precoat.n_layers} disabled={!ok} style={{ width: 64 }} onChange={(v) => setPh("thin_precoat", { n_layers: v })} /> × <NumberField step="0.1" value={d.thin_precoat.layer_thickness_mm} disabled={!ok} style={{ width: 72 }} onChange={(v) => setPh("thin_precoat", { layer_thickness_mm: v })} /> mm · feed <NumberField step="0.1" value={d.thin_precoat.feed_thickness_mm} disabled={!ok} style={{ width: 72 }} onChange={(v) => setPh("thin_precoat", { feed_thickness_mm: v })} /> mm</label>
        <span>printing feed</span><span className="row"><NumberField step="0.1" value={d.printing_feed_thickness_mm} disabled={!ok} onChange={(v) => setD({ printing_feed_thickness_mm: v })} /> mm / layer</span>
        <span>recoater return</span><span className="row"><NumberField value={d.recoater_return_mm} disabled={!ok} onChange={(v) => setD({ recoater_return_mm: v })} /> mm</span>
        <span>heater start</span><span className="row"><NumberField value={d.heater_start_mm} disabled={!ok} onChange={(v) => setD({ heater_start_mm: v })} /> mm</span>
        <span>part max</span><span className="row"><NumberField value={d.part_max_mm} disabled={!ok} onChange={(v) => setD({ part_max_mm: v })} /> mm</span>
        <span>jet passes</span><span className="row"><NumberField value={d.n_jet_passes} disabled={!ok} onChange={(v) => setD({ n_jet_passes: v })} /></span>
        <span>pre-heater drop</span><span className="row"><NumberField step="0.1" value={d.pre_heater_drop_mm} disabled={!ok} onChange={(v) => setD({ pre_heater_drop_mm: v })} /> mm</span>
        <span>postcoat</span><label className="row"><input type="checkbox" checked={d.postcoat_enabled} disabled={!ok} onChange={(e) => setD({ postcoat_enabled: e.target.checked })} /> enabled</label>
        <span>target carbon</span><span className="row"><NumberField step="0.01" value={d.target_carbon_wt} disabled={!ok} onChange={(v) => setD({ target_carbon_wt: v })} /> wt</span>
        <span>part area</span><span className="row"><NumberField value={d.part_area_mm2} disabled={!ok} onChange={(v) => setD({ part_area_mm2: v })} /> mm²</span>
        <span>heater power</span><span className="row"><NumberField value={d.heater_section_power_w} disabled={!ok} onChange={(v) => setD({ heater_section_power_w: v })} /> W</span>
      </div>
      <div className="kv" style={{ marginTop: 10 }}>
        <span>IPA exposure</span><span>{exp ? `energy ${rnd(exp.energy_j)} J · dwell ${rnd(exp.time_s)} s · sweep ${rnd(exp.sweep_speed_mm_s)} mm/s` : "exposure unavailable"}</span>
      </div>
      <div className="actions one tight" style={{ marginTop: 8 }}>
        <button className="cta" disabled={!ok || !dirty} onClick={save}>SET ROUTINE</button>
      </div>
      {!ok && <div className="lock">{gates.printActive ? "print in progress — parameters locked" : gates.connected ? "read-only · take control from the connection pill" : "connect a controller to edit"}</div>}
    </>
  );
}
