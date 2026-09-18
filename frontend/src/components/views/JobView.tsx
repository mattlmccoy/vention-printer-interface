import { useEffect, useState } from "react";
import { api } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { JobSnap, StatusPayload } from "../../lib/telemetry.ts";
import { CrossSection } from "../CrossSection.tsx";
import type { Call } from "./types.ts";

type JobRow = Omit<JobSnap, "current_layer">;

/** Job tab = QUEUE ONLY. Browse the sliced jobs, preview layers, and select one (or clear to a
 *  manual print). Selecting a job just queues it — configuring parameters and starting the print
 *  happen on the Print tab (onGoPrint). This tab never starts a print. */
export function JobView({ status, gates, call, onGoPrint }: {
  status: StatusPayload | null; gates: Gates; call: Call; onGoPrint: () => void;
}) {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [roots, setRoots] = useState<string[]>([]);
  const [preview, setPreview] = useState(1);
  const job = status?.job ?? null;
  const running = gates.printActive;
  const refresh = () => { api.jobs().then((r) => { setJobs(r.jobs as JobRow[]); setRoots(r.roots); }).catch(() => undefined); };
  useEffect(() => { refresh(); }, [gates.reachable, job?.path]);

  return (
    <div className="view fixed-page job-view">
      <div className="sec-h">choose a job</div>
      <div className="cards-2">
        <div className="card">
          <h3>sliced jobs<button className="small" onClick={refresh}>rescan</button></h3>
          <div className="hint" style={{ marginTop: 0, marginBottom: 8 }}>{roots.join(" · ") || "no jobs folder configured (vpi-serve --jobs-root)"}</div>
          <div className="job-list">
            {jobs.map((j) => (
              <button key={j.path} className={job?.path === j.path ? "on" : ""} disabled={running} onClick={() => call("select job", () => api.selectJob(j.path))}>
                <span className="n"><span className={`kind ${(j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")) === "2D" ? "k2d" : "k3d"}`} title={(j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")) === "2D" ? "2D RIP print (single layer, multi-pass)" : "3D sliced part"}>{j.kind ?? (j.layer_count <= 1 ? "2D" : "3D")}</span>{j.name}{j.archived ? <span className="m" style={{ marginLeft: 6, opacity: 0.65 }} title="Archived — under the hot folder's _archive/">· archived</span> : null}</span><span className="m">{j.layer_count} × {j.layer_height_mm} mm</span>
                <span className="m">{j.folder.slice(0, 8)} {j.folder.slice(9, 11)}:{j.folder.slice(11, 13)} · {j.bbox_mm.x} × {j.bbox_mm.y} × {j.height_mm} mm</span><span className={`m ${j.complete ? "" : "bad"}`}>{j.complete ? `${j.dpi} dpi` : "missing pages"}</span>
              </button>
            ))}
            {jobs.length === 0 && <div className="hint">no job_info.json folders found. Slice a part with the Meteor RIP tool; its hot-folder archive is scanned.</div>}
          </div>
          {job && <div className="row" style={{ marginTop: 10 }}><button className="small" disabled={running} onClick={() => call("clear job", api.clearJob)}>manual print (no job)</button></div>}
        </div>
        <div className="card">
          <h3>{job ? `${job.name} · preview` : "preview"}</h3>
          {job?.has_preview && (
            <div className="splash">
              <img src={api.jobPreviewUrl(job.folder)} alt={`${job.name} render`} onError={(e) => { (e.currentTarget.parentElement as HTMLElement).hidden = true; }} />
              <div className="cap">slicer render</div>
            </div>
          )}
          <CrossSection job={job} layer={preview} />
          {job && <div className="slider"><span>1</span><input type="range" min={1} max={job.layer_count} value={Math.min(preview, job.layer_count)} onChange={(e) => setPreview(Number(e.target.value))} /><span>{job.layer_count}</span><b style={{ color: "var(--fg-strong)" }}>layer {Math.min(preview, job.layer_count)}</b></div>}
        </div>
      </div>

      <div className="card" style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        {job ? (
          <>
            <span>Queued <b>{job.name}</b> — {job.layer_count} × {job.layer_height_mm} mm.{job.archived ? " (archived)" : ""}</span>
            <span className="spacer" style={{ flex: 1 }} />
            {!job.archived && (
              <button className="small" disabled={running}
                title="Move this job into the hot folder's _archive/ — kept in history, out of the active list. Use once a print is complete."
                onClick={() => { if (window.confirm(`Archive "${job.name}"?\n\nIt moves into the hot folder's _archive/ — kept for history, out of the active jobs list. Do this once the print is complete.`)) call("archive job", () => api.archiveJob(job.folder).then(refresh)); }}>
                Archive job
              </button>
            )}
            <button className="cta primary" disabled={running} onClick={onGoPrint}>Configure &amp; start on Print →</button>
          </>
        ) : (
          <span className="hint" style={{ marginTop: 0 }}>Select a job to queue it, then configure and start it on the <b>Print</b> tab. (Or “manual print” to run without a sliced job.)</span>
        )}
      </div>
    </div>
  );
}
