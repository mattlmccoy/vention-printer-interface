import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { pistonMaxPatch, type PistonField } from "../../lib/pistons.ts";
import type { Call } from "./types.ts";

const STEPS = [0.1, 1, 5, 10] as const;

/** One piston's jog + set-max control. Jog DOWN to the physical stop, then "Set current as max" —
 *  it records the position as this piston's usable travel (per cylinder). The build max bounds how
 *  deep a build may go (print validation); feed defaults to the same range. */
function Piston({ axis, name, field, status, ok, call, plan, onPlan }: {
  axis: 1 | 2; name: string; field: PistonField; status: StatusPayload | null; ok: boolean;
  call: Call; plan: Record<string, unknown> | null; onPlan: (p: Record<string, unknown>) => void;
}) {
  const [step, setStep] = useState<number>(1);
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(axis)];
  const unref = t?.referenced?.[String(axis)] === false;
  const moving = t ? t.motion_complete[String(axis)] === false : false;
  const max = typeof plan?.[field] === "number" ? (plan[field] as number) : null;

  const jog = (sign: 1 | -1) => call(`jog ${name}`, () => api.move(axis, "rel", sign * step));
  const home = () => {
    if (window.confirm(`Home the ${name} piston? This drives it fully UP (0 mm = flush) and EJECTS any powder in the cylinder.`))
      call(`home ${name}`, () => api.home([axis]));
  };
  const setMax = () => {
    if (typeof pos !== "number") return;
    if (unref) { window.alert("Home (reference) the piston first so its position is real."); return; }
    if (!window.confirm(`Set ${pos.toFixed(1)} mm as the ${name} piston's max travel? Jog it to the physical stop first.`)) return;
    call(`set ${name} max`, () => api.setPrintSettings(pistonMaxPatch(field, pos)).then((r) => onPlan(r.plan as Record<string, unknown>)));
  };

  return (
    <div className="card">
      <h3>{name} piston <span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>axis {axis}</span></h3>
      <div className="kv" style={{ marginTop: 0 }}>
        <span>position</span>
        <span className="v">{unref ? <b className="unref">unref</b> : typeof pos === "number" ? `${pos.toFixed(1)} mm` : "—"}{moving ? " · moving" : ""}</span>
        <span>max travel</span>
        <span className="v">{max !== null ? `${max.toFixed(1)} mm` : "—"}</span>
      </div>
      <div className="stepper" style={{ marginTop: 10 }}>step {STEPS.map((s) => <button key={s} className={s === step ? "on" : ""} onClick={() => setStep(s)}>{s} mm</button>)}</div>
      <div className="jog" style={{ marginTop: 8 }}>
        <button disabled={!ok} onClick={() => jog(-1)}>▲ UP</button>
        <button disabled={!ok} onClick={() => jog(1)}>▼ DOWN</button>
        <button className="home" disabled={!ok} data-tip={`home the ${name} piston — EJECTS POWDER (drives it fully up / flush)`} onClick={home}>⌂</button>
      </div>
      <div className="actions" style={{ marginTop: 10 }}>
        <button className="cta primary" disabled={!ok || typeof pos !== "number" || unref} onClick={setMax}>
          Set current as max{typeof pos === "number" && !unref ? ` (${pos.toFixed(1)} mm)` : ""}
        </button>
      </div>
      <div className="hint" style={{ marginTop: 10 }}>
        Jog <b>DOWN</b> to the physical stop, then set it — this becomes the piston's usable range for the current cylinder. A build deeper than the <b>build</b> max is blocked before it under-builds.
      </div>
    </div>
  );
}

/** Top-level Settings tab. First section: per-cylinder piston travel (jog + set max). More machine
 *  settings (backlash calibration, then the migrated Setup sections) land here next. */
export function SettingsView({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call }) {
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { api.printSettings().then((r) => setPlan(r.plan as Record<string, unknown>)).catch(() => undefined); }, []);
  const ok = gates.controllable && !gates.printActive;
  const lock = !gates.controllable
    ? (gates.connected ? "read-only — take control from the connection pill to jog" : "connect + take control to jog the pistons")
    : gates.printActive ? "a print is running — piston jog is locked" : null;

  return (
    <div className="view fixed-page">
      <div className="sec-h">pistons — per-cylinder travel</div>
      {lock && <div className="lock" style={{ marginBottom: 10 }}>{lock}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
        <Piston axis={1} name="build" field="build_piston_max_mm" status={status} ok={ok} call={call} plan={plan} onPlan={setPlan} />
        <Piston axis={2} name="feed" field="feed_piston_max_mm" status={status} ok={ok} call={call} plan={plan} onPlan={setPlan} />
      </div>
    </div>
  );
}
