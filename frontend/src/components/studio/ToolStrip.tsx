import type { ReactNode } from "react";
import { TOOLS, type Tool } from "../../lib/layout.ts";

const TOOL_META: Record<Tool, { glyph: ReactNode; title: string }> = {
  jog: { glyph: "✥", title: "Jog: click a track in the machine view to move that axis there (armed only)" },
  home: { glyph: "⌂", title: "Home: opens the axes section (home all / per axis)" },
  recipe: { glyph: "≡", title: "Recipe: opens the recipe section" },
  measure: { glyph: "⟷", title: "Measure: hover the machine view to read positions" },
};

interface Props { tool: Tool; onTool: (t: Tool) => void; onCollapseAll: () => void; collapsed?: boolean; disabledTools?: readonly Tool[] }

/** Left icon strip (FLIR pattern). Disabled tools stay visible so the layout never shifts; they
 *  use aria-disabled (not the disabled attribute) so their tooltip still shows. */
export function ToolStrip({ tool, onTool, onCollapseAll, collapsed = false, disabledTools = [] }: Props) {
  return (
    <nav className="strip" aria-label="tools">
      {TOOLS.map((id) => {
        const m = TOOL_META[id];
        const enabled = !disabledTools.includes(id);
        return (
          <button key={id} className={tool === id ? "active" : ""} data-tip={m.title} aria-label={m.title} aria-disabled={!enabled} aria-pressed={tool === id} onClick={() => { if (enabled) onTool(id); }}>
            {m.glyph}
          </button>
        );
      })}
      <span className="spacer" />
      <button className={collapsed ? "active" : ""} aria-pressed={collapsed} aria-label={collapsed ? "Restore panels" : "Hide panels (machine only)"} data-tip={collapsed ? "Restore panels" : "Hide panels (machine only)"} onClick={onCollapseAll}>⛶</button>
    </nav>
  );
}
