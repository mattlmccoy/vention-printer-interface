import { useEffect, useState } from "react";
import { api, type VisionCalibrateResult } from "../../lib/api.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { CalibrationBoardPanel } from "../CalibrationBoardPanel.tsx";
import { CameraRoleAssigner } from "../CameraRoleAssigner.tsx";
import { CameraSettingsPanel } from "../CameraSettingsPanel.tsx";
import { CalibrationWizard } from "../CalibrationWizard.tsx";
import { ValidationPanel } from "../ValidationPanel.tsx";
import type { Call } from "./types.ts";

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


/** Manual capture-pose calibration: the science cam rides the recoater, so jog the recoater until
 *  the bed centre sits under the crosshair, then save the recoater position as capture_recoater_mm
 *  (the every-layer overhead capture pose). Grabs an on-demand science frame to check alignment. */
function CaptureCalibration({ status, gates, call, base }: { status: StatusPayload | null; gates: Gates; call: Call; base: string }) {
  const [streaming, setStreaming] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const [err, setErr] = useState(false);
  const [step, setStep] = useState(5);
  const [pose, setPose] = useState<number | null>(null);
  useEffect(() => {
    api.printSettings().then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setPose(typeof v === "number" ? v : 0);
    }).catch(() => undefined);
  }, []);
  const rc = status?.controller.telemetry?.positions?.["4"];
  const ok = gates.controllable && !gates.printActive;
  const streamUrl = `${base}/api/vision/science/stream?t=${streamKey}`;
  const toggleStream = () => { if (streaming) { setStreaming(false); } else { setErr(false); setStreamKey(Date.now()); setStreaming(true); } };
  const jog = (sign: 1 | -1) => call("jog recoater", () => api.move(4, "rel", sign * step));
  const savePose = () => {
    if (typeof rc !== "number") return;
    call("set capture pose", () => api.setPrintSettings({ capture_recoater_mm: rc }).then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setPose(typeof v === "number" ? v : rc);
    }));
  };
  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>The science camera rides the recoater. Start the live stream, jog the recoater until the bed centre sits under the crosshair, then save the pose — it becomes the capture_recoater_mm the print uses for every-layer overhead captures. (Setup only — the stream is unavailable during a print.)</div>
      <div style={{ position: "relative", maxWidth: 480, margin: "10px 0", background: "var(--image-bg)", borderRadius: "var(--radius)", overflow: "hidden", aspectRatio: "4 / 3" }}>
        {streaming && !err
          ? <img src={streamUrl} alt="science camera live view" onError={() => setErr(true)} style={{ width: "100%", display: "block" }} />
          : <div className="chart-empty" style={{ height: "100%" }}>{err ? "no science stream — no camera, or busy during a print" : "start the stream to align"}</div>}
        {streaming && !err && (
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
            <circle cx="50" cy="50" r="24" fill="none" stroke="var(--accent)" strokeWidth="0.6" opacity="0.9" />
            <circle cx="50" cy="50" r="1.2" fill="var(--accent)" />
            <line x1="50" y1="0" x2="50" y2="42" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
            <line x1="50" y1="58" x2="50" y2="100" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
            <line x1="0" y1="50" x2="42" y2="50" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
            <line x1="58" y1="50" x2="100" y2="50" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
          </svg>
        )}
      </div>
      <div className="actions" style={{ marginTop: 0 }}>
        <button className={`cta${streaming ? "" : " primary"}`} onClick={toggleStream}>{streaming ? "stop stream" : "start alignment stream"}</button>
        <span className="hint" style={{ marginTop: 0 }}>recoater jog</span>
        {[1, 5, 10].map((s) => <button key={s} type="button" className={`small${s === step ? " on" : ""}`} onClick={() => setStep(s)}>{s} mm</button>)}
        <button className="small" disabled={!ok} onClick={() => jog(-1)}>◀</button>
        <button className="small" disabled={!ok} onClick={() => jog(1)}>▶</button>
      </div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span>recoater now</span><span>{typeof rc === "number" ? `${rc.toFixed(1)} mm` : "—"}</span>
        <span>saved capture pose</span><span>{pose != null && pose > 0 ? `${pose} mm` : "not set"}</span>
      </div>
      <div className="actions one tight" style={{ marginTop: 10 }}>
        <button className="cta primary" disabled={!ok || typeof rc !== "number"} onClick={savePose}>Set capture pose = {typeof rc === "number" ? `${rc.toFixed(1)} mm` : "?"}</button>
      </div>
      {!ok && <div className="lock">{gates.printActive ? "print in progress — jog locked" : gates.connected ? "read-only · take control from the connection pill" : "connect + arm to jog the recoater"}</div>}
    </div>
  );
}

export function CamerasView({ status, gates, call, base, onOpenQuickStart }: {
  status: StatusPayload | null; gates: Gates; call: Call; base: string;
  /** A7: reopens the camera-role quick-start wizard any time (cameras swapped/replaced/re-cabled) */
  onOpenQuickStart: () => void;
}) {
  const [step, setStep] = useState(() => {
    const raw = typeof location !== "undefined" ? new URLSearchParams(location.search).get("step") : null;
    const q = raw === null || raw === "" ? NaN : Number(raw); // Number(null)===0 trap
    return Number.isInteger(q) && q >= 0 && q <= 6 ? q : 0; // capture/deep-link aid, matches STEPS below
  });
  const STEPS = [
    { title: "Connect controller", sub: "arm the machine" },
    { title: "Identify & assign cameras", sub: "overview · science" },
    { title: "Camera settings", sub: "res · fps · format · exposure" },
    { title: "Generate & print board", sub: "ChArUco / checkerboard" },
    { title: "Calibrate intrinsics", sub: "capture ≥3 board views" },
    { title: "Set bed plane", sub: "bed correspondence" },
    { title: "Validate", sub: "dimensional ±0.1 mm" },
  ];

  return (
    <div className="view fixed-page setup-view">
      <div className="sec-h">guided setup</div>
      <p className="setup-intro">Commission the cameras end to end — connect the controller, assign the overview and science roles, calibrate, and validate. Work top to bottom; each step says what it needs.</p>
      <div className="setup-grid">
        <div className="card">
          <h3>steps</h3>
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
              <div className="hint" style={{ marginTop: 0 }}>Connect the controller from the connection pill in the top bar, then take control (arm) so calibration moves are allowed.</div>
              <div className="chips" style={{ marginTop: 0 }}>
                <span className={`chip ${gates.connected ? "" : "warn"}`}>{gates.connected ? "controller connected" : "not connected"}</span>
                <span className={`chip ${gates.armed ? "" : "warn"}`}>{gates.armed ? "armed" : "read-only"}</span>
              </div>
            </div>
          )}
          {step === 1 && (
            <div className="grid-gap">
              <div className="note">📷 Nothing opens a camera until a page asks for it. Assign each camera by its live feed — the two share a name, so the picture is how you tell them apart: set one as overview (wide live view) and one as science (bed stills). It's remembered and reconnects automatically; if a camera doesn't appear, use Rescan.</div>
              <CameraRoleAssigner />
              <div className="btnrow">
                <button className="cta primary" onClick={onOpenQuickStart}>Identify &amp; assign cameras…</button>
                <button className="small" disabled={!gates.reachable} onClick={() => call("rescan cameras", () => api.visionDevices())}>Rescan devices</button>
              </div>
            </div>
          )}
          {step === 2 && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>Tune each camera live — resolution (up to 4K@30) and the controls it exposes (fps, exposure, …). Assign the cameras in step 2 first; settings are remembered per camera.</div>
              <div className="cols-2">
                <CameraSettingsPanel role="overview" />
                <CameraSettingsPanel role="science" />
              </div>
            </div>
          )}
          {step === 3 && <CalibrationBoardPanel base={base} />}
          {step === 4 && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>Start a session against your laser-engraved ChArUco board and capture at least 3 views from different bed positions / tilts.</div>
              <CalibrationWizard call={call} printing={gates.printActive} />
            </div>
          )}
          {step === 5 && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>Finalize the calibration with "use the last board view as the bed reference" ticked — this sets the bed plane so mm map to the bed, not the camera.</div>
              <CalibrationWizard call={call} printing={gates.printActive} />
            </div>
          )}
          {step === 6 && <ValidationPanel call={call} printing={gates.printActive} />}

          <div className="step-nav">
            <button className="small" disabled={step === 0} onClick={() => setStep((n) => Math.max(0, n - 1))}>Back</button>
            <button className="small" disabled={step === STEPS.length - 1} onClick={() => setStep((n) => Math.min(STEPS.length - 1, n + 1))}>Next</button>
          </div>
        </div>
      </div>

      <div className="sec-h">calibration tools</div>
      <p className="setup-intro">Manual and standalone calibration — set the overhead capture pose, or enter raw image↔world points by hand. The guided steps above are the normal commissioning path; reach for these only to adjust one thing directly.</p>
      <div className="setup-tools">
        <details className="rp-drawer">
          <summary>capture-pose calibration (overhead science cam)</summary>
          <CaptureCalibration status={status} gates={gates} call={call} base={base} />
        </details>
        <details className="rp-drawer">
          <summary>manual calibration (raw points)</summary>
          <div className="body"><CalibrationForm call={call} disabled={!gates.reachable} /></div>
        </details>
      </div>
    </div>
  );
}
