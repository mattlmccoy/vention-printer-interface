import { useEffect } from "react";
import { CHANGELOG } from "../lib/changelog.ts";

/** Console version history (#16). Opened from the version badge in the status bar. Shows every
 *  release newest-first, plus the current site build stamp and the connected operator version. */
export function ChangelogModal({ siteVersion, buildId, operatorVersion, onClose }: {
  siteVersion: string; buildId: string; operatorVersion: string | null; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="console changelog" onClick={onClose}>
      <div className="changelog-panel" onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 560, width: "min(92vw, 560px)", maxHeight: "82vh", overflow: "auto", background: "var(--panel, #14161a)", borderRadius: 12, padding: 20 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
          <h3 style={{ margin: 0 }}>console changelog</h3>
          <button className="small" onClick={onClose}>close</button>
        </div>
        <div className="hint" style={{ marginTop: 0 }}>
          console v{siteVersion}{buildId ? ` · build ${buildId}` : ""}
          {operatorVersion ? ` · operator v${operatorVersion}` : ""}
        </div>
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
          {CHANGELOG.map((r) => (
            <div key={r.version}>
              <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
                <b style={{ fontSize: 15 }}>v{r.version}</b><span className="muted">{r.date}</span>
              </div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
                {r.changes.map((c, i) => <li key={i} style={{ marginBottom: 3 }}>{c}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
