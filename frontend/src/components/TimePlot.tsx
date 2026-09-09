import { useEffect, useRef, useState } from "react";
import { AXES, TRAVEL_MM, type AxisNo, type TraceBuffer } from "../lib/telemetry.ts";

const CLS: Record<AxisNo, string> = { 1: "t-part", 2: "t-feed", 3: "t-ph", 4: "t-rc" };

/** Position vs time, each axis normalised to its travel (0–100 %) so four very different
 *  ranges share one plot. Pure SVG, no library. */
export function TimePlot({ traces, windowS, tick }: { traces: Record<AxisNo, TraceBuffer>; windowS: number; tick: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 200 });
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el); setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  void tick;
  const pad = { l: 36, r: 8, t: 8, b: 18 };
  const W = size.w - pad.l - pad.r, H = size.h - pad.t - pad.b;
  const now = Date.now() / 1000;
  const x = (t: number) => pad.l + ((t - (now - windowS)) / windowS) * W;
  const y = (pct: number) => pad.t + H - (pct / 100) * H;
  return (
    <div ref={ref} style={{ width: "100%", height: "100%", minHeight: 0 }}>
      <svg className="plot-svg" viewBox={`0 0 ${size.w} ${size.h}`}>
        {[0, 25, 50, 75, 100].map((p) => <g key={p}><line className="grid" x1={pad.l} x2={pad.l + W} y1={y(p)} y2={y(p)} /><text className="axis-lbl" x={pad.l - 4} y={y(p) + 3} textAnchor="end">{p}%</text></g>)}
        <text className="axis-lbl" x={pad.l + W} y={size.h - 4} textAnchor="end">last {windowS}s · % of travel</text>
        {AXES.map((a) => {
          const pts = traces[a].window(windowS).map(([t, v]) => `${x(t).toFixed(1)},${y((v / TRAVEL_MM[a]) * 100).toFixed(1)}`).join(" ");
          return pts ? <polyline key={a} className={CLS[a]} points={pts} /> : null;
        })}
      </svg>
    </div>
  );
}
