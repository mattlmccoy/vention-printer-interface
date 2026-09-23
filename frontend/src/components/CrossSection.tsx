import { api } from "../lib/api.ts";
import type { JobSnap } from "../lib/telemetry.ts";
import { cleanNum } from "../lib/format.ts";

/** The current (or chosen) layer's ink pattern from the sliced job, letterboxed. */
export function CrossSection({ job, layer, caption }: { job: JobSnap | null; layer: number; caption?: string }) {
  if (!job) return <div className="xsec"><div className="empty">no sliced job selected<br /><span className="hint">pick one on the Job tab, or run a manual print</span></div></div>;
  const n = Math.min(Math.max(layer, 1), job.layer_count);
  return (
    <div className="xsec">
      <img src={api.jobLayerUrl(n, job.folder)} alt={`layer ${n} cross-section`} />
      <div className="cap">{caption ?? <><b>{job.name}</b> · layer {n} of {job.layer_count} · {cleanNum(job.bbox_mm.x)} × {cleanNum(job.bbox_mm.y)} mm at {job.dpi} dpi</>}</div>
    </div>
  );
}
