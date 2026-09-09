import { fmtSecs } from "../lib/format.ts";

export function HeaterRing({ on, onS, maxS }: { on: boolean | null; onS: number; maxS: number }) {
  const C = 2 * Math.PI * 36;
  const frac = maxS > 0 ? Math.min(onS / maxS, 1) : 0;
  return (
    <div className="ring" aria-label="heater on-time">
      <svg viewBox="0 0 84 84"><circle className="c" cx="42" cy="42" r="36" />{on && <circle className="p" cx="42" cy="42" r="36" strokeDasharray={C} strokeDashoffset={C * (1 - frac)} />}</svg>
      <div className="t">{on === null ? "?" : on ? fmtSecs(onS) : "off"}</div>
    </div>
  );
}
