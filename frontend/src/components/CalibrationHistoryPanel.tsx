import { Fragment, useCallback, useEffect, useState, type CSSProperties } from "react";
import { api, operatorBase } from "../lib/api.ts";
import { checkRows, pointMethodSummary, type PointMethodRow, type RunResult } from "../lib/autocal_report.ts";
import {
  IMAGE_CAPTIONS, restorePlan, summaryFacts, validationBadge,
  type CalibrationDetail, type CalibrationSummary, type ValidationRecord,
} from "../lib/calibration_history.ts";

const TONE: Record<string, string> = { ok: "var(--live)", warn: "var(--warn)", err: "var(--err)" };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "unknown time");
const stampIso = (s: string) => `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(9, 11)}:${s.slice(11, 13)}:${s.slice(13, 15)}Z`;

/** Settings → Calibrations: every science-camera calibration with its report, photos, self-check
 *  and validations, long after it was made; any archived one can be made the one in use. */
export function CalibrationHistoryPanel() {
  const [rows, setRows] = useState<CalibrationSummary[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<CalibrationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await api.calibrations();
      setRows(list);
      setErr(null);
      setSel((cur) => cur ?? list[0]?.version ?? null);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    setDetail(null);
    api.calibration(sel).then(setDetail).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [sel, rows]);

  const active = rows?.find((r) => r.active) ?? null;
  const restore = async (target: CalibrationSummary) => {
    const plan = restorePlan(target, active);
    if (!window.confirm(plan.warning ? `${plan.confirm}\n\n⚠ ${plan.warning}` : plan.confirm)) return;
    setBusy(true);
    try { await api.activateCalibration(target.version); await load(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  if (err && !rows) return <div className="errline">Could not load the calibrations: {err}</div>;
  if (!rows) return <div className="hint">Loading calibrations…</div>;
  if (!rows.length) return <div className="hint">No calibration saved yet. Run one under Calibrate; every saved calibration is kept here.</div>;

  return (
    <div className="grid-gap">
      <div className="hint" style={{ marginTop: 0 }}>
        Every saved calibration, newest first, with the photos and numbers from when it was made and every validation against the certified plate. Stored on the operator in <code>experiments/vision_calibrations/</code>.
      </div>
      {err && <div className="errline" style={{ margin: 0 }}>{err}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
          <thead><tr>{["saved", "calibration", "photo size", "lens fit", "validation", ""].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r) => {
            const b = validationBadge(r.validation);
            const facts = Object.fromEntries(summaryFacts(r));
            return (
              <tr key={r.version} onClick={() => setSel(r.version)} aria-selected={sel === r.version}
                  style={{ cursor: "pointer", boxShadow: sel === r.version ? "inset 3px 0 0 var(--accent)" : undefined }}>
                <td style={td}>{when(r.saved_at)}</td>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{r.version}</td>
                <td style={td}>{facts["photo size"]}</td>
                <td style={{ ...td, fontFamily: "var(--font-mono)" }}>{facts["lens fit"]}</td>
                <td style={{ ...td, color: TONE[b.tone] }}>{b.text}</td>
                <td style={td}>{r.active ? <span className="pill" style={{ cursor: "default", color: "var(--live)", borderColor: "var(--live)" }}>in use</span> : null}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      {sel && !detail && <div className="hint">Loading {sel}…</div>}
      {detail && <CalibrationDetailView d={detail} busy={busy} onRestore={() => void restore(detail)} />}
    </div>
  );
}

function CalibrationDetailView({ d, busy, onRestore }: { d: CalibrationDetail; busy: boolean; onRestore: () => void }) {
  const report = d.report as (RunResult & { point_methods?: PointMethodRow[] }) | null;
  const methods = pointMethodSummary(report?.point_methods);
  const img = (name: string) => `${operatorBase()}/api/vision/calibrations/${encodeURIComponent(d.version)}/images/${name}.jpg`;
  return (
    <div className="grid-gap" style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "baseline", justifyContent: "space-between" }}>
        <h4 style={{ margin: 0, fontFamily: "var(--font-mono)" }}>{d.version}</h4>
        {d.active
          ? <span className="hint" style={{ margin: 0 }}>in use for every science photo</span>
          : d.archived
            ? <button className="cta" disabled={busy} onClick={onRestore}>{busy ? "switching…" : "use this calibration"}</button>
            : null}
      </div>
      <div className="kv">
        <span>saved</span><span>{when(d.saved_at)} · {d.method}</span>
        {summaryFacts(d).map(([k, v]) => <Fragment key={k}><span>{k}</span><span>{v}</span></Fragment>)}
      </div>
      {!d.archived && <div className="warnline" style={{ margin: 0 }}>Not archived yet: only the numbers in use are shown (the operator archives it on its next start).</div>}

      {d.images.length > 0 ? (
        <div style={thumbs}>
          {d.images.map((name) => (
            <figure key={name} style={{ margin: 0 }}>
              <a href={img(name)} target="_blank" rel="noreferrer"><img src={img(name)} alt={`${name} photo of ${d.version}`} loading="lazy" style={{ width: "100%", display: "block", border: "1px solid var(--line)" }} /></a>
              <figcaption className="hint" style={{ margin: "4px 0 0" }}>{IMAGE_CAPTIONS[name] ?? name} Click for full size.</figcaption>
            </figure>
          ))}
        </div>
      ) : <div className="hint" style={{ margin: 0 }}>No photos kept for this calibration{d.method === "auto-sweep" ? " (saved before photos were archived, and its sweep photos are no longer on the operator)" : " (manual calibrations keep numbers only)"}.</div>}

      {report && (
        <details>
          <summary>Run report: every check against its limit</summary>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6 }}>
              <thead><tr><th style={th}>check</th><th style={th}>this run</th><th style={th}>limit</th></tr></thead>
              <tbody>{checkRows(report).map((row) => (
                <tr key={row.label}><td style={td}>{row.label}</td><td style={{ ...td, fontFamily: "var(--font-mono)" }}>{row.value}</td><td style={{ ...td, color: "var(--muted)" }}>{row.limit}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {methods && (
            <>
              <div className="hint" style={{ margin: "8px 0 0" }}>{methods.verdict}</div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 6, fontVariantNumeric: "tabular-nums" }}>
                  <thead><tr><th style={th}>points fitted</th><th style={th}>used</th><th style={th}>held-out photos, average</th><th style={th}>worst point</th></tr></thead>
                  <tbody>{methods.rows.map((m) => (
                    <tr key={m.label}><td style={td}>{m.label}{m.kept ? " (kept)" : ""}</td><td style={td}>{m.points}</td><td style={{ ...td, fontFamily: "var(--font-mono)" }}>{m.heldout}</td><td style={{ ...td, fontFamily: "var(--font-mono)" }}>{m.worst}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          )}
        </details>
      )}

      <div>
        <div className="sec-h" style={{ margin: "4px 0 6px" }}>validations against the certified plate</div>
        {d.validations.length === 0
          ? <div className="warnline" style={{ margin: 0 }}>Not validated. Run Validate with the certified chessboard to check this calibration.</div>
          : <div className="grid-gap">{d.validations.map((v, i) => <ValidationItem key={v.stamp ?? `legacy-${i}`} version={d.version} v={v} />)}</div>}
      </div>
    </div>
  );
}

function ValidationItem({ version, v }: { version: string; v: ValidationRecord }) {
  const ok = v.passed === true;
  const url = (name: string) => `${operatorBase()}/api/vision/validations/${encodeURIComponent(version)}/${v.stamp}/${name}.jpg`;
  const fmt = (x: number | null | undefined) => (x == null ? "—" : `${x.toFixed(3)} mm`);
  return (
    <div>
      <div className={ok ? "okline" : "errline"} style={{ margin: 0 }}>
        {v.stamp ? when(stampIso(v.stamp)) : "date not recorded"}: {ok ? "passed" : "failed"} — worst {fmt(v.max_mm)}, RMS {fmt(v.rms_mm)}
        {v.target_mm != null && ` (target ${v.target_mm} mm)`}{v.scale_bias != null && ` · scale bias ${v.scale_bias.toFixed(4)}`}
        {v.scale_free_rms_mm != null && ` · RMS with scale removed ${fmt(v.scale_free_rms_mm)}`}
      </div>
      {v.note && <div className="hint" style={{ margin: "4px 0 0" }}>{v.note}</div>}
      {(v.annotated || v.raw) && (
        <div style={{ ...thumbs, marginTop: 6 }}>
          {v.annotated && <figure style={{ margin: 0 }}><a href={url("annotated")} target="_blank" rel="noreferrer"><img src={url("annotated")} alt="validation photo with every corner's error" loading="lazy" style={imgStyle} /></a><figcaption className="hint" style={{ margin: "4px 0 0" }}>Each corner's error: green within target, amber within 2×, red beyond.</figcaption></figure>}
          {v.raw && <figure style={{ margin: 0 }}><a href={url("raw")} target="_blank" rel="noreferrer"><img src={url("raw")} alt="the certified chessboard as photographed" loading="lazy" style={imgStyle} /></a><figcaption className="hint" style={{ margin: "4px 0 0" }}>The certified plate as photographed (unmarked). Click for full size.</figcaption></figure>}
        </div>
      )}
    </div>
  );
}

const thumbs: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 };
const imgStyle: CSSProperties = { width: "100%", display: "block", border: "1px solid var(--line)" };
const th: CSSProperties = { textAlign: "left", fontWeight: 500, color: "var(--muted)", borderBottom: "1px solid var(--line)", padding: "4px 8px" };
const td: CSSProperties = { borderBottom: "1px solid var(--line)", padding: "4px 8px", verticalAlign: "top" };
