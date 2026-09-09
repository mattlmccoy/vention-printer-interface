import type { ReactNode } from "react";
import type { Section } from "../../lib/layout.ts";
import { useFloat } from "./FloatContext.tsx";
import { FloatingPanel } from "./FloatingPanel.tsx";

interface Props { title: string; open: boolean; onToggle: () => void; tag?: string; tagWarn?: boolean; id?: Section; children: ReactNode; }

/** Collapsible rail section; with an `id` it can pop out into a floating window (⧉) and dock back. */
export function RailSection({ title, open, onToggle, tag, tagWarn, id, children }: Props) {
  const fl = useFloat();
  const rect = id && fl ? fl.floating[id] : undefined;
  if (id && fl && rect) {
    return (
      <>
        <section className="rail-section floating-stub">
          <div className="sec-head" style={{ cursor: "default" }}>
            <span>{title}</span><span className="tag">window</span>
            <button type="button" className="secondary chev" onClick={() => fl.dispatch({ type: "dockBack", section: id })} title="Dock back into the rail">⇲</button>
          </div>
        </section>
        <FloatingPanel title={title} rect={rect} onMove={(r) => fl.dispatch({ type: "moveFloat", section: id, rect: r })} onDock={() => fl.dispatch({ type: "dockBack", section: id })}>
          {children}
        </FloatingPanel>
      </>
    );
  }
  return (
    <section className="rail-section">
      <div className="sec-head-row">
        <button type="button" className="sec-head" aria-expanded={open} onClick={onToggle}>
          <span>{title}</span>
          {tag && <span className={`tag${tagWarn ? " tag-warn" : ""}`}>{tag}</span>}
          <span className="chev">{open ? "▾" : "▸"}</span>
        </button>
        {id && fl && <button type="button" className="secondary pop" onClick={() => fl.dispatch({ type: "popOut", section: id })} title="Pop out into a resizable window" aria-label={`Pop out ${title}`}>⧉</button>}
      </div>
      {open && <div className="body">{children}</div>}
    </section>
  );
}
