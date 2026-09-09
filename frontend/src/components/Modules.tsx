import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { clampSize, moduleOrder, moveModule, type ModuleSize } from "../lib/console.ts";

export interface Module { id: string; title: string; size: "s" | "m" | "l" | "xl"; node: ReactNode; hidden?: boolean }

/** Self-sized cards in a wrapping row. Drag the header onto another card to reorder; drag the
 *  bottom-right handle to resize. Sizes are per-view overrides; nothing stretches to fill space. */
export function ModuleGrid({ modules, order, sizes, onOrder, onResize }: {
  modules: Module[];
  order: string[] | undefined;
  sizes: Record<string, ModuleSize> | undefined;
  onOrder: (ids: string[]) => void;
  onResize: (id: string, size: ModuleSize) => void;
}) {
  const visible = modules.filter((m) => !m.hidden);
  const ids = moduleOrder(order, visible.map((m) => m.id));
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const resizeRef = useRef<{ id: string; startX: number; startY: number; w: number; h: number } | null>(null);
  const byId = Object.fromEntries(visible.map((m) => [m.id, m]));

  const onResizeStart = (id: string, node: HTMLElement) => (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = node.getBoundingClientRect();
    resizeRef.current = { id, startX: e.clientX, startY: e.clientY, w: rect.width, h: rect.height };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    document.body.style.userSelect = "none";
    const move = (ev: PointerEvent) => {
      const r = resizeRef.current;
      if (!r) return;
      onResize(r.id, clampSize(r.w + (ev.clientX - r.startX), r.h + (ev.clientY - r.startY)));
    };
    const up = () => {
      resizeRef.current = null;
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="modules" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (dragging) onOrder(moveModule(ids, dragging, null)); setDragging(null); setOver(null); }}>
      {ids.map((id) => {
        const m = byId[id];
        const sz = sizes?.[id];
        const style = sz ? { width: sz.w, height: sz.h } : undefined;
        return (
          <ModuleCard key={id} id={id} className={`module ${sz ? "sized" : m.size}${over === id && dragging !== id ? " over" : ""}${dragging === id ? " dragging" : ""}`} style={style}
            title={m.title}
            onHeaderDragStart={(e) => { setDragging(id); e.dataTransfer.effectAllowed = "move"; }}
            onHeaderDragEnd={() => { setDragging(null); setOver(null); }}
            onCardDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setOver(id); }}
            onCardDragLeave={() => setOver((o) => (o === id ? null : o))}
            onCardDrop={(e) => { e.preventDefault(); e.stopPropagation(); if (dragging) onOrder(moveModule(ids, dragging, id)); setDragging(null); setOver(null); }}
            makeResize={onResizeStart}
            onResetSize={sz ? () => onResize(id, { w: 0, h: 0 }) : undefined}
          >
            {m.node}
          </ModuleCard>
        );
      })}
    </div>
  );
}

function ModuleCard({ id, className, style, title, children, onHeaderDragStart, onHeaderDragEnd, onCardDragOver, onCardDragLeave, onCardDrop, makeResize, onResetSize }: {
  id: string; className: string; style?: React.CSSProperties; title: string; children: ReactNode;
  onHeaderDragStart: (e: React.DragEvent) => void; onHeaderDragEnd: () => void;
  onCardDragOver: (e: React.DragEvent) => void; onCardDragLeave: () => void; onCardDrop: (e: React.DragEvent) => void;
  makeResize: (id: string, node: HTMLElement) => (e: ReactPointerEvent) => void; onResetSize?: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  return (
    <section ref={ref} className={className} style={style} onDragOver={onCardDragOver} onDragLeave={onCardDragLeave} onDrop={onCardDrop}>
      <header className="mh" draggable onDragStart={onHeaderDragStart} onDragEnd={onHeaderDragEnd} title="drag to reorder">
        <span>{title}</span>
        <span className="mh-r">{onResetSize && <button className="mh-reset" title="reset size" onClick={onResetSize}>⤡</button>}<span className="grip">⋮⋮</span></span>
      </header>
      <div className="mb">{children}</div>
      <span className="mresize" title="drag to resize" onPointerDown={(e) => ref.current && makeResize(id, ref.current)(e)} />
    </section>
  );
}
