import { useRef } from "react";
import { layoutElevation } from "../lib/elevation.ts";
import { markerClass, pistonArrow, type DiagramMode } from "../lib/diagram.ts";
import type { StatusPayload } from "../lib/telemetry.ts";

/** Front elevation of the printer: two rails with carriages on top, feed and build pistons in
 *  the bed (pistons descend as their position grows), heater bar on the recoater. Kept quiet:
 *  four captions, no numbers — the readout row under it carries the values.
 *  `mode` styles the axis markers: "live" keeps each axis colour (solid), "model" draws them
 *  as a violet preview ghost. Per-axis motion drives the moving pulse either way. */
export function Elevation({
  status,
  partZeroMm,
  mode = "live",
  onNudge,
  nudgeStepMm = 1,
  recoaterStepMm = 20,
  controlsEnabled = true,
}: {
  status: StatusPayload | null;
  partZeroMm: number | null;
  mode?: DiagramMode;
  /** undefined => render NO controls (read-only diagram for Print/Job/Runs). */
  onNudge?: (axis: number, deltaMm: number) => void;
  nudgeStepMm?: number;
  recoaterStepMm?: number;
  /** false => controls render greyed and non-interactive. */
  controlsEnabled?: boolean;
}) {
  const e = layoutElevation();
  // One in-SVG accessible nudge button: rounded hit-rect + centered glyph. Scales with the viewBox.
  // `enabled` is per-button so a nudge is greyed while ITS axis is moving — a relative move is
  // refused mid-motion by the controller (409), so we don't offer it rather than error.
  const ctl = (key: string, cx: number, cy: number, glyph: string, label: string, axis: number, delta: number, enabled: boolean) => {
    const en = enabled;
    const fire = () => onNudge?.(axis, delta);
    const s = 18;
    return (
      <g
        key={key}
        className="el-ctl"
        role="button"
        tabIndex={en ? 0 : -1}
        aria-label={label}
        aria-disabled={en ? undefined : true}
        onClick={en ? fire : undefined}
        onKeyDown={en ? (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fire(); } } : undefined}
      >
        <rect x={cx - s / 2} y={cy - s / 2} width={s} height={s} rx={4} />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central">{glyph}</text>
      </g>
    );
  };
  const prevPos = useRef<Record<number, number | null>>({ 1: null, 2: null });
  const t = status?.controller.telemetry ?? null;
  const p = (a: number) => t?.positions[String(a)] ?? null;
  const mv = (a: number) => (t ? t.motion_complete[String(a)] === false : false);
  const mk = (a: number) => markerClass(mode, mv(a));
  const heater = status?.controller.heater.on ?? null;
  const ph = p(3), rc = p(4), feed = p(2), build = p(1);
  const hcls = heater === true ? "el-heater-on" : heater === false ? "el-heater-off" : "el-heater-unk";
  const top = (mm: number | null, r: { y: number; h: number }) => (mm === null ? r.y + r.h : e.pistonTopY(2, mm));
  return (
    <svg viewBox={`0 0 ${e.vb.w} ${e.vb.h}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="printer front elevation">
      <rect className="el-frame" x={e.frame.x} y={e.frame.y} width={e.frame.w} height={e.frame.h} rx={3} />
      <rect className="el-rail" x={e.railPh.x} y={e.railPh.y} width={e.railPh.w} height={e.railPh.h} />
      <rect className="el-rail" x={e.railRc.x} y={e.railRc.y} width={e.railRc.w} height={e.railRc.h} />
      {/* label at each rail's AWAY end (home direction folded in) so the homed carriage never covers it */}
      <text className="el-lbl" x={e.railPh.x + e.railPh.w - 4} y={e.railPh.y - 6} textAnchor="end">printhead rail · home ◀</text>
      <text className="el-lbl" x={e.railRc.x + 4} y={e.railRc.y - 6} textAnchor="start">recoater rail · home ▶</text>
      {[{ r: e.feed, mm: feed, cls: "el-feed", lbl: "feed", axis: 2 }, { r: e.build, mm: build, cls: "el-build", lbl: "build", axis: 1 }].map(({ r, mm, cls, lbl, axis }) => {
        const y = top(mm, r);
        const dir = pistonArrow(prevPos.current[axis], mm);
        const moving = mv(axis);
        prevPos.current[axis] = mm;
        const ax = r.x + r.w / 2;
        return (
          <g key={lbl}>
            <rect className="el-well" x={r.x} y={r.y} width={r.w} height={r.h} />
            <rect className="el-powder" x={r.x + 2} y={y} width={r.w - 4} height={Math.max(0, r.y + r.h - y)} />
            {axis === 1 && partZeroMm !== null && mm !== null && mm > partZeroMm && (
              <rect className="el-part" x={r.x + r.w * 0.25} y={e.pistonTopY(1, partZeroMm)} width={r.w * 0.5} height={Math.max(0, e.pistonTopY(1, mm) - e.pistonTopY(1, partZeroMm))} />
            )}
            <rect className={`${cls} ${mk(axis)}`} x={r.x + 2} y={y - 3} width={r.w - 4} height={6} />
            {moving && dir === "up" && (
              <polygon className="el-arrow up" aria-hidden="true" points={`${ax},${y - 12} ${ax - 4},${y - 6} ${ax + 4},${y - 6}`} />
            )}
            {moving && dir === "down" && (
              <polygon className="el-arrow down" aria-hidden="true" points={`${ax},${y + 12} ${ax - 4},${y + 6} ${ax + 4},${y + 6}`} />
            )}
            <text className="el-lbl" x={r.x + r.w / 2} y={r.y + r.h + 18} textAnchor="middle">{lbl} piston</text>
            {/* fixed nudge pair, clear of the moving Task-3 arrow: ▲ above the well's top edge (r.y),
                ▼ below the caption. Up = flush/negative mm, down = open cavity/positive mm. */}
            {onNudge && ctl(`${lbl}-up`, ax, r.y - 22, "▲", `${lbl} piston up ${nudgeStepMm} mm`, axis, -nudgeStepMm, controlsEnabled && !moving)}
            {onNudge && ctl(`${lbl}-down`, ax, r.y + r.h + 38, "▼", `${lbl} piston down ${nudgeStepMm} mm`, axis, nudgeStepMm, controlsEnabled && !moving)}
          </g>
        );
      })}
      {ph !== null && <rect className={`el-ph ${mk(3)}`} x={e.gantryX(3, ph) - 17} y={e.railPh.y - 10} width={34} height={30} rx={3} />}
      {rc !== null && <g className={mk(4)}>
        <rect className="el-rc" x={e.gantryX(4, rc) - 23} y={e.railRc.y - 10} width={46} height={30} rx={3} />
        <rect className="el-blade" x={e.gantryX(4, rc) - 23} y={e.railRc.y + 20} width={46} height={4} />
        <rect className={hcls} x={e.gantryX(4, rc) + 25} y={e.railRc.y - 6} width={30} height={16} rx={3} />
      </g>}
      {/* recoater nudge pair — STATIC at the rail ends (they do not follow the carriage). The
          recoater homes RIGHT, so on screen higher position = further LEFT: ◀ (on the left) moves
          the carriage left = +mm; ▶ (on the right) moves it right toward home = -mm. Greyed while
          the recoater is moving (a relative move is refused mid-motion). */}
      {onNudge && (() => {
        const railCy = e.railRc.y + e.railRc.h / 2;
        const rcMoving = mv(4);
        return (
          <g>
            {ctl("rec-left", e.railRc.x + 24, railCy, "◀", `recoater left (away from home) ${recoaterStepMm} mm`, 4, recoaterStepMm, controlsEnabled && !rcMoving)}
            {ctl("rec-right", e.railRc.x + e.railRc.w - 24, railCy, "▶", `recoater right (toward home) ${recoaterStepMm} mm`, 4, -recoaterStepMm, controlsEnabled && !rcMoving)}
          </g>
        );
      })()}
      {/* legend: solid = live axis, violet ghost = model/preview — makes the marker styling self-explanatory */}
      <g className="el-legend" transform={`translate(${e.frame.x + 4}, ${e.frame.y + e.frame.h + 16})`} aria-hidden="true">
        <circle className="mk-live" cx={5} cy={-4} r={5} />
        <text className="el-lbl" x={16} y={0}>live</text>
        <circle className="mk-model" cx={66} cy={-4} r={5} />
        <text className="el-lbl" x={77} y={0}>model</text>
      </g>
      {!t && <text className="el-empty" x={e.vb.w / 2} y={e.vb.h / 2} textAnchor="middle">no telemetry — connect a controller</text>}
    </svg>
  );
}
