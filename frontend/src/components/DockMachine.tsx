import { GANTRY_HOME_SIDE, TRAVEL_MM, type AxisNo, type StatusPayload } from "../lib/telemetry.ts";

/** Compact machine diagram purpose-built for the NARROW dock (portrait-ish ~5:4), unlike the wide
 *  Elevation schematic which can't fit a side panel. Gantries (printhead/recoater) ride horizontal
 *  rails up top; build/feed pistons are vertical fill-bins below. Everything is driven by live
 *  telemetry and scaled to each axis's travel; carriages/fills pulse while moving. */
export function DockMachine({ status }: { status: StatusPayload | null }) {
  const t = status?.controller.telemetry ?? null;
  const lim = status?.controller.limits;
  const frac = (a: AxisNo): number => {
    const p = t?.positions[String(a)];
    if (typeof p !== "number") return 0;
    const tmin = lim?.travel_min[String(a)] ?? 0;
    const tmax = lim?.travel_max[String(a)] ?? TRAVEL_MM[a] ?? 100;
    return tmax > tmin ? Math.max(0, Math.min(1, (p - tmin) / (tmax - tmin))) : 0;
  };
  const mv = (a: AxisNo) => (t ? t.motion_complete[String(a)] === false : false);

  // gantry rails span x 52..268; carriage centre measured FROM the home side (printhead homes
  // left, recoater homes right) so position 0 sits at the correct end of each rail.
  const railX0 = 52, railX1 = 268, span = railX1 - railX0;
  const carriageX = (a: 3 | 4) => (GANTRY_HOME_SIDE[a] === "right" ? railX1 - frac(a) * span : railX0 + frac(a) * span);
  const phX = carriageX(3);
  const rcX = carriageX(4);
  // piston bins: vertical, fill grows from the bottom with position
  const binY0 = 132, binY1 = 214, binH = binY1 - binY0;
  const buildFill = frac(1) * binH, feedFill = frac(2) * binH;

  return (
    <svg className="dockdiag" viewBox="0 0 300 244" role="img" aria-label="machine positions">
      <rect className="frame" x="8" y="8" width="284" height="228" rx="6" />
      {/* gantries */}
      <text className="lbl" x="16" y="40">GANTRY</text>
      <line className="rail" x1={railX0} y1="56" x2={railX1} y2="56" />
      <line className="rail" x1={railX0} y1="92" x2={railX1} y2="92" />
      <text className="lbl dim" x="16" y="60">PH</text>
      <text className="lbl dim" x="284" y="96" textAnchor="end">RC</text>
      <rect className={`ph${mv(3) ? " mv" : ""}`} x={phX - 11} y="49" width="22" height="14" rx="2" />
      <rect className={`rc${mv(4) ? " mv" : ""}`} x={rcX - 11} y="85" width="22" height="14" rx="2" />
      {/* bed line */}
      <line className="bed" x1="20" y1="116" x2="280" y2="116" />
      {/* pistons */}
      <rect className="bin" x="56" y={binY0} width="82" height={binH} rx="2" />
      <rect className="bin" x="162" y={binY0} width="82" height={binH} rx="2" />
      <rect className={`build${mv(1) ? " mv" : ""}`} x="58" y={binY1 - buildFill} width="78" height={buildFill} />
      <rect className={`feed${mv(2) ? " mv" : ""}`} x="164" y={binY1 - feedFill} width="78" height={feedFill} />
      <text className="lbl" x="97" y="230" textAnchor="middle">BUILD</text>
      <text className="lbl" x="203" y="230" textAnchor="middle">FEED</text>
      {!t && <text className="lbl dim" x="150" y="120" textAnchor="middle">no telemetry — connect a controller</text>}
    </svg>
  );
}
