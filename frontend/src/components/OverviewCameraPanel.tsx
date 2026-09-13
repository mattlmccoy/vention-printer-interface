import { useEffect, useState } from "react";
import type { View } from "../lib/console.ts";
import { overviewStreamUrl, panelVisible, setPanelVisible } from "../lib/vision.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Compact, collapsible live view of the OVERVIEW camera's MJPEG stream. Reused verbatim on
 *  Control/Priming/Print (compact) and full-size on the Cameras view — every instance points at
 *  the same stream endpoint, so this is a pure frontend addition with no extra backend cost.
 *  Degrades to a placeholder (never a broken-image icon) when the stream 404s or the camera is
 *  absent; visibility is a per-view toggle remembered locally (default: visible). */
export function OverviewCameraPanel({ base, view }: { base: string; view: View }) {
  const [visible, setVisible] = useState(() => panelVisible(view, storage));
  const [errored, setErrored] = useState(false);
  // A stream failure is scoped to the current stream attempt — if the base or view changes
  // (different operator, different panel), give the new stream a fresh chance to load.
  useEffect(() => setErrored(false), [base, view]);

  const toggle = () => {
    const next = !visible;
    setVisible(next);
    setPanelVisible(view, next, storage);
  };

  return (
    <section className="cam-panel">
      <header className="cam-panel-head">
        <span className="cam-panel-title">overview camera</span>
        <button className="small" aria-expanded={visible} onClick={toggle}>{visible ? "hide" : "show"}</button>
      </header>
      {visible && (
        errored ? (
          <div className="cam-panel-body cam-panel-empty">
            <span className="cam-panel-ph" aria-hidden="true" />
            <span>overview camera unavailable</span>
          </div>
        ) : (
          <div className="cam-panel-body">
            <img
              className="cam-panel-img"
              src={overviewStreamUrl(base)}
              alt="overview camera live view"
              onError={() => setErrored(true)}
            />
          </div>
        )
      )}
    </section>
  );
}
