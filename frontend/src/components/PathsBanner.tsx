import { useEffect, useState } from "react";
import { api, type PathsInfo } from "../lib/api.ts";

const POLL_MS = 15_000;

/** A LOUD, always-visible banner shown whenever the operator resolved its jobs or runs folder to an
 *  empty install-local fallback (the recurring "wrong directory after a reinstall" bug). It never
 *  fails silently: it names the bad folder and lets the operator set the correct one inline. The
 *  paths persist install-independently (~/.config/vention-printer-interface/paths.json), so a future
 *  reinstall reads them back instead of falling back again. */
export function PathsBanner() {
  const [info, setInfo] = useState<PathsInfo | null>(null);
  const [jobs, setJobs] = useState("");
  const [runs, setRuns] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => api.health()
    .then((h) => { if (h.paths) { setInfo(h.paths); setJobs((j) => j || h.paths!.jobs_root); setRuns((r) => r || h.paths!.experiments_root); } })
    .catch(() => {});
  useEffect(() => { load(); const id = window.setInterval(load, POLL_MS); return () => window.clearInterval(id); }, []);

  if (!info || (!info.jobs_root_is_fallback && !info.experiments_root_is_fallback)) return null;

  const save = () => api.setConfigPaths({ jobs_root: jobs.trim() || null, experiments_root: runs.trim() || null })
    .then((r) => { setMsg(r.restart_required ? "saved — restart the operator so the runs folder takes effect" : "saved ✓"); load(); })
    .catch((e) => setMsg(String(e?.message ?? "failed")));

  return (
    <div className="update-banner" role="alert" style={{ background: "#5a1b1b", flexWrap: "wrap" }}>
      <span className="msg">
        ⚠ <b>Data-location problem.</b> The operator is reading an empty install-local folder — your real jobs/runs are elsewhere.
        {info.jobs_root_is_fallback && <> Jobs → <b>{info.jobs_root}</b>.</>}
        {info.experiments_root_is_fallback && <> Runs → <b>{info.experiments_root}</b>.</>}
        {" "}Enter the correct folders (saved to <code>{info.config_path}</code>, survives reinstalls):
      </span>
      <label className="row" style={{ gap: 4 }}>jobs <input style={{ width: 340 }} value={jobs} onChange={(e) => setJobs(e.target.value)} placeholder="/…/Hot Folder" /></label>
      <label className="row" style={{ gap: 4 }}>runs <input style={{ width: 340 }} value={runs} onChange={(e) => setRuns(e.target.value)} placeholder="/…/backend/experiments" /></label>
      <button className="small" onClick={save}>save</button>
      {msg && <span className="hint">{msg}</span>}
    </div>
  );
}
