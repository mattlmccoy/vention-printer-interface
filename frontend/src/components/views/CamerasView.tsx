import { useEffect, useMemo, useState } from "react";
import { api, type VisionCalibrateResult, type VisionCaptureSidecar } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { formatCaptureMetaValue, overviewStreamUrl, parseCaptures, type Capture } from "../../lib/vision.ts";
import { CalibrationBoardPanel } from "../CalibrationBoardPanel.tsx";
import { CalibrationWizard } from "../CalibrationWizard.tsx";
import { ValidationPanel } from "../ValidationPanel.tsx";
import type { Call } from "./types.ts";

const STAGES = ["pre_jet", "post_jet", "post_heat"] as const;
const STAGE_LABEL: Record<string, string> = { pre_jet: "pre-jet", post_jet: "post-jet", post_heat: "post-heat" };

/** One `<img>` with an honest failure state — the vision endpoints are freshly wired and a given
 *  run/layer/stage may simply have no image yet (or the file-serving route for it may not exist
 *  yet), so a 404 must always render as "unavailable", never as a blank/broken image (matches
 *  OverviewCameraPanel's fallback pattern). */
function CamImg({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [errored, setErrored] = useState(false);
  useEffect(() => setErrored(false), [src]);
  if (errored) return <div className="cam-panel-empty"><span className="cam-panel-ph" aria-hidden="true" /><span>{alt} unavailable</span></div>;
  return <img className={className} src={src} alt={alt} onError={() => setErrored(true)} />;
}

/** Fetches and renders one capture's sidecar JSON (see backend vision/store.py's
 *  _SIDECAR_TEMPLATE) via its `sidecar_url`. Shows only fields the backend actually
 *  populated — an absent/null field renders "—", never a guessed value (data-contract-
 *  verification: unknown must never render as healthy/invented). */
function CaptureMeta({ sidecarUrl }: { sidecarUrl?: string }) {
  const [meta, setMeta] = useState<VisionCaptureSidecar | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setMeta(null);
    setFailed(false);
    if (!sidecarUrl) return;
    let live = true;
    api.visionCaptureSidecar(sidecarUrl)
      .then((m) => { if (live) setMeta(m); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [sidecarUrl]);

  if (!sidecarUrl) return null;
  if (failed) return <div className="hint">metadata unavailable</div>;
  if (!meta) return null; // loading — say nothing rather than show a stale/wrong value

  const fmt = formatCaptureMetaValue;
  return (
    <div className="kv">
      <span>layer</span><span>{fmt(meta.layer)}</span>
      <span>stage</span><span>{fmt(meta.stage)}</span>
      <span>axis positions (mm)</span><span>{fmt(meta.axis_positions_mm)}</span>
      <span>capture requested</span><span>{fmt(meta.capture?.requested)}</span>
      <span>capture actual</span><span>{fmt(meta.capture?.actual)}</span>
      <span>exposure</span><span>{fmt(meta.controls?.exposure)}</span>
      <span>gain</span><span>{fmt(meta.controls?.gain)}</span>
      <span>calibration version</span><span>{fmt(meta.calibration?.version)}</span>
    </div>
  );
}

function CalibrationForm({ call, disabled }: { call: Call; disabled: boolean }) {
  const [imagePts, setImagePts] = useState("0,0\n100,0\n100,100\n0,100");
  const [worldPts, setWorldPts] = useState("0,0\n200,0\n200,200\n0,200");
  const [mmPerPx, setMmPerPx] = useState("0.5");
  const [bedExtent, setBedExtent] = useState("0,0,200,200");
  const [result, setResult] = useState<VisionCalibrateResult | null>(null);
  const [parseErr, setParseErr] = useState<string | null>(null);

  const parsePoints = (text: string): [number, number][] =>
    text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [x, y] = l.split(",").map(Number);
      return [x, y] as [number, number];
    });

  const submit = () => {
    setParseErr(null);
    let body: Parameters<typeof api.visionCalibrate>[0];
    try {
      const image_points = parsePoints(imagePts);
      const world_points_mm = parsePoints(worldPts);
      const extent = bedExtent.split(",").map(Number);
      if (image_points.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y))) throw new Error("bad image point");
      if (world_points_mm.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y))) throw new Error("bad world point");
      if (image_points.length !== world_points_mm.length || image_points.length < 4) throw new Error("need >= 4 matched image/world points");
      if (extent.length !== 4 || extent.some((v) => !Number.isFinite(v))) throw new Error("bed extent needs 4 numbers: x0,y0,x1,y1");
      const mm = Number(mmPerPx);
      if (!Number.isFinite(mm) || mm <= 0) throw new Error("mm/px must be a positive number");
      body = { image_points, world_points_mm, mm_per_px: mm, bed_extent_mm: extent as [number, number, number, number] };
    } catch (e) {
      setParseErr(e instanceof Error ? e.message : String(e));
      return;
    }
    call("calibrate", () => api.visionCalibrate(body).then(setResult));
  };

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>Paste matched image (px) and world (mm) points, one "x,y" per line — same order, same count (≥4).</div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span>image points (px)</span>
        <textarea rows={4} value={imagePts} onChange={(e) => setImagePts(e.target.value)} style={{ fontFamily: "var(--font-mono)" }} />
        <span>world points (mm)</span>
        <textarea rows={4} value={worldPts} onChange={(e) => setWorldPts(e.target.value)} style={{ fontFamily: "var(--font-mono)" }} />
        <span>mm / px</span>
        <input type="number" step="0.01" value={mmPerPx} onChange={(e) => setMmPerPx(e.target.value)} />
        <span>bed extent (mm)</span>
        <input type="text" placeholder="x0,y0,x1,y1" value={bedExtent} onChange={(e) => setBedExtent(e.target.value)} />
      </div>
      {parseErr && <div className="errline">{parseErr}</div>}
      <div className="actions one tight">
        <button className="cta primary" disabled={disabled} onClick={submit}>run calibration</button>
      </div>
      {disabled && <div className="lock">operator unreachable — calibration needs the backend</div>}
      {result && (
        <div className="kv">
          <span>reprojection error</span><span>{result.reprojection_error.toFixed(4)} px</span>
          <span>calibration version</span><span>{result.calibration_version}</span>
        </div>
      )}
    </>
  );
}

function CaptureBrowser({ base }: { base: string }) {
  const [runs, setRuns] = useState<string[]>([]);
  const [run, setRun] = useState("");
  const [captures, setCaptures] = useState<Capture[]>([]);

  useEffect(() => { api.recordings().then((r) => setRuns(r.runs.map((x) => x.run).reverse())).catch(() => undefined); }, []);
  useEffect(() => {
    if (!run) { setCaptures([]); return; }
    let live = true;
    api.visionCaptures(run).then((records) => { if (live) setCaptures(parseCaptures(records)); }).catch(() => { if (live) setCaptures([]); });
    return () => { live = false; };
  }, [run]);

  const layers = useMemo(() => [...new Set(captures.map((c) => c.layer))].sort((a, b) => a - b), [captures]);
  const [layer, setLayer] = useState<number | null>(null);
  useEffect(() => setLayer(layers[0] ?? null), [layers.join(",")]);
  const forLayer = captures.filter((c) => c.layer === layer);

  return (
    <>
      <div className="cam-browser-row">
        <label className="row">run <select value={run} onChange={(e) => setRun(e.target.value)}>
          <option value="">select a run…</option>
          {runs.map((r) => <option key={r} value={r}>{r}</option>)}
        </select></label>
        <label className="row">layer <select value={layer ?? ""} disabled={layers.length === 0} onChange={(e) => setLayer(Number(e.target.value))}>
          {layers.map((l) => <option key={l} value={l}>{l}</option>)}
        </select></label>
      </div>
      {run && layers.length === 0 && <div className="hint">no captures recorded for this run</div>}
      {forLayer.length > 0 && (
        <div className="cam-grid">
          {forLayer.map((c) => (
            <div key={c.stage} className="cam-still">
              <header>{STAGE_LABEL[c.stage] ?? c.stage} · layer {c.layer}</header>
              <CamImg src={`${base}${c.url}`} alt={`${c.stage} layer ${c.layer}`} />
              <CaptureMeta sidecarUrl={c.sidecarUrl} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function CamerasView({ status, gates, call, base, onOpenQuickStart }: {
  status: StatusPayload | null; gates: Gates; call: Call; base: string;
  /** A7: reopens the camera-role quick-start wizard any time (cameras swapped/replaced/re-cabled) */
  onOpenQuickStart: () => void;
}) {
  const run = status?.recording.run ?? null;
  const layer = status?.print?.layer ?? null;
  const [layerCaptures, setLayerCaptures] = useState<Capture[]>([]);

  useEffect(() => {
    if (!run) { setLayerCaptures([]); return; }
    let live = true;
    api.visionCaptures(run).then((records) => { if (live) setLayerCaptures(parseCaptures(records)); }).catch(() => { if (live) setLayerCaptures([]); });
    const id = window.setInterval(() => {
      api.visionCaptures(run).then((records) => { if (live) setLayerCaptures(parseCaptures(records)); }).catch(() => undefined);
    }, 4000);
    return () => { live = false; window.clearInterval(id); };
  }, [run]);

  const currentStills = layer === null ? [] : layerCaptures.filter((c) => c.layer === layer);

  const [step, setStep] = useState(0);
  const STEPS = [
    { title: "Cameras & roles", sub: "identify · assign · permission" },
    { title: "Print a board", sub: "ChArUco / checkerboard" },
    { title: "Calibrate", sub: "intrinsics + bed plane" },
    { title: "Validate", sub: "dimensional ±0.1 mm" },
  ];

  return (
    <div className="view fixed-page setup-view">
      <div className="setup-grid">
        <div className="card">
          <h3>guided setup</h3>
          <ol className="srail">
            {STEPS.map((s, i) => (
              <li key={s.title} className={i === step ? "on" : i < step ? "done" : ""} aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)}>
                <span className="n">{i < step ? "✓" : i + 1}</span>
                <div><div className="t">{s.title}</div><div className="sd">{s.sub}</div></div>
              </li>
            ))}
          </ol>
        </div>

        <div className="card">
          <h3>step {step + 1} · {STEPS[step].title}</h3>

          {step === 0 && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>Identify which detected camera is the overview (wide live view) and which is the science camera (bed stills). This is remembered and reconnects automatically. Nothing opens a camera until a page asks for it.</div>
              <div className="cam-panel-body" style={{ borderRadius: "var(--radius)", border: "1px solid var(--line)" }}><CamImg className="cam-panel-img" src={overviewStreamUrl(base)} alt="overview camera live view" /></div>
              <div className="btnrow">
                <button className="cta primary" onClick={onOpenQuickStart}>Identify &amp; assign cameras…</button>
                <button className="small" disabled={!gates.reachable} onClick={() => call("rescan cameras", () => api.visionDevices())}>Rescan devices</button>
              </div>
            </div>
          )}
          {step === 1 && <CalibrationBoardPanel base={base} />}
          {step === 2 && <CalibrationWizard call={call} printing={gates.printActive} />}
          {step === 3 && <ValidationPanel call={call} printing={gates.printActive} />}

          <div className="step-nav">
            <button className="small" disabled={step === 0} onClick={() => setStep((n) => Math.max(0, n - 1))}>Back</button>
            <button className="small" disabled={step === STEPS.length - 1} onClick={() => setStep((n) => Math.min(STEPS.length - 1, n + 1))}>Next</button>
          </div>
        </div>
      </div>

      <div className="sec-h">review captures</div>
      <div className="cards-2">
        <div className="card">
          <h3>{run ? `current layer stills · layer ${layer ?? "—"}` : "current layer stills"}</h3>
          {!run ? <div className="hint" style={{ marginTop: 0 }}>no active run — start a recording to capture layer stills</div> :
            currentStills.length === 0 ? <div className="hint" style={{ marginTop: 0 }}>no captures for the current layer yet</div> : (
              <div className="cam-grid">
                {STAGES.map((s) => {
                  const c = currentStills.find((x) => x.stage === s);
                  return (
                    <div key={s} className="cam-still">
                      <header>{STAGE_LABEL[s]}</header>
                      {c ? <CamImg src={`${base}${c.url}`} alt={STAGE_LABEL[s]} />
                        : <div className="cam-panel-empty"><span className="cam-panel-ph" aria-hidden="true" /><span>not captured yet</span></div>}
                    </div>
                  );
                })}
              </div>
            )}
        </div>
        <div className="card"><h3>capture browser</h3><CaptureBrowser base={base} /></div>
      </div>

      <details className="rp-drawer">
        <summary>manual calibration (raw points)</summary>
        <div className="body"><CalibrationForm call={call} disabled={!gates.reachable} /></div>
      </details>
    </div>
  );
}
