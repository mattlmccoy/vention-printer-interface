import { useEffect, useRef, useState } from "react";
import { heaterGlyph, layoutMachine, limitBands } from "../lib/machineview.ts";
import { AXES, AXIS_NAMES, type AxisNo, type StatusPayload } from "../lib/telemetry.ts";
import { describeStep, type Step } from "../lib/recipe.ts";

interface Props { status: StatusPayload | null; jog: boolean; onJog: (axis: AxisNo, mm: number) => void; currentStep?: Step | null }

const CLS: Record<AxisNo, string> = { 1: "m-part", 2: "m-feed", 3: "m-ph", 4: "m-rc" };

/** To-scale schematic of the printer (black-line style like the lab's wireframe): two gantries
 *  over the bed (printhead, recoater with the heater) and the two pistons in the bed. Live
 *  markers, soft-limit bands, heater state, and the recipe cursor. Click a track with the jog
 *  tool to move that axis there. */
export function MachineView({ status, jog, onJog, currentStep }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 400 });
  const [hover, setHover] = useState<{ axis: AxisNo; mm: number } | null>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  const g = layoutMachine(size.w, size.h);
  const tel = status?.controller.telemetry ?? null;
  const lim = status?.controller.limits;
  const pos = (a: AxisNo) => tel?.positions[String(a)] ?? null;
  const moving = (a: AxisNo) => tel ? tel.motion_complete[String(a)] === false : false;
  const heater = status?.controller.heater.on ?? null;

  const track = (a: AxisNo) => {
    const ax = g.axes[a];
    const t = ax.track;
    const p = pos(a);
    const bands = lim ? limitBands(ax, lim.travel_min[String(a)] ?? 0, lim.travel_max[String(a)] ?? 0) : [];
    const horizontal = ax.orientation === "horizontal";
    const onClick = (e: React.MouseEvent<SVGRectElement>) => {
      if (!jog) return;
      const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
      const mm = horizontal ? ax.mm(e.clientX - r.left) : ax.mm(e.clientY - r.top);
      onJog(a, Math.round(mm * 10) / 10);
    };
    const onMove = (e: React.MouseEvent<SVGRectElement>) => {
      const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
      setHover({ axis: a, mm: horizontal ? ax.mm(e.clientX - r.left) : ax.mm(e.clientY - r.top) });
    };
    return (
      <g key={a}>
        <rect className={`track${jog ? " jog" : ""}`} x={t.x} y={t.y} width={Math.max(t.w, 2)} height={Math.max(t.h, 2)} onClick={onClick} onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        {bands.map((b, i) => <rect key={i} className="band" x={b.x} y={b.y} width={b.w} height={b.h} pointerEvents="none" />)}
        {p !== null && (horizontal
          ? <rect className={`${CLS[a]}${moving(a) ? " moving" : ""}`} x={ax.px(p) - 6} y={t.y - 3} width={12} height={t.h + 6} rx={2} pointerEvents="none" />
          : <rect className={`${CLS[a]}${moving(a) ? " moving" : ""}`} x={t.x - 3} y={ax.px(p) - 3} width={t.w + 6} height={6} rx={2} pointerEvents="none" />)}
        <text className="lbl" x={horizontal ? t.x : t.x + t.w + 8} y={horizontal ? t.y - 4 : t.y + 12}>{AXIS_NAMES[a]}</text>
        <text className="val" x={horizontal ? t.x + t.w : t.x + t.w + 8} y={horizontal ? t.y - 4 : t.y + 26} textAnchor={horizontal ? "end" : "start"}>{p === null ? "—" : `${p.toFixed(1)} mm`}</text>
      </g>
    );
  };

  const hg = heaterGlyph(g, pos(4) ?? 0);
  const heaterCls = heater === true ? "heater-on" : heater === false ? "heater-off" : "heater-unk";
  // powder level in each piston: the piston top sits at its position (increasing downward)
  const powder = (a: AxisNo) => {
    const ax = g.axes[a]; const p = pos(a); if (p === null) return null;
    return <rect className="powder" x={ax.track.x + 4} y={ax.px(p)} width={ax.track.w - 8} height={Math.max(0, ax.track.y + ax.track.h - ax.px(p))} pointerEvents="none" />;
  };
  return (
    <div ref={ref} style={{ width: "100%", height: "100%", minHeight: 0 }}>
      <svg className="machine" viewBox={`0 0 ${size.w} ${size.h}`} role="img" aria-label="machine view">
        <rect className="frame" x={g.bed.x - 12} y={g.axes[3].track.y - 18} width={g.bed.w + 24} height={g.bed.y + g.bed.h - g.axes[3].track.y + 30} rx={4} />
        <rect className="frame" x={g.bed.x} y={g.bed.y} width={g.bed.w} height={g.bed.h} />
        {powder(2)}{powder(1)}
        {AXES.map(track)}
        <circle className={heaterCls} cx={hg.x} cy={hg.y + 6} r={5} pointerEvents="none" />
        <text className="lbl" x={hg.x + 9} y={hg.y + 10} pointerEvents="none">heater {heater === null ? "?" : heater ? "ON" : "off"}</text>
        {currentStep && <text className="cursor" x={g.bed.x} y={size.h - 10}>▶ step {currentStep.index}: {describeStep(currentStep)}</text>}
        {hover && <text className="val" x={size.w - 10} y={size.h - 10} textAnchor="end">{AXIS_NAMES[hover.axis]} {hover.mm.toFixed(1)} mm{jog ? " · click to jog" : ""}</text>}
        {!tel && <text className="lbl" x={size.w / 2} y={size.h / 2} textAnchor="middle">no telemetry — connect a controller</text>}
      </svg>
    </div>
  );
}
