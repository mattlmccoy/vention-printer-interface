import { useEffect, useRef, type ReactNode } from "react";
import type { FloatRect } from "../../lib/layout.ts";

interface Props { title: string; rect: FloatRect; onMove: (r: FloatRect) => void; onDock: () => void; children: ReactNode; }

/** A rail section living as a window: drag by the header, resize from the corner, dock back. */
export function FloatingPanel({ title, rect, onMove, onDock, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);

  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.offsetWidth, h = el.offsetHeight;
      if (Math.abs(w - rect.w) > 1 || Math.abs(h - rect.h) > 1) onMove({ ...rect, w, h });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [rect, onMove]);

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    drag.current = { dx: e.clientX - rect.x, dy: e.clientY - rect.y };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    onMove({ ...rect, x: Math.max(0, e.clientX - drag.current.dx), y: Math.max(0, e.clientY - drag.current.dy) });
  };
  const onPointerUp = () => { drag.current = null; };

  return (
    <div ref={ref} className="float-panel" role="dialog" aria-label={title}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}>
      <div className="float-head" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}>
        <span>{title}</span>
        <button type="button" className="secondary" onClick={onDock} title="Dock back into the rail" aria-label={`Dock ${title}`}>⇲ dock</button>
      </div>
      <div className="float-body">{children}</div>
    </div>
  );
}
