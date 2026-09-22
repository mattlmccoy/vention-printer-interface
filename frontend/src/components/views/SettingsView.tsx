import { useEffect, useRef, useState } from "react";
import { api, type BacklashHistoryItem, type BacklashRecord, type BacklashSession, type CenterSweepBest, type Drive, type OffloadJob, type OffloadPlanRow, type TimingConfig, type VisionCalibrateResult } from "../../lib/api.ts";
import { captureScienceStillOnce } from "../../lib/science_still.ts";
import { BacklashPlot } from "../BacklashPlot.tsx";
import { verifyVerdict, type Verdict } from "../../lib/backlash_verify.ts";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { loadRoleMap } from "../../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../../lib/overview_settings.ts";
import { CalibrationBoardPanel } from "../CalibrationBoardPanel.tsx";
import { CameraRoleAssigner } from "../CameraRoleAssigner.tsx";
import { CameraSettingsPanel } from "../CameraSettingsPanel.tsx";
import { CalibrationWizard } from "../CalibrationWizard.tsx";
import { ValidationPanel } from "../ValidationPanel.tsx";
import { PlotExportButtons } from "../PlotExportButtons.tsx";
import { pistonMaxPatch, type PistonField } from "../../lib/pistons.ts";
import type { Call } from "./types.ts";

const PISTON_STEPS = [0.1, 1, 5, 10] as const;

/** Server-side backlash calibration for one piston: drives ±d reversals at several depths, measures
 *  the bidirectional lost motion, and (on Apply) writes build/feed_backlash_mm. One runs at a time;
 *  the status is global so this card only reacts to sessions for its own axis. */
function BacklashCal({ axis, name, ok, unref, call, onPlan }: {
  axis: 1 | 2; name: string; ok: boolean; unref: boolean;
  call: Call; onPlan: (p: Record<string, unknown>) => void;
}) {
  const [sess, setSess] = useState<BacklashSession | null>(null);
  const [hideDone, setHideDone] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [hist, setHist] = useState<BacklashHistoryItem[]>([]);
  const [histOpen, setHistOpen] = useState(false);
  const [viewing, setViewing] = useState<BacklashRecord | null>(null);
  const loadHist = () => api.backlashHistory()
    .then((r) => setHist(r.calibrations.filter((c) => c.axis === axis)))
    .catch(() => setHist([]));
  useEffect(() => { loadHist(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const doneState = sess?.state === "done" && sess.result?.axis === axis;
  useEffect(() => { if (doneState) loadHist(); }, [doneState]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let live = true;
    const tick = async () => {
      try { const s = await api.backlashStatus(); if (live) setSess(s); } catch { /* transient */ }
    };
    tick();
    const id = window.setInterval(tick, 800);
    return () => { live = false; window.clearInterval(id); };
  }, []);

  const running = sess?.state === "running";
  const runningMine = running && sess?.axis === axis;
  const runningOther = running && sess?.axis !== axis;
  const doneMine = sess?.state === "done" && sess.result?.axis === axis && !hideDone;
  const errMine = sess?.state === "error" && sess.axis === axis;
  const rec = sess?.result?.recommended_mm ?? null;

  const start = () => {
    if (!window.confirm(`Calibrate the ${name} piston's backlash? It jogs the piston through several ±2 mm reversals at a few depths, then returns to the current position. Keep clear of the piston.`)) return;
    setHideDone(false);
    call(`calibrate ${name} backlash`, () => api.backlashStart({ axis }).then(setSess));
  };
  const cancel = () => call(`cancel ${name} backlash`, () => api.backlashCancel().then(setSess));
  const apply = () => {
    setHideDone(true);
    call(`apply ${name} backlash`, () => api.backlashApply(axis).then((r) => onPlan(r.plan as Record<string, unknown>)));
  };
  // Re-measure at PERTURBED depths (the midpoints between the original references) to check the
  // lash holds across the travel, not just at the depths first probed — guards against reading a
  // position-specific rut. The cal measures raw mechanical lash (the applied compensation is a
  // print-time move, not part of the measurement), so this verifies the MEASUREMENT is trustworthy,
  // not that comp zeroed the lash — that shows up in layer accuracy.
  const verify = async () => {
    if (rec == null) return;
    const baseline = rec;
    setVerdict(null); setVerifying(true);
    const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
    try {
      let s = await api.backlashStart({ axis, verify: true });
      setSess(s);
      while (s.state === "running") { await sleep(800); s = await api.backlashStatus(); setSess(s); }
      const newRec = s.result?.recommended_mm;
      if (s.state === "done" && newRec != null) setVerdict(verifyVerdict(baseline, newRec));
    } catch (e) {
      setVerdict(null);
      window.alert(`re-measure failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="backlash-cal" style={{ marginTop: 10 }}>
      <div className="actions" style={{ marginTop: 0 }}>
        <button className="cta" disabled={!ok || unref || running} onClick={start}
          data-tip="Measure the piston's mechanical lost-motion (backlash) by reversing into each depth from both sides.">
          Calibrate backlash
        </button>
      </div>
      {runningOther && <div className="hint" style={{ marginTop: 8 }}>calibrating the other piston…</div>}
      {runningMine && (
        <div className="cal-run" style={{ marginTop: 8 }}>
          <div className="hint" style={{ marginTop: 0 }}>
            measuring… {sess!.progress.done}/{sess!.progress.total}
            {typeof sess!.current_ref_mm === "number" ? ` · at ${sess!.current_ref_mm.toFixed(1)} mm` : ""}
          </div>
          <div className="bar" style={{ marginTop: 6, height: 6, background: "var(--track, #2a2f3a)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${sess!.progress.total ? (100 * sess!.progress.done) / sess!.progress.total : 0}%`, background: "var(--accent, #d9a441)" }} />
          </div>
          {sess!.partial_positions && sess!.partial_positions.length > 0 &&
            <BacklashPlot positions={sess!.partial_positions} recommended={null} />}
          <div className="actions" style={{ marginTop: 8 }}><button className="cta" onClick={cancel}>Cancel</button></div>
        </div>
      )}
      {doneMine && (
        <div className="cal-result" style={{ marginTop: 8 }}>
          <div className="kv" style={{ marginTop: 0 }}>
            <span>measured backlash</span>
            <span className="v">{rec !== null ? `${rec.toFixed(2)} mm` : "—"}</span>
          </div>
          {sess!.result && sess!.result.positions.length > 0 &&
            <BacklashPlot positions={sess!.result.positions} recommended={rec} />}
          {rec === 0
            ? <div className="hint" style={{ marginTop: 6 }}>no lash detected on this cylinder — nothing to compensate. Applying sets it to 0.</div>
            : <div className="hint" style={{ marginTop: 6 }}>Apply to write this as the {name}-piston anti-backlash compensation.</div>}
          <div className="actions" style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="cta primary" style={{ whiteSpace: "nowrap" }} disabled={!ok} onClick={apply}>Apply {rec !== null ? `(${rec.toFixed(2)} mm)` : ""}</button>
            <button className="cta" style={{ whiteSpace: "nowrap" }} disabled={!ok || verifying} onClick={() => void verify()}
              data-tip="Re-measure at the depths BETWEEN the first ones. If the lash holds there too, it's a real mechanical property, not a position-specific rut. Verifies the measurement — not that compensation zeroed the lash (that shows in layer accuracy).">
              {verifying ? "re-measuring…" : "Verify · re-measure"}
            </button>
            <button className="cta" style={{ whiteSpace: "nowrap" }} onClick={() => setHideDone(true)}>Discard</button>
          </div>
          {verdict && (
            <div className="hint" style={{ marginTop: 6, color: verdict.consistent ? "var(--ok, #2e7d32)" : "var(--bad, #b00020)" }}>
              {verdict.consistent
                ? `✓ Holds at perturbed depths — re-measured ${verdict.newMm.toFixed(2)} mm (was ${verdict.priorMm.toFixed(2)} mm, Δ ${verdict.deltaMm.toFixed(2)} mm ≤ one count). Consistent across the travel, so the reading is trustworthy.`
                : `⚠ Differs at perturbed depths — re-measured ${verdict.newMm.toFixed(2)} mm vs ${verdict.priorMm.toFixed(2)} mm (Δ ${verdict.deltaMm.toFixed(2)} mm > one count). The lash is position-dependent — average more runs or check the mechanism before trusting one value.`}
            </div>
          )}
          <PlotExportButtons fetchBlob={(fmt) => api.plotBacklash(fmt)}
            filename={`${name}_piston_backlash`} label="Seaborn plot" />
        </div>
      )}
      {errMine && (
        <div className="cal-result" style={{ marginTop: 8 }}>
          <div className="errline">calibration failed: {sess!.error}</div>
        </div>
      )}
      {hist.length > 0 && (
        <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 8 }}>
          <button className="small" onClick={() => setHistOpen((v) => !v)}>{histOpen ? "hide" : "show"} saved calibrations ({hist.length})</button>
          {histOpen && (
            <>
              {hist.map((h) => (
                <div key={h.id} className="row" style={{ justifyContent: "space-between", gap: 8, padding: "3px 0" }}>
                  <span className="hint" style={{ marginTop: 0 }}>{(h.saved_utc || "").replace("T", " ").replace("Z", " UTC")} · {h.recommended_mm != null ? `${h.recommended_mm.toFixed(2)} mm` : "—"} · {h.n_positions} depths</span>
                  <button className="small" onClick={() => api.backlashRecord(h.id).then(setViewing).catch(() => undefined)}>view</button>
                </div>
              ))}
              {viewing && viewing.axis === axis && viewing.positions.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <div className="hint" style={{ marginTop: 0 }}>recommended {viewing.recommended_mm != null ? `${viewing.recommended_mm.toFixed(2)} mm` : "—"}</div>
                  <BacklashPlot positions={viewing.positions} recommended={viewing.recommended_mm ?? null} />
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** One piston's jog + set-max control. Jog to the physical stop, then "Set current as max" records
 *  the position as this piston's usable travel (per cylinder); the build max bounds build depth. */
function Piston({ axis, name, field, status, ok, call, plan, onPlan }: {
  axis: 1 | 2; name: string; field: PistonField; status: StatusPayload | null; ok: boolean;
  call: Call; plan: Record<string, unknown> | null; onPlan: (p: Record<string, unknown>) => void;
}) {
  const [pstep, setPstep] = useState<number>(1);
  const t = status?.controller.telemetry;
  const pos = t?.positions[String(axis)];
  const unref = t?.referenced?.[String(axis)] === false;
  const moving = t ? t.motion_complete[String(axis)] === false : false;
  const max = typeof plan?.[field] === "number" ? (plan[field] as number) : null;
  const jog = (sign: 1 | -1) => call(`jog ${name}`, () => api.move(axis, "rel", sign * pstep));
  const home = () => {
    if (window.confirm(`Home the ${name} piston? This drives it fully UP (0 mm = flush) and EJECTS any powder in the cylinder.`))
      call(`home ${name}`, () => api.home([axis]));
  };
  const setMax = () => {
    if (typeof pos !== "number") return;
    if (unref) { window.alert("Home (reference) the piston first so its position is real."); return; }
    if (!window.confirm(`Set ${pos.toFixed(1)} mm as the ${name} piston's max travel? Jog it to the physical stop first.`)) return;
    call(`set ${name} max`, () => api.setPrintSettings(pistonMaxPatch(field, pos)).then((r) => onPlan(r.plan as Record<string, unknown>)));
  };
  return (
    <div className="card">
      <h3>{name} piston <span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>axis {axis}</span></h3>
      <div className="kv" style={{ marginTop: 0 }}>
        <span>position</span>
        <span className="v">{unref ? <b className="unref">unref</b> : typeof pos === "number" ? `${pos.toFixed(1)} mm` : "—"}{moving ? " · moving" : ""}</span>
        <span>max travel</span>
        <span className="v">{max !== null ? `${max.toFixed(1)} mm` : "—"}</span>
      </div>
      <div className="stepper" style={{ marginTop: 10 }}>step {PISTON_STEPS.map((s) => <button key={s} className={s === pstep ? "on" : ""} onClick={() => setPstep(s)}>{s} mm</button>)}</div>
      <div className="jog" style={{ marginTop: 8 }}>
        <button disabled={!ok} onClick={() => jog(-1)}>▲ UP</button>
        <button disabled={!ok} onClick={() => jog(1)}>▼ DOWN</button>
        <button className="home" disabled={!ok} data-tip={`home the ${name} piston — EJECTS POWDER (drives it fully up / flush)`} onClick={home}>⌂</button>
      </div>
      <div className="actions" style={{ marginTop: 10 }}>
        <button className="cta primary" disabled={!ok || typeof pos !== "number" || unref} onClick={setMax}>
          Set current as max{typeof pos === "number" && !unref ? ` (${pos.toFixed(1)} mm)` : ""}
        </button>
      </div>
      <div className="hint" style={{ marginTop: 10 }}>Jog <b>DOWN</b> to the physical stop, then set it — this is the piston's usable range for the current cylinder. A build deeper than the <b>build</b> max is blocked.</div>
      <BacklashCal axis={axis} name={name} ok={ok} unref={unref} call={call} onPlan={onPlan} />
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


/** Manual capture-pose calibration: the science cam rides the recoater, so jog the recoater until
 *  the bed center sits under the crosshair, then save the recoater position as capture_recoater_mm
 *  (the every-layer overhead capture pose). Grabs an on-demand science frame to check alignment. */
function CaptureCalibration({ status, gates, call }: { status: StatusPayload | null; gates: Gates; call: Call; base: string }) {
  const [streaming, setStreaming] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState(5);
  const [pose, setPose] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  useEffect(() => {
    api.printSettings().then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setPose(typeof v === "number" ? v : 0);
    }).catch(() => undefined);
  }, []);
  const rc = status?.controller.telemetry?.positions?.["4"];
  const ok = gates.controllable && !gates.printActive;
  // Client-side stream of the ASSIGNED science camera (by browser deviceId) — the setup alignment
  // must show the SAME camera the print records with. The old server MJPEG stream opened the wrong
  // camera on macOS with two identical ELPs (the exact bug this fixes).
  const stopStream = () => { streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null; };
  useEffect(() => () => stopStream(), []);
  const toggleStream = () => {
    if (streaming) { stopStream(); setStreaming(false); return; }
    setErr(null);
    const storage = typeof localStorage === "undefined" ? null : localStorage;
    const deviceId = loadRoleMap(storage).science;
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
    if (!deviceId) { setErr("assign the science camera in Setup first"); return; }
    if (!md?.getUserMedia) { setErr("camera access unavailable in this browser"); return; }
    setStreaming(true);
    md.getUserMedia({ video: videoConstraints(deviceId, loadCameraSettings(storage, "science")) })
      .then((stream) => {
        streamRef.current = stream;
        if (videoRef.current) { videoRef.current.srcObject = stream; videoRef.current.play().catch(() => {}); }
      })
      .catch(() => { setErr("could not open the science camera (in use, or permission denied)"); setStreaming(false); });
  };
  const jog = (sign: 1 | -1) => call("jog recoater", () => api.move(4, "rel", sign * step));
  const savePose = () => {
    if (typeof rc !== "number") return;
    call("set capture pose", () => api.setPrintSettings({ capture_recoater_mm: rc }).then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setPose(typeof v === "number" ? v : rc);
    }));
  };

  // ---- automated center-find: sweep the recoater, score the bore offset per pose, pick the center.
  const [sweeping, setSweeping] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [best, setBest] = useState<CenterSweepBest | null>(null);
  const [autoErr, setAutoErr] = useState<string | null>(null);
  const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
  const waitSettled = async (axis: number, timeoutMs = 6000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      try {
        const s = await api.status();
        if (s.controller?.telemetry?.motion_complete?.[String(axis)] !== false) break;
      } catch { /* transient */ }
      await sleep(200);
    }
    await sleep(400);  // let gantry vibration settle before the shot
  };
  const findCenter = async () => {
    if (!window.confirm("Auto-find the overhead center? The recoater sweeps through several positions, capturing the science camera at each, then recommends the pose that centers the build piston. Keep clear of the gantry.")) return;
    const storage = typeof localStorage === "undefined" ? null : localStorage;
    setAutoErr(null); setBest(null); setSweeping(true);
    if (streaming) { stopStream(); setStreaming(false); }  // free the science cam for per-pose grabs
    try {
      const sess = await api.centerSweepStart({ span_mm: 8, step_mm: 2 });
      setProgress({ done: 0, total: sess.poses.length });
      for (let i = 0; i < sess.poses.length; i++) {
        const p = sess.poses[i];
        await api.move(4, "abs", p);
        await waitSettled(4);
        const blob = await captureScienceStillOnce(storage);
        await api.centerSweepSample(blob, p);
        setProgress({ done: i + 1, total: sess.poses.length });
      }
      const b = await api.centerSweepBest();
      setBest(b);
      await api.move(4, "abs", b.pose_mm);  // park at the recommended pose so the preview shows it
    } catch (e) {
      setAutoErr(e instanceof Error ? e.message : String(e));
      await api.centerSweepCancel().catch(() => undefined);
    } finally {
      setSweeping(false);
    }
  };
  const applyCenter = () => {
    if (best == null) return;
    call("apply overhead center", () => api.centerSweepApply(best.pose_mm).then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setPose(typeof v === "number" ? v : best.pose_mm);
      setBest(null);
    }));
  };
  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>The science camera rides the recoater. Start the live stream, jog the recoater until the bed center sits under the crosshair, then save the pose — it becomes the capture_recoater_mm the print uses for every-layer overhead captures. This streams the camera you assigned to the science role.</div>
      {/* When streaming, the <video> (width:100%, height:auto) defines the box height from the
          stream's OWN aspect ratio, so the absolute crosshair overlay lands exactly on it — no
          letterbox, center on the true frame center. The fixed 4:3 is only for the placeholder box
          before a stream exists (the camera's real aspect is unknown until then). */}
      <div style={{ position: "relative", maxWidth: 480, margin: "10px 0", background: "var(--image-bg)", borderRadius: "var(--radius)", overflow: "hidden", ...(streaming && !err ? {} : { aspectRatio: "4 / 3" }) }}>
        <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", display: streaming && !err ? "block" : "none", verticalAlign: "bottom" }} />
        {(!streaming || err) && <div className="chart-empty" style={{ height: "100%" }}>{err ?? "start the stream to align"}</div>}
        {streaming && !err && (
          <>
            {/* Cross lines span the whole frame and cross at its exact center (stretched viewBox
                keeps them axis-aligned). */}
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
              <line x1="50" y1="0" x2="50" y2="42" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
              <line x1="50" y1="58" x2="50" y2="100" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
              <line x1="0" y1="50" x2="42" y2="50" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
              <line x1="58" y1="50" x2="100" y2="50" stroke="var(--accent)" strokeWidth="0.5" opacity="0.9" />
            </svg>
            {/* Guide circle + center dot in a `meet`-scaled overlay so the circle stays ROUND on
                any stream aspect (scales to the shorter side, centered) instead of an ellipse. */}
            <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
              <circle cx="50" cy="50" r="30" fill="none" stroke="var(--accent)" strokeWidth="0.7" opacity="0.9" />
              <circle cx="50" cy="50" r="1.4" fill="var(--accent)" />
            </svg>
          </>
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

      {/* Automated alternative to the manual jog: sweep + circle-detect finds the overhead center. */}
      <div style={{ marginTop: 14, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
        <div className="hint" style={{ marginTop: 0 }}>Or find it automatically: the recoater sweeps a tight range while the science camera watches, and the build-piston bore is detected in each frame to pick the centering pose. HOME + prime the bed first so the bore is visible.</div>
        <div className="actions one tight" style={{ marginTop: 8 }}>
          <button className="cta" disabled={!ok || sweeping} onClick={() => void findCenter()}>
            {sweeping ? `sweeping… ${progress.done}/${progress.total}` : "Find overhead center"}
          </button>
        </div>
        {sweeping && progress.total > 0 && (
          <div className="bar" style={{ marginTop: 8, height: 6, background: "var(--track, #2a2f3a)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${(100 * progress.done) / progress.total}%`, background: "var(--accent, #d9a441)" }} />
          </div>
        )}
        {autoErr && <div className="errline" style={{ marginTop: 8 }}>center-find failed: {autoErr}</div>}
        {best && (
          <div className="cal-result" style={{ marginTop: 8 }}>
            <div className="kv" style={{ marginTop: 0 }}>
              <span>recommended pose</span><span className="v">{best.pose_mm.toFixed(1)} mm</span>
              <span>residual offset</span><span className="v">{best.offset_px.toFixed(0)} px</span>
            </div>
            {best.improved
              ? <div className="hint" style={{ marginTop: 6 }}>Better centered than the previous pose. Apply to write it as the capture pose.</div>
              : <div className="hint" style={{ marginTop: 6 }}>No improvement over the current pose — the bore may already be centered, or the bore wasn’t clearly detected. Check the preview before applying.</div>}
            <div className="actions" style={{ marginTop: 8, display: "flex", gap: 8 }}>
              <button className="cta primary" disabled={!ok} onClick={applyCenter}>Apply ({best.pose_mm.toFixed(1)} mm)</button>
              <button className="cta" onClick={() => setBest(null)}>Discard</button>
            </div>
          </div>
        )}
      </div>
      {!ok && <div className="lock">{gates.printActive ? "print in progress — jog locked" : gates.connected ? "read-only · take control from the connection pill" : "connect + arm to jog the recoater"}</div>}
    </div>
  );
}

/** Bind the SCIENCE camera to a stable macOS AVFoundation unique id, so the operator captures the
 *  RIGHT camera unattended (no browser tab open). The client-side picker is still the primary way to
 *  tell two identical ELPs apart; this is the robust server-side fallback for unattended prints. */
/** Copy runs to a picked external drive, FLIR-style: each file hash-verified, re-copy skips what's
 *  already there (a yanked cable just resumes). Runs land under vpi-runs/ on the drive. */
function DataOffloadPanel() {
  const [drives, setDrives] = useState<Drive[]>([]);
  const [dest, setDest] = useState("");
  const [plan, setPlan] = useState<OffloadPlanRow[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [job, setJob] = useState<OffloadJob | null>(null);
  const [msg, setMsg] = useState("");
  const gb = (b: number) => (b / 1e9).toFixed(1);

  const loadDrives = () => api.offloadDrives().then((r) => setDrives(r.drives)).catch(() => setDrives([]));
  useEffect(() => { loadDrives(); }, []);
  const loadPlan = (d: string) => api.offloadPlan(d).then((r) => {
    setPlan(r.plan);
    setJob(r.job.state === "idle" ? null : r.job);
    setSel(new Set(r.plan.filter((p) => !p.at_dest).map((p) => p.run)));  // default: the missing ones
  }).catch(() => setPlan([]));
  const pick = (d: string) => { setDest(d); if (d) loadPlan(d); else setPlan([]); };

  const running = job?.state === "running";
  useEffect(() => {  // poll while a copy runs; refresh the plan when it finishes
    if (!running) return;
    const id = window.setInterval(async () => {
      try {
        const j = await api.offloadJob();
        setJob(j);
        if (j.state !== "running") { window.clearInterval(id); if (dest) loadPlan(dest); }
      } catch { /* transient */ }
    }, 700);
    return () => window.clearInterval(id);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  const [move, setMove] = useState(false);
  const start = (runs?: string[]) => {
    if (move && !window.confirm(`MOVE ${runs ? runs.length : "all local"} run(s) to the drive? Each is copied and verified, then DELETED from the operator's disk to free space. The copy is only removed locally after it's verified on the drive.`)) return;
    setMsg("");
    api.offloadStart(dest, { runs, move }).then(setJob).catch((e) => setMsg(e instanceof Error ? e.message : "failed"));
  };
  const toggle = (run: string) => setSel((s) => {
    const n = new Set(s); if (n.has(run)) n.delete(run); else n.add(run); return n;
  });
  const missing = plan.filter((p) => !p.at_dest).length;
  const pct = job?.progress && job.progress.runs_total
    ? Math.round((100 * job.progress.runs_done) / job.progress.runs_total) : 0;

  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>
        Copy runs to an external drive. Each file is hash-verified and only kept once verified;
        re-copying skips what's already there, so a yanked cable just resumes next time. Runs land
        under <code>vpi-runs/</code> on the drive.
      </div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span>destination drive</span>
        <select value={dest} onChange={(e) => pick(e.target.value)}>
          <option value="">— pick a mounted drive —</option>
          {drives.map((d) => <option key={d.path} value={d.path}>{d.name} · {gb(d.free_bytes)} GB free</option>)}
        </select>
      </div>
      <div className="actions" style={{ marginTop: 8, gap: 8 }}>
        <button className="small" onClick={loadDrives}>refresh drives</button>
        {drives.length === 0 && <span className="hint">no external drives mounted — plug one in, then refresh</span>}
      </div>

      {dest && (
        <>
          <div className="kv" style={{ marginTop: 12 }}>
            <span>runs</span><span className="v">{plan.length} total · {missing} not on drive</span>
          </div>
          <label className="row" style={{ gap: 6, marginTop: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={move} disabled={running} onChange={(e) => setMove(e.target.checked)} />
            <span>Move (delete local after verified copy — frees operator disk space)</span>
          </label>
          <div className="actions" style={{ marginTop: 8, gap: 8, flexWrap: "wrap" }}>
            <button className="cta primary" style={{ whiteSpace: "nowrap" }} disabled={running || (move ? plan.length === 0 : missing === 0)} onClick={() => start()}>{move ? `Move all (${plan.length})` : `Copy all missing (${missing})`}</button>
            <button className="cta" style={{ whiteSpace: "nowrap" }} disabled={running || sel.size === 0} onClick={() => start([...sel])}>{move ? "Move" : "Copy"} selected ({sel.size})</button>
            {running && <button className="cta" onClick={() => api.offloadCancel().then(setJob).catch(() => undefined)}>Cancel</button>}
          </div>
          {job && job.state !== "idle" && (
            <div className="cal-result" style={{ marginTop: 8 }}>
              <div className="hint" style={{ marginTop: 0 }}>
                {job.state === "running" ? `${job.mode === "move" ? "moving" : "copying"} ${job.progress?.current} · run ${job.progress?.runs_done}/${job.progress?.runs_total} · file ${job.progress?.file_done}/${job.progress?.file_total}`
                  : job.state === "done" ? `✓ done — ${job.files_copied} ${job.mode === "move" ? "moved" : "copied"}, ${job.files_skipped} already there`
                  : job.state === "cancelled" ? "cancelled" : `error — ${(job.errors ?? []).length} problem(s)`}
              </div>
              {running && (
                <div className="bar" style={{ marginTop: 6, height: 6, background: "var(--track, #2a2f3a)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${pct}%`, background: "var(--accent, #d9a441)" }} />
                </div>
              )}
              {job.errors && job.errors.length > 0 && <div className="errline" style={{ marginTop: 6 }}>{job.errors.slice(0, 3).join("; ")}</div>}
            </div>
          )}
          <div style={{ marginTop: 10, maxHeight: 240, overflowY: "auto" }}>
            {plan.map((p) => (
              <label key={p.run} className="row" style={{ justifyContent: "space-between", gap: 8, padding: "3px 0", borderTop: "1px solid var(--line)", cursor: running ? "default" : "pointer" }}>
                <span><input type="checkbox" checked={sel.has(p.run)} disabled={running} onChange={() => toggle(p.run)} /> {p.run}</span>
                {p.at_dest ? <b className="okv">on drive ✓</b> : <span className="hint">not copied</span>}
              </label>
            ))}
          </div>
        </>
      )}
      {msg && <div className="errline" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}

/** Live-tune the two knobs that pace the print between moves: the per-step wait FLOOR and the
 *  controller POLL interval during a print. Applies immediately (no restart) and persists to the
 *  install-independent config. Tighter = less dead time between moves; too tight risks a step
 *  advancing before motion settles. */
function PrintPacingPanel() {
  const [cfg, setCfg] = useState<TimingConfig | null>(null);
  const [minWait, setMinWait] = useState("");
  const [poll, setPoll] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.timing().then((t) => {
    setCfg(t); setMinWait(String(t.print_min_wait_s)); setPoll(String(t.print_poll_interval_s));
  }).catch(() => setMsg("could not load timing"));
  useEffect(() => { load(); }, []);
  const save = (body: { print_min_wait_s?: number; print_poll_interval_s?: number }) => {
    setMsg("");
    api.setTiming(body).then((t) => {
      setCfg(t); setMinWait(String(t.print_min_wait_s)); setPoll(String(t.print_poll_interval_s));
      setMsg("applied + saved");
    }).catch((e) => setMsg(e instanceof Error ? e.message : "failed"));
  };
  const apply = () => {
    const mw = Number(minWait), pp = Number(poll);
    if (!Number.isFinite(mw) || mw < 0 || mw > 5) { setMsg("wait floor must be 0–5 s"); return; }
    if (!Number.isFinite(pp) || pp < 0.02 || pp > 1) { setMsg("poll must be 0.02–1 s"); return; }
    save({ print_min_wait_s: mw, print_poll_interval_s: pp });
  };
  const d = cfg?.defaults;
  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>
        These pace the choreography BETWEEN moves. A move longer than the poll interval is detected the
        instant it finishes; only very short / no-op moves wait out the floor. Tighten both to cut the
        dead time between steps — but if a step ever advances before motion settles, raise them back.
        Applies live (no restart) and survives restarts.
      </div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span>per-step wait floor (s)</span>
        <input type="number" step="0.01" min="0" max="5" value={minWait} onChange={(e) => setMinWait(e.target.value)} />
        <span>poll interval during print (s)</span>
        <input type="number" step="0.01" min="0.02" max="1" value={poll} onChange={(e) => setPoll(e.target.value)} />
      </div>
      <div className="kv" style={{ marginTop: 10 }}>
        <span>live now</span><span className="v">{cfg ? `${cfg.print_min_wait_s}s floor · ${cfg.print_poll_interval_s}s poll` : "—"}</span>
        <span>defaults</span><span>{d ? `${d.print_min_wait_s}s · ${d.print_poll_interval_s}s` : "—"}</span>
      </div>
      <div className="actions" style={{ marginTop: 10, gap: 8 }}>
        <button className="cta primary" onClick={apply}>Apply</button>
        {d && <button className="cta" onClick={() => save({ print_min_wait_s: d.print_min_wait_s, print_poll_interval_s: d.print_poll_interval_s })}>Reset to defaults</button>}
        {msg && <span className="hint" style={{ marginTop: 0 }}>{msg}</span>}
      </div>
    </div>
  );
}

function UnattendedSciencePanel() {
  const [cams, setCams] = useState<Array<{ index: number; name: string; unique_id: string }>>([]);
  const [uid, setUid] = useState<string | null>(null);
  const [ignored, setIgnored] = useState<string[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => api.avfCameras().then((r) => { setCams(r.cameras); setUid(r.science_uid); setIgnored(r.ignored_uids); }).catch(() => setCams([]));
  useEffect(() => { load(); }, []);
  const set = (u: string | null) => api.setScienceUid(u).then((r) => { setUid(r.unique_id); setMsg(u ? "science camera bound" : "binding cleared"); }).catch(() => setMsg("failed"));
  const saveIgnored = (list: string[]) => api.setIgnoredCameras(list).then((r) => setIgnored(r.unique_ids)).catch(() => setMsg("failed"));
  const ignore = (u: string) => { if (uid !== u) void saveIgnored([...ignored, u]); };
  const unignore = (u: string) => void saveIgnored(ignored.filter((x) => x !== u));

  const rowStyle = { justifyContent: "space-between", gap: 8, padding: "5px 0", borderTop: "1px solid var(--line)" } as const;
  const active = cams.filter((c) => !ignored.includes(c.unique_id));
  const ignoredCams = cams.filter((c) => ignored.includes(c.unique_id));
  const ignoredMissing = ignored.filter((u) => !cams.some((c) => c.unique_id === u));  // unplugged but still ignored
  const ignoredCount = ignoredCams.length + ignoredMissing.length;
  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>
        Bind the science camera to a stable macOS unique id so the server grabs the correct camera even
        with no browser tab open. Identify which is which with the live tiles in the camera quick-start;
        confirm on the two-ELP rig before relying on it for a real print. Ignore the cameras you never
        use (FaceTime, iPhone) to keep the picker clean — it persists across restarts.
      </div>
      {active.length === 0 && ignoredCount === 0
        ? <div className="hint">no macOS cameras enumerated (non-macOS, or none detected)</div>
        : active.map((c) => (
            <div key={c.unique_id} className="row" style={rowStyle}>
              <span>[{c.index}] {c.name || "camera"} <small className="hint">{c.unique_id}</small></span>
              <span style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                {uid === c.unique_id
                  ? <b className="okv">science ✓</b>
                  : <button className="small" onClick={() => set(c.unique_id)}>set as science</button>}
                <button className="small" title="Hide this camera from the picker permanently" disabled={uid === c.unique_id} onClick={() => ignore(c.unique_id)}>ignore</button>
              </span>
            </div>
          ))}
      {ignoredCount > 0 && (
        <div style={{ marginTop: 8 }}>
          <button className="small" onClick={() => setShowIgnored((v) => !v)}>{showIgnored ? "hide" : "show"} {ignoredCount} ignored</button>
          {showIgnored && (
            <>
              {ignoredCams.map((c) => (
                <div key={c.unique_id} className="row" style={{ ...rowStyle, opacity: 0.6 }}>
                  <span>[{c.index}] {c.name || "camera"} <small className="hint">{c.unique_id}</small></span>
                  <button className="small" onClick={() => unignore(c.unique_id)}>un-ignore</button>
                </div>
              ))}
              {ignoredMissing.map((u) => (
                <div key={u} className="row" style={{ ...rowStyle, opacity: 0.6 }}>
                  <span><span className="hint">not connected</span> <small className="hint">{u}</small></span>
                  <button className="small" onClick={() => unignore(u)}>un-ignore</button>
                </div>
              ))}
            </>
          )}
        </div>
      )}
      <div className="actions" style={{ marginTop: 8, gap: 8 }}>
        <button className="small" onClick={load}>refresh</button>
        {uid && <button className="small" onClick={() => set(null)}>clear binding</button>}
        {msg && <span className="hint">{msg}</span>}
      </div>
    </div>
  );
}

export function SettingsView({ status, gates, call, base, onOpenQuickStart }: {
  status: StatusPayload | null; gates: Gates; call: Call; base: string;
  /** A7: reopens the camera-role quick-start wizard any time (cameras swapped/replaced/re-cabled) */
  onOpenQuickStart: () => void;
}) {
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [sel, setSel] = useState<string>("pistons");
  useEffect(() => { api.printSettings().then((r) => setPlan(r.plan as Record<string, unknown>)).catch(() => undefined); }, []);
  const ok = gates.controllable && !gates.printActive;
  const pistonLock = !gates.controllable
    ? (gates.connected ? "read-only — take control from the connection pill to jog" : "connect + take control to jog the pistons")
    : gates.printActive ? "a print is running — piston jog is locked" : null;

  // Settings master-detail: pick an item on the left, it opens in the pane on the right. Independent
  // sections (not a wizard) — the calibration ones read top-to-bottom on first commissioning.
  const SECTIONS = [
    { key: "pistons", title: "Pistons", sub: "per-cylinder travel" },
    { key: "assign", title: "Cameras", sub: "identify & assign" },
    { key: "camset", title: "Camera settings", sub: "res · fps · exposure" },
    { key: "board", title: "Calibration board", sub: "ChArUco / checkerboard" },
    { key: "calib", title: "Calibrate", sub: "intrinsics & bed plane" },
    { key: "validate", title: "Validate", sub: "dimensional ±0.1 mm" },
    { key: "pose", title: "Capture pose", sub: "overhead science cam" },
    { key: "manual", title: "Manual calibration", sub: "raw image↔world points" },
    { key: "unattended", title: "Unattended science", sub: "bind camera by UID" },
    { key: "offload", title: "Data offload", sub: "copy runs to a drive" },
    { key: "pacing", title: "Print pacing", sub: "inter-move timing" },
  ];
  const current = SECTIONS.find((s) => s.key === sel) ?? SECTIONS[0];

  return (
    <div className="view fixed-page">
      <div className="sec-h">settings</div>
      <div className="setup-grid">
        <div className="card">
          <ol className="srail">
            {SECTIONS.map((s) => (
              <li key={s.key} className={sel === s.key ? "on" : ""} aria-current={sel === s.key ? "true" : undefined} onClick={() => setSel(s.key)}>
                <span className="n" />
                <div><div className="t">{s.title}</div><div className="sd">{s.sub}</div></div>
              </li>
            ))}
          </ol>
        </div>

        <div className="card">
          <h3>{current.title} <span className="hint" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 400 }}>· {current.sub}</span></h3>

          {sel === "pistons" && (
            <div className="grid-gap">
              {pistonLock && <div className="lock" style={{ marginTop: 0 }}>{pistonLock}</div>}
              <div className="hint" style={{ marginTop: 0 }}>Jog each piston to its physical stop and set its max — that's the usable range for the current cylinder. A build deeper than the build max is blocked before it under-builds.</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
                {/* Feed on the left, build on the right — the physical/intuitive layout of the machine. */}
                <Piston axis={2} name="feed" field="feed_piston_max_mm" status={status} ok={ok} call={call} plan={plan} onPlan={setPlan} />
                <Piston axis={1} name="build" field="build_piston_max_mm" status={status} ok={ok} call={call} plan={plan} onPlan={setPlan} />
              </div>
            </div>
          )}
          {sel === "assign" && (
            <div className="grid-gap">
              <div className="note">📷 Nothing opens a camera until a page asks for it. Assign each camera by its live feed — the two share a name, so the picture is how you tell them apart: set one as overview (wide live view) and one as science (bed stills). Remembered and auto-reconnected; if a camera doesn't appear, use Rescan.</div>
              <CameraRoleAssigner />
              <div className="btnrow">
                <button className="cta primary" onClick={onOpenQuickStart}>Identify &amp; assign cameras…</button>
                <button className="small" disabled={!gates.reachable} onClick={() => call("rescan cameras", () => api.visionDevices())}>Rescan devices</button>
              </div>
            </div>
          )}
          {sel === "camset" && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>One panel per camera: live preview, a resolution dropdown, an fps slider on the mode's real scale, an exposure slider read from the camera (in ms), and the YUY2/MJPG format for recorded stills (YUY2 = lossless for CAD). Assign the cameras first; settings are remembered per camera.</div>
              <div className="cols-2">
                <CameraSettingsPanel role="overview" />
                <CameraSettingsPanel role="science" />
              </div>
            </div>
          )}
          {sel === "board" && <CalibrationBoardPanel base={base} />}
          {sel === "calib" && (
            <div className="grid-gap">
              <div className="hint" style={{ marginTop: 0 }}>Capture ≥3 board views from different bed positions / tilts, then finalize with "use the last board view as the bed reference" ticked — that sets the bed plane so mm map to the bed, not the camera.</div>
              <CalibrationWizard call={call} printing={gates.printActive} />
            </div>
          )}
          {sel === "validate" && <ValidationPanel call={call} printing={gates.printActive} />}
          {sel === "pose" && <CaptureCalibration status={status} gates={gates} call={call} base={base} />}
          {sel === "manual" && <div className="body"><CalibrationForm call={call} disabled={!gates.reachable} /></div>}
          {sel === "unattended" && <UnattendedSciencePanel />}
          {sel === "offload" && <DataOffloadPanel />}
          {sel === "pacing" && <PrintPacingPanel />}
        </div>
      </div>
    </div>
  );
}
