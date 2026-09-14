import { useEffect, useState } from "react";
import { api, type PrintSettingsPayload } from "../lib/api.ts";
import type { Gates } from "../lib/format.ts";
import type { Call } from "./views/types.ts";
import { NumberField } from "./NumberField.tsx";
import { Toggle } from "./Toggle.tsx";

/** Edit the print routine (thin precoat, printing multi-pass, postcoat) plus the heater-exposure
 *  inputs, and show the backend-computed IPA exposure readout. The thick precoats live in the
 *  priming routine now, so they are not edited here. Fetches the resolved print_settings, patches
 *  with api.setPrintSettings, and re-reads the exposure from each response. */

interface PhaseDraft { n_layers: number; layer_thickness_mm: number; feed_thickness_mm: number }
interface Draft {
  thin_precoat: PhaseDraft;
  postcoat: PhaseDraft; // N postcoat layers × layer height (just like precoats), when enabled
  printing_feed_thickness_mm: number; // feed advance per printing layer (the powder supply)
  recoater_return_mm: number;
  heater_start_mm: number;
  heater_speed: number; // manual override of the computed exposure sweep speed (unachievable now)
  part_max_mm: number;
  n_jet_passes: number;
  printhead_multipass_return_mm: number;
  printhead_start_mm: number;
  feed_backlash_mm: number;
  purge_dwell_s: number;
  purge_position_mm: number | null;
  purge_mode: string;
  purge_every_n_layers: number;
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
    thin_precoat: phaseOf(plan, "thin_precoat"),
    postcoat: phaseOf(plan, "postcoat"),
    printing_feed_thickness_mm: phaseOf(plan, "printing").feed_thickness_mm,
    recoater_return_mm: n(plan.recoater_return_mm, 350),
    heater_start_mm: n(plan.heater_start_mm, 425),
    heater_speed: n(plan.heater_speed, 50),
    part_max_mm: n(plan.part_max_mm, 72),
    n_jet_passes: n(plan.n_jet_passes, 1),
    printhead_multipass_return_mm: n(plan.printhead_multipass_return_mm, 250),
    printhead_start_mm: n(plan.printhead_start_mm, 250),
    feed_backlash_mm: n(plan.feed_backlash_mm),
    purge_dwell_s: n(plan.purge_dwell_s),
    purge_position_mm: typeof plan.purge_position_mm === "number" ? plan.purge_position_mm : null,
    purge_mode: typeof plan.purge_mode === "string" ? (plan.purge_mode as string) : "per_layer",
    purge_every_n_layers: n(plan.purge_every_n_layers, 5),
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
  const setPh = (key: "thin_precoat" | "postcoat", patch: Partial<PhaseDraft>) => d && setD({ [key]: { ...d[key], ...patch } } as Partial<Draft>);
  const save = () => d && call("set routine", () => {
    const patch = {
      thin_precoat: d.thin_precoat,
      printing: { feed_thickness_mm: d.printing_feed_thickness_mm },
      recoater_return_mm: d.recoater_return_mm,
      heater_start_mm: d.heater_start_mm,
      heater_speed: d.heater_speed,
      part_max_mm: d.part_max_mm,
      n_jet_passes: d.n_jet_passes,
      printhead_multipass_return_mm: d.printhead_multipass_return_mm,
      printhead_start_mm: d.printhead_start_mm,
      feed_backlash_mm: d.feed_backlash_mm,
      purge_dwell_s: d.purge_dwell_s,
      purge_position_mm: d.purge_position_mm,
      purge_mode: d.purge_mode,
      purge_every_n_layers: d.purge_every_n_layers,
      pre_heater_drop_mm: d.pre_heater_drop_mm,
      postcoat_enabled: d.postcoat_enabled,
      postcoat: d.postcoat,
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
      <div className="rp-grid">
        <div className="rp-card">
          <h4>powder handling</h4>
          <div className="rp-row"><span>thin precoat (n × mm)</span><span className="rv"><NumberField value={d.thin_precoat.n_layers} disabled={!ok} style={{ width: 46 }} onChange={(v) => setPh("thin_precoat", { n_layers: v })} /> × <NumberField step="0.1" value={d.thin_precoat.layer_thickness_mm} disabled={!ok} style={{ width: 64 }} onChange={(v) => setPh("thin_precoat", { layer_thickness_mm: v })} /></span></div>
          <div className="rp-row"><span>precoat feed (mm)</span><span className="rv"><NumberField step="0.1" value={d.thin_precoat.feed_thickness_mm} disabled={!ok} onChange={(v) => setPh("thin_precoat", { feed_thickness_mm: v })} /></span></div>
          <div className="rp-row"><span>printing feed (mm)</span><span className="rv"><NumberField step="0.1" value={d.printing_feed_thickness_mm} disabled={!ok} onChange={(v) => setD({ printing_feed_thickness_mm: v })} /></span></div>
          <div className="rp-row"><span>recoater return (mm)</span><span className="rv"><NumberField value={d.recoater_return_mm} disabled={!ok} onChange={(v) => setD({ recoater_return_mm: v })} /></span></div>
          <div className="rp-row"><span title="Anti-backlash: drops the feed piston this much BEFORE the recoater spread, then the post-spread feed-up returns it from below to take up mechanical slop. 0 = off.">feed backlash (mm)</span><span className="rv"><NumberField step="0.1" value={d.feed_backlash_mm} disabled={!ok} onChange={(v) => setD({ feed_backlash_mm: v })} /></span></div>
          <div className="rp-row"><span>postcoat</span><span className="rv"><Toggle checked={d.postcoat_enabled} disabled={!ok} onChange={(v) => setD({ postcoat_enabled: v })} /></span></div>
          {d.postcoat_enabled && <>
            <div className="rp-row"><span title="Number of postcoat layers × the layer height — just like precoats. The part is held; each layer feeds + spreads powder to cap the build.">postcoat (n × mm)</span><span className="rv"><NumberField value={d.postcoat.n_layers} disabled={!ok} style={{ width: 46 }} onChange={(v) => setPh("postcoat", { n_layers: v })} /> × <NumberField step="0.1" value={d.postcoat.layer_thickness_mm} disabled={!ok} style={{ width: 64 }} onChange={(v) => setPh("postcoat", { layer_thickness_mm: v })} /></span></div>
            <div className="rp-row"><span>postcoat feed (mm)</span><span className="rv"><NumberField step="0.1" value={d.postcoat.feed_thickness_mm} disabled={!ok} onChange={(v) => setPh("postcoat", { feed_thickness_mm: v })} /></span></div>
          </>}
          <div className="rp-note">Thick precoats live in the Priming routine, not here.</div>
        </div>

        <div className="rp-card">
          <h4>multipass</h4>
          <div className="rp-row"><span title="prints each layer N times without dropping the build piston">passes / layer</span><span className="rv"><NumberField value={d.n_jet_passes} disabled={!ok} onChange={(v) => setD({ n_jet_passes: v })} /></span></div>
          <div className="rp-row"><span title="Between multipass passes the printhead returns only to here instead of home (saves travel); it still returns home on the last pass.">multipass return (mm)</span><span className="rv"><NumberField value={d.printhead_multipass_return_mm} disabled={!ok} onChange={(v) => setD({ printhead_multipass_return_mm: v })} /></span></div>
          <div className="rp-row"><span title="Where the printhead parks at the start of every print (after the setup homing), before layer 1.">printhead start (mm)</span><span className="rv"><NumberField value={d.printhead_start_mm} disabled={!ok} onChange={(v) => setD({ printhead_start_mm: v })} /></span></div>
        </div>

        <div className="rp-card">
          <h4>heat</h4>
          <div className="rp-row"><span>heater start (mm)</span><span className="rv"><NumberField value={d.heater_start_mm} disabled={!ok} onChange={(v) => setD({ heater_start_mm: v })} /></span></div>
          <div className="rp-row"><span title="Manual recoater sweep speed during the heater pass — overrides the computed exposure sweep (unachievable on current hardware).">heater speed (mm/s)</span><span className="rv"><NumberField step="1" value={d.heater_speed} disabled={!ok} onChange={(v) => setD({ heater_speed: v })} /></span></div>
          <div className="rp-row"><span>pre-heater drop (mm)</span><span className="rv"><NumberField step="0.1" value={d.pre_heater_drop_mm} disabled={!ok} onChange={(v) => setD({ pre_heater_drop_mm: v })} /></span></div>
        </div>

        <div className="rp-card">
          <h4>nozzle purge</h4>
          <div className="rp-row"><span title="Firing is external, so this holds the printhead for this many seconds before a jet pass — a window for the printhead controller to purge. 0 = off.">purge dwell (s)</span><span className="rv"><NumberField step="0.1" value={d.purge_dwell_s} disabled={!ok} style={{ width: 64 }} onChange={(v) => setD({ purge_dwell_s: v })} /></span></div>
          <div className="rp-row"><span title="Absolute printhead position (mm) where the purge dwell holds. Blank = use the printhead start position.">purge position (mm)</span><span className="rv"><input type="text" style={{ width: 80, textAlign: "right" }} placeholder={`${d.printhead_start_mm} (start)`} value={d.purge_position_mm ?? ""} disabled={!ok} onChange={(e) => setD({ purge_position_mm: e.target.value === "" ? null : Number(e.target.value) })} /></span></div>
          <div className="rp-row" style={{ alignItems: "flex-start" }}><span>frequency</span><span className="seg">{([["every_pass", "every pass"], ["per_layer", "per layer"], ["every_n_layers", "every N"]] as const).map(([m, lbl]) => <button key={m} type="button" className={`small${d.purge_mode === m ? " on" : ""}`} aria-pressed={d.purge_mode === m} disabled={!ok} onClick={() => setD({ purge_mode: m })}>{lbl}</button>)}</span></div>
          {d.purge_mode === "every_n_layers" && <div className="rp-row"><span>N (layers)</span><span className="rv"><NumberField value={d.purge_every_n_layers} disabled={!ok} style={{ width: 56 }} onChange={(v) => setD({ purge_every_n_layers: v })} /></span></div>}
        </div>

        <div className="rp-card">
          <h4>carbon &amp; exposure</h4>
          <div className="rp-row"><span>target carbon (wt)</span><span className="rv"><NumberField step="0.01" value={d.target_carbon_wt} disabled={!ok} onChange={(v) => setD({ target_carbon_wt: v })} /></span></div>
          <div className="rp-row"><span>part area (mm²)</span><span className="rv"><NumberField value={d.part_area_mm2} disabled={!ok} onChange={(v) => setD({ part_area_mm2: v })} /></span></div>
          <div className="rp-row"><span>heater power (W)</span><span className="rv"><NumberField value={d.heater_section_power_w} disabled={!ok} onChange={(v) => setD({ heater_section_power_w: v })} /></span></div>
          <div className="rp-readout">IPA exposure — {exp ? <>energy <b>{rnd(exp.energy_j)} J</b> · dwell <b>{rnd(exp.time_s)} s</b> · sweep <b>{rnd(exp.sweep_speed_mm_s)} mm/s</b></> : "unavailable"}</div>
        </div>

        <div className="rp-card">
          <h4>finish</h4>
          <div className="rp-row"><span title="FINISH drives the part cylinder to this absolute position — the spill-safe depth.">part drop-to (mm)</span><span className="rv"><NumberField value={d.part_max_mm} disabled={!ok} onChange={(v) => setD({ part_max_mm: v })} /></span></div>
          <div className="rp-note">Absolute position the part cylinder is driven to when the print finishes.</div>
        </div>
      </div>
      <div className="actions one tight" style={{ marginTop: 12 }}>
        <button className="cta" disabled={!ok || !dirty} onClick={save}>SET ROUTINE</button>
      </div>
      {!ok && <div className="lock">{gates.printActive ? "print in progress — parameters locked" : gates.connected ? "read-only · take control from the connection pill" : "connect a controller to edit"}</div>}
    </>
  );
}
