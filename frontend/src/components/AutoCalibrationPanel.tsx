import { useEffect, useRef, useState } from "react";
import { api, type AutocalReport, type AutocalSession } from "../lib/api.ts";
import { preflight, RECOATER_AXIS, runSweep, waitSettled } from "../lib/autocal.ts";
import { boardDefError, describeBoardDef, loadBoardDef, sessionSpecFromDef } from "../lib/board_def.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import { cleanNum } from "../lib/format.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { CalibrationSizeNote } from "./CalibrationSizeNote.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;
const SECONDS_PER_POSE = 3;

type Phase = "idle" | "confirm" | "running" | "solving" | "result";
interface Shot { pose: number; mm: number; usable: boolean; corners: number; url: string; size: [number, number]; pts: [number, number][] }

/** One-button science-camera calibration (spec docs/superpowers/specs/2026-10-20-auto-calibration-
 *  design.md): place the board, press Start, confirm the planned recoater positions, watch. The
 *  browser steps the recoater (the science camera rides it) inside the safety window, takes each
 *  still through the print capture path and uploads it with the position read back from telemetry;
 *  the operator detects, solves and judges. Nothing moves before the on-page confirm; Stop halts. */
export function AutoCalibrationPanel({ status, printing }: { status: StatusPayload | null; printing: boolean }) {
  const board = loadBoardDef(storage);
  const boardErr = board ? boardDefError(board) : "no board generated in this browser";
  const [capturePose, setCapturePose] = useState(0);
  const [winMin, setWinMin] = useState("0");
  const [winMax, setWinMax] = useState("523");
  const [placement, setPlacement] = useState<"substrate" | "cylinder">("substrate");
  const [thickness, setThickness] = useState("3.175");
  const [phase, setPhase] = useState<Phase>("idle");
  const [session, setSession] = useState<AutocalSession | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [cells, setCells] = useState<boolean[][] | null>(null);
  const [report, setReport] = useState<AutocalReport | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [returnArmed, setReturnArmed] = useState(false);
  const stopRef = useRef(false);

  useEffect(() => {
    api.printSettings().then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setCapturePose(typeof v === "number" ? v : 0);
    }).catch(() => undefined);
    api.autocalWindow().then((w) => { setWinMin(String(w.min_mm)); setWinMax(String(w.max_mm)); }).catch(() => undefined);
  }, []);

  const problems = [
    ...(printing ? ["A print is running — wait until it finishes."] : []),
    ...preflight({ status, capturePoseMm: capturePose, scienceAssigned: !!loadRoleMap(storage).science, boardOk: !boardErr }),
  ];
  const busy = phase === "running" || phase === "solving";

  const plan = async () => {
    setErr(null); setReport(null); setSaved(null); setShots([]); setCells(null);
    try {
      const s = await api.autocalStart({
        spec: sessionSpecFromDef(board!), window_min_mm: Number(winMin), window_max_mm: Number(winMax),
        placement, board_thickness_mm: Number(thickness),
      });
      setSession(s); setPhase("confirm");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const run = async () => {
    if (!session) return;
    stopRef.current = false;
    setPhase("running"); setErr(null);
    try {
      const outcome = await runSweep(
        { poses: session.poses, preApproachMm: session.pre_approach_mm, captureMm: session.capture_mm },
        {
          move: async (mm) => { await api.move(RECOATER_AXIS, "abs", mm); },
          settle: () => waitSettled(() => api.status(), RECOATER_AXIS),
          capture: () => captureScienceStillOnce(storage),
          readMm: async () => {
            const v = (await api.status()).controller?.telemetry?.positions?.[String(RECOATER_AXIS)];
            if (typeof v !== "number" || !Number.isFinite(v)) throw new Error("no recoater position from the machine");
            return v;
          },
          sample: async (blob, mm) => {
            const r = await api.autocalSample(blob, mm);
            if (r.coverage_cells) setCells(r.coverage_cells);
            setShots((prev) => [...prev, {
              pose: mm, mm, usable: r.usable, corners: r.corners, url: URL.createObjectURL(blob),
              size: r.image_size, pts: r.corners_px ?? [],
            }]);
            return r;
          },
          stopped: () => stopRef.current,
          stopMotion: async () => { await api.stop().catch(() => undefined); },
        },
      );
      if (outcome === "stopped") { setPhase("idle"); setErr("Stopped. Nothing was saved; the recoater stayed where it was."); return; }
      setPhase("solving");
      setReport(await api.autocalSolve());
      setPhase("result");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  };

  const stop = () => { stopRef.current = true; void api.stop().catch(() => undefined); };
  const save = async () => {
    try { setSaved((await api.autocalSave()).calibration_version); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const returnToPose = async () => {
    setReturnArmed(false);
    try { await api.move(RECOATER_AXIS, "abs", capturePose); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const last = shots.at(-1);
  return (
    <div className="grid-gap">
      <div className="hint" style={{ marginTop: 0 }}>
        Place the ChArUco board once, press Start, confirm the planned recoater positions, and watch. The science camera rides
        the recoater, so the machine moves the camera across the board; no clicking per photo.
      </div>
      <div className={boardErr ? "warnline" : "okline"}>
        Board: {board ? describeBoardDef(board) : "—"}{boardErr ? ` — ${boardErr} (Settings → Calibration board)` : ""}
      </div>
      <div className="fields">
        <span title="Where the board sits: on the static substrate (square) or down in the build cylinder (round).">board placement</span>
        <select value={placement} onChange={(e) => setPlacement(e.target.value as "substrate" | "cylinder")} disabled={busy}>
          <option value="substrate">on the substrate</option>
          <option value="cylinder">in the build cylinder</option>
        </select>
        <span title="Recorded with the calibration so the offset from the print plane can be corrected later.">board thickness (mm)</span>
        <input type="number" step="0.001" min={0} value={thickness} onChange={(e) => setThickness(e.target.value)} disabled={busy} />
        <span title="The recoater never moves outside this range. With the board on the substrate, 523 mm keeps the blade off the board.">safety window (mm)</span>
        <span className="row" style={{ gap: 6 }}>
          <input type="number" step="1" value={winMin} onChange={(e) => setWinMin(e.target.value)} style={{ width: 80 }} disabled={busy} /> to
          <input type="number" step="1" value={winMax} onChange={(e) => setWinMax(e.target.value)} style={{ width: 80 }} disabled={busy} />
        </span>
        <span>capture pose</span><span>{capturePose > 0 ? `${capturePose.toFixed(1)} mm` : "not set"}</span>
      </div>
      {problems.length > 0 && phase === "idle" && (
        <div className="warnline">
          Before starting:<ul style={{ margin: "4px 0 0 18px" }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      {err && <div className="errline">{err}</div>}
      {phase === "idle" && (
        <div className="actions one tight">
          <button className="cta primary" disabled={problems.length > 0} onClick={() => void plan()}>start calibration</button>
        </div>
      )}
      {phase === "confirm" && session && (
        <div className="warnline">
          The recoater will move to {cleanNum(session.pre_approach_mm, 1)} mm, then step down through {session.poses.length} positions
          ({cleanNum(session.poses[0], 1)} → {cleanNum(session.poses.at(-1) ?? 0, 1)} mm), all inside {cleanNum(session.window.min_mm, 1)}–{cleanNum(session.window.max_mm, 1)} mm.
          About {Math.round((session.poses.length + 1) * SECONDS_PER_POSE)} s. Keep clear of the gantry.
          <div className="actions one tight" style={{ marginTop: 8 }}>
            <button className="cta primary" onClick={() => void run()}>move and calibrate</button>
            <button className="cta" onClick={() => { setPhase("idle"); void api.autocalCancel(); }}>cancel</button>
          </div>
        </div>
      )}
      {(phase === "running" || phase === "solving") && (
        <div className="actions one tight">
          <span className="hint" style={{ margin: 0 }}>{phase === "running" ? `photo ${shots.length} of ${session?.poses.length ?? "?"}` : "solving…"}</span>
          {phase === "running" && <button className="cta" onClick={stop}>stop</button>}
        </div>
      )}
      {last && (
        <div className="cols-2">
          <div style={{ position: "relative", maxWidth: 480 }}>
            <img src={last.url} alt="latest calibration photo" style={{ width: "100%", display: "block" }} />
            <svg viewBox={`0 0 ${last.size[0]} ${last.size[1]}`} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
              {last.pts.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={Math.max(4, last.size[0] / 160)} fill="var(--accent)" />)}
            </svg>
          </div>
          <div>
            <div className="kv">
              {shots.map((s, i) => <span key={i} style={{ display: "contents" }}><span>{s.mm.toFixed(1)} mm</span><span>{s.usable ? `${s.corners} corners` : "board not found"}</span></span>)}
            </div>
            {cells && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 30px)", gap: 4, marginTop: 8 }} title="where corners have been seen in the photo">
                {cells.flatMap((row, r) => row.map((on, c) => <div key={`${r}${c}`} style={{ width: 30, height: 22, borderRadius: 4, background: on ? "var(--ok, #2e7d32)" : "var(--track, #2a2f3a)" }} />))}
              </div>
            )}
          </div>
        </div>
      )}
      {phase === "result" && report && (
        <div>
          <div className={report.passed ? "okline" : "errline"}>
            {report.passed ? "Calibration passed." : "Calibration did not pass — nothing was saved."}
            {report.reasons.length > 0 && <ul style={{ margin: "4px 0 0 18px" }}>{report.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          </div>
          <div className="kv">
            <span>lens fit</span><span>{report.reprojection_rms_px.toFixed(3)} px RMS (limit 0.5)</span>
            <span>encoder-shift check</span><span>{report.shift_rms_mm.toFixed(3)} mm RMS, worst {report.shift_worst_mm.toFixed(3)} mm (limit 0.1 RMS)</span>
            <span>scale vs recoater</span><span>{report.scale_ratio.toFixed(4)}</span>
            <span>usable photos</span><span>{report.n_views} (need 5)</span>
            <span>photo size</span><span>{report.image_size[0]}×{report.image_size[1]}</span>
            <span>calibrated area</span><span>{report.bed_extent_mm.join(", ")} mm (where corners were seen)</span>
            <span>plane</span><span>{report.plane_note}; {report.placement}, board {report.board_thickness_mm} mm thick</span>
          </div>
          <div className="actions one tight">
            {report.passed && !saved && <button className="cta primary" onClick={() => void save()}>save calibration</button>}
            {saved && <span className="okline" style={{ margin: 0 }}>Saved as {saved}. Next: Settings → Validate.</span>}
            <button className="cta" onClick={() => { setPhase("idle"); setSession(null); }}>start over</button>
          </div>
          <CalibrationSizeNote refreshKey={saved ? 1 : 0} />
        </div>
      )}
      {capturePose > 0 && !busy && shots.length > 0 && (
        <div className="actions one tight">
          {!returnArmed
            ? <button className="cta" onClick={() => setReturnArmed(true)}>return recoater to capture pose</button>
            : <button className="cta primary" onClick={() => void returnToPose()}>confirm move to {capturePose.toFixed(1)} mm</button>}
        </div>
      )}
    </div>
  );
}
