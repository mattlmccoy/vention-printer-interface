import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { DOCK_H, RAIL_W, studioClasses, type LayoutAction, type LayoutState } from "../../lib/layout.ts";
import { FloatContext } from "./FloatContext.tsx";

interface Props {
  layout: LayoutState;
  /** true for setup/experiments pages: center spans full height, no dock, strip hidden */
  page?: boolean;
  topbar: ReactNode;
  /**
   * Slot contract: each of `strip`, `rail`, `statusbar` must render exactly one element bearing
   * the grid's own class (`strip`, `rail`, `statusbar` respectively — see ToolStrip, Rail,
   * StatusBar). The Studio grid areas are keyed to those classes; a fragment, `null`, or more
   * than one top-level element in a slot would create implicit/extra grid rows.
   */
  strip?: ReactNode;
  center: ReactNode;
  dock?: ReactNode;
  rail?: ReactNode;
  statusbar: ReactNode;
  /** Layout dispatch: enables section pop-out and the collapsed-dock restore bar. */
  dispatch?: (a: LayoutAction) => void;
  /** Shown in the collapsed-dock bar too (playback transport must survive collapsing the plot). */
  dockFoot?: ReactNode;
}

/**
 * Drives a pointer drag on a resize handle. `measure` reads the moving edge's size in px from the
 * event; the result is clamped by the reducer. Double-click resets to the default.
 */
function dragHandler(measure: (e: PointerEvent) => number, apply: (px: number) => void) {
  return (e: ReactPointerEvent) => {
    e.preventDefault();
    const move = (ev: PointerEvent) => apply(measure(ev));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
}

/** The Studio grid (spec §3). Panels collapse via layout flags; grid areas are fixed. */
export function StudioFrame({ layout, page = false, topbar, strip, center, dock, rail, statusbar, dispatch, dockFoot }: Props) {
  const { className, showStrip, showRail, showDock } = studioClasses(layout, {
    page,
    hasStrip: !!strip,
    hasRail: !!rail,
    hasDock: !!dock,
  });
  const style: CSSProperties = {
    ...(showRail ? { ["--rail-w" as string]: `${layout.railW}px` } : {}),
    ...(showDock ? { ["--dock-h" as string]: `${layout.dockH}px` } : {}),
  };
  const railResize = dispatch && showRail && (
    <div className="rail-resizer" role="separator" aria-orientation="vertical" aria-label="Drag to resize the panel"
      title="Drag to resize · double-click to reset"
      onPointerDown={dragHandler(
        (ev) => (document.querySelector(".studio > .rail")?.getBoundingClientRect().right ?? window.innerWidth) - ev.clientX,
        (px) => dispatch({ type: "setRailW", w: px }),
      )}
      onDoubleClick={() => dispatch({ type: "setRailW", w: RAIL_W.default })} />
  );
  const dockResize = dispatch && showDock && (
    <div className="dock-resizer" role="separator" aria-orientation="horizontal" aria-label="Drag to resize the plot"
      title="Drag to resize · double-click to reset"
      onPointerDown={dragHandler(
        (ev) => (document.querySelector(".studio .dock")?.getBoundingClientRect().bottom ?? window.innerHeight) - ev.clientY,
        (px) => dispatch({ type: "setDockH", h: px }),
      )}
      onDoubleClick={() => dispatch({ type: "setDockH", h: DOCK_H.default })} />
  );
  const body = (
    <div className={className} style={style}>
      <div className="topbar">{topbar}</div>
      {showStrip && strip}
      <div className="center">
        {center}
        {dockResize}
        {showDock && dock}
        {!showDock && dock && dispatch && (
          <div className="dock-collapsed">
            <button type="button" className="secondary" onClick={() => dispatch({ type: "toggle", panel: "dock" })} title="Show the position plot">▴ plot</button>
            {dockFoot}
          </div>
        )}
      </div>
      {railResize}
      {showRail && rail}
      {statusbar}
    </div>
  );
  return dispatch ? <FloatContext.Provider value={{ floating: layout.floating, dispatch }}>{body}</FloatContext.Provider> : body;
}
