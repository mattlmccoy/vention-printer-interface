import { useState, type ReactNode } from "react";
import { moduleOrder, moveModule } from "../lib/console.ts";

export interface Module { id: string; title: string; size: "s" | "m" | "l" | "xl"; node: ReactNode; hidden?: boolean }

/** Self-sized cards in a wrapping row; drag a card's header onto another to reorder. Nothing
 *  stretches: widths are fixed per size, heights follow content. */
export function ModuleGrid({ modules, order, onOrder }: { modules: Module[]; order: string[] | undefined; onOrder: (ids: string[]) => void }) {
  const visible = modules.filter((m) => !m.hidden);
  const ids = moduleOrder(order, visible.map((m) => m.id));
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const byId = Object.fromEntries(visible.map((m) => [m.id, m]));
  return (
    <div className="modules" onDragOver={(e) => { e.preventDefault(); }} onDrop={(e) => { e.preventDefault(); if (dragging) onOrder(moveModule(ids, dragging, null)); setDragging(null); setOver(null); }}>
      {ids.map((id) => {
        const m = byId[id];
        return (
          <section key={id} className={`module ${m.size}${over === id && dragging !== id ? " over" : ""}${dragging === id ? " dragging" : ""}`}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setOver(id); }}
            onDragLeave={() => setOver((o) => (o === id ? null : o))}
            onDrop={(e) => { e.preventDefault(); e.stopPropagation(); if (dragging) onOrder(moveModule(ids, dragging, id)); setDragging(null); setOver(null); }}>
            <header className="mh" draggable onDragStart={(e) => { setDragging(id); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => { setDragging(null); setOver(null); }} title="drag to reorder">
              <span>{m.title}</span><span className="grip">⋮⋮</span>
            </header>
            <div className="mb">{m.node}</div>
          </section>
        );
      })}
    </div>
  );
}
