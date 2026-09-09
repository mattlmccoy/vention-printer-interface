import { layoutElevation } from "../lib/elevation.ts";
import { TRAVEL_MM, type StatusPayload } from "../lib/telemetry.ts";

/** Front elevation of the printer in the style of the lab's wireframe: printhead and recoater
 *  rails on top (carriages move left→right from home), feed and build pistons in the bed
 *  (pistons descend as their position grows). The heater bar rides on the recoater. */
export function Elevation({ status, partExpectedMm, partZeroMm }: { status: StatusPayload | null; partExpectedMm: number; partZeroMm: number | null }) {
  const e = layoutElevation();
  const t = status?.controller.telemetry ?? null;
  const p = (a: number) => t?.positions[String(a)] ?? null;
  const mv = (a: number) => (t ? t.motion_complete[String(a)] === false : false);
  const heater = status?.controller.heater.on ?? null;
  const ph = p(3), rc = p(4), feed = p(2), build = p(1);
  const hcls = heater === true ? "el-heater-on" : heater === false ? "el-heater-off" : "el-heater-unk";
  const powderTop = (well: { y: number; h: number }, mm: number | null) => (mm === null ? well.y + well.h : e.pistonTopY(2, mm));
  return (
    <svg viewBox={`0 0 ${e.vb.w} ${e.vb.h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="printer front elevation">
      <defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" className="el-hatch" strokeWidth="1" /></pattern></defs>
      <rect className="el-frame" x={e.frame.x} y={e.frame.y} width={e.frame.w} height={e.frame.h} />
      <line className="el-frame" x1={e.frame.x} x2={e.frame.x + e.frame.w} y1={e.bed.y - 20} y2={e.bed.y - 20} />
      {/* rails */}
      <text className="el-lbl" x={e.railPh.x + e.railPh.w} y={e.railPh.y - 6} textAnchor="end">PRINTHEAD RAIL 0–{TRAVEL_MM[3]} mm</text>
      <rect className="el-rail" x={e.railPh.x} y={e.railPh.y} width={e.railPh.w} height={e.railPh.h} />
      <text className="el-lbl" x={e.railRc.x + e.railRc.w} y={e.railRc.y - 6} textAnchor="end">RECOATER RAIL 0–{TRAVEL_MM[4]} mm</text>
      <rect className="el-rail" x={e.railRc.x} y={e.railRc.y} width={e.railRc.w} height={e.railRc.h} />
      {/* bed with pistons */}
      <rect x={e.bed.x} y={e.bed.y} width={e.bed.w} height={e.bed.h} fill="url(#hatch)" className="el-frame" />
      {[{ r: e.feed, mm: feed, cls: "el-feed", lbl: "FEED PISTON", axis: 2 }, { r: e.build, mm: build, cls: "el-build", lbl: "BUILD PISTON", axis: 1 }].map(({ r, mm, cls, lbl, axis }) => {
        const top = powderTop(r, mm);
        return (
          <g key={lbl}>
            <rect className="el-well" x={r.x} y={r.y} width={r.w} height={r.h} />
            <rect className="el-powder" x={r.x + 2} y={top} width={r.w - 4} height={Math.max(0, r.y + r.h - top)} />
            {axis === 1 && partZeroMm !== null && mm !== null && mm > partZeroMm && (
              <rect className="el-part" x={r.x + r.w * 0.25} y={e.pistonTopY(1, partZeroMm)} width={r.w * 0.5} height={Math.max(0, e.pistonTopY(1, mm) - e.pistonTopY(1, partZeroMm))} />
            )}
            <rect className={`${cls}${mv(axis) ? " el-moving" : ""}`} x={r.x + 2} y={top - 3} width={r.w - 4} height={5} />
            <text className={`${cls}-t`} x={r.x} y={r.y - 6}>{lbl}  {mm === null ? "—" : `${mm.toFixed(1)} mm`}{axis === 1 && partExpectedMm > 0 ? ` · part ${partExpectedMm.toFixed(1)} mm expected` : ""}{axis === 2 && mm !== null ? ` · ${(TRAVEL_MM[2] - mm).toFixed(1)} mm powder left` : ""}</text>
          </g>
        );
      })}
      {/* carriages */}
      {ph !== null && <g className={mv(3) ? "el-moving" : ""}><rect className="el-ph" x={e.gantryX(3, ph) - 17} y={e.railPh.y - 10} width={34} height={30} rx={2} /><text className="el-ph-t" x={e.gantryX(3, ph) - 17} y={e.railPh.y - 14}>printhead {ph.toFixed(1)}</text></g>}
      {rc !== null && <g className={mv(4) ? "el-moving" : ""}>
        <rect className="el-rc" x={e.gantryX(4, rc) - 23} y={e.railRc.y - 10} width={46} height={30} rx={2} />
        <rect className="el-blade" x={e.gantryX(4, rc) - 23} y={e.railRc.y + 20} width={46} height={4} />
        <rect className={hcls} x={e.gantryX(4, rc) + 25} y={e.railRc.y - 6} width={30} height={16} rx={2} />
        <text className="el-rc-t" x={e.gantryX(4, rc) - 23} y={e.railRc.y + 36}>recoater {rc.toFixed(1)} · heater {heater === null ? "?" : heater ? "ON" : "off"}</text>
      </g>}
      {!t && <text className="el-empty" x={e.vb.w / 2} y={e.vb.h / 2} textAnchor="middle">no telemetry — connect a controller</text>}
    </svg>
  );
}
