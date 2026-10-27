import { useEffect, useRef, useState } from "react";
import { api, type AutocalReport, type AutocalSession } from "../lib/api.ts";
import { lensFitText, preflight, RECOATER_AXIS, runSweep, selfCheckSummary, type SelfCheckResult, waitSettled } from "../lib/autocal.ts";
import { boardDefError, calibBoardChoices, defaultBoardChoice, loadBoardDef, saveBoardDef } from "../lib/board_def.ts";
import { autocalSpec, CERTIFIED_PLATE, lengthReferenceText } from "../lib/autocal_board.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import { cleanNum } from "../lib/format.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { CalibrationSizeNote } from "./CalibrationSizeNote.tsx";
import { CalibrationRunReport, type LastSweep } from "./CalibrationRunReport.tsx";
import { canSolvePartial } from "../lib/autocal_report.ts";
import { convexHull, markerQuads } from "../lib/overlay_geom.ts";
import { CalibrationOverlay } from "./CalibrationOverlay.tsx";
import { CalibrationLivePreview } from "./CalibrationLivePreview.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;
const PLATE_PICKED = "vpi.autocal.plate.v1";  // the certified plate was the last board picked here
const readPlatePicked = () => { try { return storage?.getItem(PLATE_PICKED) === "1"; } catch { return false; } };
const SECONDS_PER_POSE = 3;

type Phase = "idle" | "confirm" | "running" | "solving" | "result" | "placing";
interface Shot { pose: number; mm: number; usable: boolean; corners: number; url: string; size: [number, number]; pts: [number, number][]; nChess: number; placement: number }

/** One-button science-camera calibration (spec docs/superpowers/specs/2026-10-20-auto-calibration-
 *  design.md): place the board, press Start, confirm the planned recoater positions, watch. The
 *  browser steps the recoater (the science camera rides it) inside the safety window, takes each
 *  still through the print capture path and uploads it with the position read back from telemetry;
 *  the operator detects, solves and judges. Nothing moves before the on-page confirm; Stop halts. */
export function AutoCalibrationPanel({ status, printing }: { status: StatusPayload | null; printing: boolean }) {
  // The board is picked right here (presets + a custom board saved from the Calibration board
  // page); the choice is remembered in this browser. A wrong square size cannot pass silently: the
  // encoder-shift scale check fails the run.
  const [savedBoard] = useState(() => loadBoardDef(storage));
  const boardChoices = calibBoardChoices(savedBoard);
  const [boardKey, setBoardKey] = useState(() => readPlatePicked() ? CERTIFIED_PLATE.key : defaultBoardChoice(boardChoices, savedBoard));
  const plate = boardKey === CERTIFIED_PLATE.key;
  const board = boardChoices.find((c) => c.key === boardKey)?.def ?? null;
  const boardErr = plate ? null : board ? boardDefError(board) : "pick the board you placed";
  const pickBoard = (key: string) => {
    setBoardKey(key);
    try { storage?.setItem(PLATE_PICKED, key === CERTIFIED_PLATE.key ? "1" : "0"); } catch { /* storage disabled */ }
    const def = boardChoices.find((c) => c.key === key)?.def;
    if (def) saveBoardDef(storage, def);
  };
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
  const [selfCheck, setSelfCheck] = useState<(SelfCheckResult & { url: string; size: [number, number] }) | null>(null);
  const [checking, setChecking] = useState(false);
  const [lastRun, setLastRun] = useState<LastSweep | null>(null);  // the operator's last solved sweep (report)
  const [compare, setCompare] = useState<{ busy: boolean; data?: import("../lib/api.ts").DetectionComparison; err?: string } | null>(null);
  const [overlays, setOverlays] = useState<{ raw?: string; corrected?: string; residuals?: string; err?: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [returnArmed, setReturnArmed] = useState(false);
  const stopRef = useRef(false);
  const runningRef = useRef(false);

  useEffect(() => {
    api.printSettings().then((p) => {
      const v = (p.plan as Record<string, unknown>).capture_recoater_mm;
      setCapturePose(typeof v === "number" ? v : 0);
    }).catch(() => undefined);
    api.autocalWindow().then((w) => { setWinMin(String(w.min_mm)); setWinMax(String(w.max_mm)); }).catch(() => undefined);
    api.autocalLast().then(setLastRun).catch(() => undefined);
  }, []);

  // Solve (the full sweep, or what a stopped run already photographed) and load its saved report.
  const solve = async () => {
    setPhase("solving"); setErr(null); setSelfCheck(null);
    try {
      setReport(await api.autocalSolve());
      setLastRun(await api.autocalLast().catch(() => null));
      setPhase("result");
      // The capture-pose photo with the solved bed grid + calibrated area drawn on it.
      Promise.all([api.autocalOverlay("raw"), api.autocalOverlay("corrected"), api.autocalOverlay("residuals")])
        .then(([raw, corrected, residuals]) => setOverlays({ raw: URL.createObjectURL(raw), corrected: URL.createObjectURL(corrected), residuals: URL.createObjectURL(residuals) }))
        .catch((e) => setOverlays({ err: e instanceof Error ? e.message : String(e) }));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setPhase("idle"); }
  };

  const check = (s: StatusPayload | null) => preflight({
    status: s, capturePoseMm: capturePose, scienceAssigned: !!loadRoleMap(storage).science, boardOk: !boardErr,
    printActive: printing || s?.print?.state === "running" || s?.print?.state === "paused",  // = gates.printActive
  });
  const problems = check(status);
  // Re-check against a FRESH status right before any motion (the machine can change while the
  // confirm screen is open: power-cycle -> unreferenced, a print starting, ...).
  const freshProblems = async () => check(await api.status().catch(() => null));
  const busy = phase === "running" || phase === "solving";

  const plan = async () => {
    setErr(null); setReport(null); setSaved(null); setShots([]); setCells(null); setSelfCheck(null); setOverlays(null); setPlacementIdx(0);
    try {
      const s = await api.autocalStart({
        spec: autocalSpec(boardKey, board)!, window_min_mm: Number(winMin), window_max_mm: Number(winMax),
        placement, board_thickness_mm: Number(thickness),
      });
      setSession(s); setPhase("confirm");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  // Another board placement in the same run (2026-10-26: one placement only covers a band of the
  // frame; the rest of the lens was extrapolated). Nothing moves until "sweep this placement".
  const [placementIdx, setPlacementIdx] = useState(0);
  const addPlacement = async () => {
    try {
      const r = await api.autocalNewPlacement();
      setPlacementIdx(r.placement); setSession(r.session); setSelfCheck(null); setOverlays(null); setErr(null);
      setPhase("placing");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const run = async () => {
    if (!session || runningRef.current) return;
    const blockers = await freshProblems();
    if (blockers.length) { setErr(`Not moving: ${blockers.join(" ")}`); return; }
    runningRef.current = true;
    stopRef.current = false;
    setPhase("running"); setErr(null);
    try {
      const outcome = await runSweep(
        { poses: session.poses, preApproachMm: session.pre_approach_mm, captureMm: session.capture_mm,
          windowMinMm: session.window.min_mm, windowMaxMm: session.window.max_mm },
        {
          move: async (mm) => { await api.move(RECOATER_AXIS, "abs", mm); },
          settle: (targetMm) => waitSettled(() => api.status(), RECOATER_AXIS, { targetMm }),
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
              size: r.image_size, pts: r.corners_px ?? [], nChess: r.chessboard_corners ?? (r.corners_px ?? []).length,
              placement: placementIdx,
            }]);
            return r;
          },
          stopped: () => stopRef.current,
          stopMotion: async () => { await api.stop().catch(() => undefined); },
        },
      );
      if (outcome === "stopped") { setPhase("idle"); setErr("Stopped. Nothing was saved; the recoater stayed where it was. The photos taken so far are kept."); return; }
      await solve();
    } catch (e) {
      // Keep the photos already taken: the run can still be solved from them (below).
      setErr(`${e instanceof Error ? e.message : String(e)} The photos taken so far are kept.`);
      setPhase("idle");
    } finally {
      runningRef.current = false;
    }
  };

  // ChArUco self-check (spec 2026-10-21 §2): the board moved, one photo, scored against the PENDING
  // solve; Save opens only when it passed. No motion: any recoater position works.
  const takeSelfCheck = async () => {
    setChecking(true); setErr(null);
    try {
      const blob = await captureScienceStillOnce(storage);
      const bmp = await createImageBitmap(blob);
      const size: [number, number] = [bmp.width, bmp.height];
      bmp.close();
      const r = await api.autocalSelfCheck(blob);
      setSelfCheck({ ...r, url: URL.createObjectURL(blob), size });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setChecking(false); }
  };
  const stop = () => { stopRef.current = true; void api.stop().catch(() => undefined); };
  const save = async () => {
    try { setSaved((await api.autocalSave()).calibration_version); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const returnToPose = async () => {
    setReturnArmed(false);
    const blockers = await freshProblems();
    if (blockers.length) { setErr(`Not moving: ${blockers.join(" ")}`); return; }
    try { await api.move(RECOATER_AXIS, "abs", session?.capture_mm ?? capturePose); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const last = shots.at(-1);
  return (
    <div className="grid-gap">
      <div className="hint" style={{ marginTop: 0 }}>
        Place the board once, press Start, confirm the planned recoater positions, and watch. The science camera rides
        the recoater, so the machine moves the camera across the board; no clicking per photo.
      </div>
      <div className="fields">
        <span title="The board you placed. The certified chessboard is flat and manufactured, so its squares are the length reference. A ChArUco board needs its exact squares, sizes and marker dictionary; a custom board made on the Calibration board page appears here too.">calibration board</span>
        <select value={boardKey} onChange={(e) => pickBoard(e.target.value)} disabled={busy || phase !== "idle"}>
          <option value={CERTIFIED_PLATE.key}>{CERTIFIED_PLATE.label}</option>
          {boardChoices.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <span title="Where the board sits: on the static substrate (square) or down in the build cylinder (round).">board placement</span>
        <select value={placement} onChange={(e) => setPlacement(e.target.value as "substrate" | "cylinder")} disabled={busy}>
          <option value="substrate">on the substrate</option>
          <option value="cylinder">in the build cylinder</option>
        </select>
        <span title={plate ? "Caliper-measure the plate: its top surface is the plane this calibration measures on." : "Recorded with the calibration so the offset from the print plane can be corrected later."}>board thickness (mm)</span>
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
      {phase === "idle" && session && shots.length > 0 && (
        <div className={canSolvePartial(shots, 5) ? "hint" : "warnline"} style={{ margin: 0 }}>
          This run stopped after {shots.length} photos ({shots.filter((s) => s.usable).length} with the board found).
          {canSolvePartial(shots, 5)
            ? " You can solve from them instead of starting again."
            : " That is too few to solve (need 5 with the board found); start again."}
          {canSolvePartial(shots, 5) && (
            <div className="actions one tight" style={{ marginTop: 6 }}>
              <button className="cta primary" onClick={() => void solve()}>solve the {shots.filter((s) => s.usable).length} photos taken</button>
            </div>
          )}
        </div>
      )}
      {phase === "idle" && (
        <div className="actions one tight">
          <button className="cta primary" disabled={problems.length > 0} onClick={() => void plan()}>start calibration</button>
        </div>
      )}
      {phase === "idle" && !shots.length && lastRun && (
        <details>
          <summary>Last run report</summary>
          <CalibrationRunReport last={lastRun} />
        </details>
      )}
      {plate && phase === "idle" && (
        <div className="hint" style={{ margin: 0 }}>
          Certified chessboard: the plate must be fully in the photo at the capture pose (it is: 81 mm in a ~95 mm view), so
          the photos near it number every corner; further along the sweep the plate runs off the photo and the encoder
          fixes which corners those are. A photo that cannot be numbered safely is dropped and listed.
        </div>
      )}
      {board && !plate && phase !== "running" && phase !== "solving" && (
        <details open={phase === "result"}>
          <summary>Live view with the identified points{phase === "result" ? " (place the board for the self-check)" : ""}</summary>
          <CalibrationLivePreview board={board} covered={
            shots.length ? { size: shots[0].size, points: shots.filter((x) => x.usable).flatMap((x) => x.pts) }
              : lastRun ? { size: lastRun.image_size, points: lastRun.views.flatMap((v) => v.image_points) } : null} />
        </details>
      )}
      {phase === "placing" && session && (
        <div className="warnline">
          Placement {placementIdx + 1}: move the board to a part of the bed the previous sweep{placementIdx > 1 ? "s" : ""} did not cover —
          to the left or right of where it was, flat on the same surface, still in view at the capture pose. The live view below shows
          the area already covered (dashed). Then sweep this placement; the recoater makes the same moves as before
          ({cleanNum(session.poses[0], 1)} → {cleanNum(session.poses.at(-1) ?? 0, 1)} mm). The solve combines every placement.
          <div className="actions one tight" style={{ marginTop: 8 }}>
            <button className="cta primary" onClick={() => void run()}>sweep this placement</button>
            <button className="cta" onClick={() => setPhase("result")} disabled={!report}>back to the result</button>
          </div>
        </div>
      )}
      {phase === "confirm" && session && (
        <div className="warnline">
          The recoater (now at {(() => { const v = status?.controller?.telemetry?.positions?.[String(RECOATER_AXIS)]; return typeof v === "number" ? `${cleanNum(v, 1)} mm` : "an unknown position"; })()}) will move to {cleanNum(session.pre_approach_mm, 1)} mm, then step down through {session.poses.length} positions
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
          <span className="hint" style={{ margin: 0 }}>{phase === "running" ? `placement ${placementIdx + 1}: photo ${shots.filter((x) => x.placement === placementIdx).length} of ${session?.poses.length ?? "?"}` : "solving…"}</span>
          {phase === "running" && <button className="cta" onClick={stop}>stop</button>}
        </div>
      )}
      {last && (
        <div className="cols-2">
          <div style={{ position: "relative", maxWidth: 480 }}>
            <img src={last.url} alt="latest calibration photo" style={{ width: "100%", display: "block" }} />
            <CalibrationOverlay size={last.size} chess={last.pts.slice(0, last.nChess)} markers={last.pts.slice(last.nChess)}
              quads={markerQuads(last.pts, last.nChess)} hull={convexHull(shots.filter((x) => x.usable).flatMap((x) => x.pts))} />
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
            <span>lens fit</span><span>{lensFitText(report)}</span>
            <span>plane</span><span>{report.plane_note}; {report.placement}, board {report.board_thickness_mm} mm thick</span>
            <span>length reference</span><span>{lengthReferenceText(report)}</span>
            {(report.dropped_views?.length ?? 0) > 0 && (<>
              <span>photos dropped</span>
              <span>{report.dropped_views!.map((d) => `${d.recoater_mm.toFixed(1)} mm: ${d.reason}`).join("; ")}</span>
            </>)}
          </div>
          {overlays && (overlays.err
            ? <div className="warnline">Overlay unavailable: {overlays.err}</div>
            : (
              <div className="cols-2" style={{ marginTop: 8 }}>
                <figure style={{ margin: 0 }}>
                  {overlays.raw && <img src={overlays.raw} alt="capture-pose photo with the predicted board grid" style={{ width: "100%", display: "block" }} />}
                  <figcaption className="hint" style={{ margin: "4px 0 0" }}>As photographed (capture pose): amber = the board's square edges where the new calibration predicts them; they should lie exactly on the real edges. Green = calibrated area.</figcaption>
                </figure>
                <figure style={{ margin: 0 }}>
                  {overlays.residuals && <img src={overlays.residuals} alt="capture-pose photo with lens-fit residual arrows" style={{ width: "100%", display: "block" }} />}
                  <figcaption className="hint" style={{ margin: "4px 0 0" }}>Lens-fit residual of every point at the capture pose: direction and size, enlarged (factor printed on the photo). Arrows lined up in one direction show a systematic misfit; scattered ones are noise.</figcaption>
                </figure>
                <figure style={{ margin: 0 }}>
                  {overlays.corrected && <img src={overlays.corrected} alt="the same photo corrected onto the bed" style={{ width: "100%", display: "block" }} />}
                  <figcaption className="hint" style={{ margin: "4px 0 0" }}>Corrected onto the bed (lens distortion removed): the board's edges should now be straight and on the amber grid. Green = calibrated area.</figcaption>
                </figure>
              </div>
            ))}
          {lastRun ? <CalibrationRunReport last={lastRun} /> : <div className="hint">Loading the run report…</div>}
          <div className="grid-gap" style={{ marginTop: 8 }}>
            {!plate && <div className="actions one tight">
              <button className="cta" disabled={compare?.busy} onClick={() => {
                setCompare({ busy: true });
                api.autocalCompareDetection().then((data) => setCompare({ busy: false, data }))
                  .catch((e) => setCompare({ busy: false, err: e instanceof Error ? e.message : String(e) }));
              }}>{compare?.busy ? "comparing detection methods… (1–2 min)" : "compare detection methods on these photos"}</button>
            </div>}
            {!plate && <div className="hint" style={{ margin: 0 }}>Re-detects this run's stored photos three ways (as now; marker corners not refined; corners placed through the solved lens, as the OpenCV ChArUco tutorial advises) and measures each on photos the fit never saw. Nothing changes until the numbers say so.</div>}
            {compare?.err && <div className="errline" style={{ margin: 0 }}>{compare.err}</div>}
            {compare?.data && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
                  <thead><tr>{["method", "photos", "error on unseen photos (mean ± SD)", "worst point", "lens fit", "encoder shift"].map((h) => <th key={h} style={{ textAlign: "left", fontWeight: 500, color: "var(--muted)", borderBottom: "1px solid var(--line)", padding: "4px 8px" }}>{h}</th>)}</tr></thead>
                  <tbody>{compare.data.methods.map((m) => (
                    <tr key={m.method}>
                      <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)" }}>{m.label}</td>
                      <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)" }}>{m.n_photos}</td>
                      {m.error
                        ? <td colSpan={4} style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)", color: "var(--err)" }}>{m.error}</td>
                        : <>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>{m.heldout_mean_mm == null ? "—" : `${m.heldout_mean_mm.toFixed(3)} ± ${(m.heldout_sd_mm ?? 0).toFixed(3)} mm`}</td>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>{m.heldout_worst_mm == null ? "—" : `${m.heldout_worst_mm.toFixed(3)} mm`}</td>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>{m.lens_mm == null ? "—" : `${m.lens_mm.toFixed(3)} mm`}</td>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid var(--line)", fontFamily: "var(--font-mono)" }}>{m.shift_rms_mm == null ? "—" : `${m.shift_rms_mm.toFixed(3)} mm`}</td>
                        </>}
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
          {report.passed && !saved && (
            <div className="grid-gap" style={{ marginTop: 8 }}>
              <div className="hint" style={{ margin: 0 }}>
                Self-check before saving: move or rotate the board anywhere in view (keep it flat on the same surface), then take a
                self-check photo. Every board point is mapped through this new calibration and the distances between points are
                compared with the board's true distances. Only points inside the calibrated area count.
              </div>
              <div className="actions one tight">
                <button className="cta" disabled={checking} onClick={() => void takeSelfCheck()}>{checking ? "checking…" : selfCheck ? "retake self-check photo" : "take self-check photo"}</button>
              </div>
              {selfCheck && (() => {
                const v = selfCheckSummary(selfCheck);
                return (
                  <div className="cols-2">
                    <div style={{ position: "relative", maxWidth: 480 }}>
                      <img src={selfCheck.url} alt="self-check photo" style={{ width: "100%", display: "block" }} />
                      <svg viewBox={`0 0 ${selfCheck.size[0]} ${selfCheck.size[1]}`} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
                        {(selfCheck.corners_px ?? []).map(([x, y], i) => <circle key={i} cx={x} cy={y} r={Math.max(4, selfCheck.size[0] / 160)} fill="var(--accent)" />)}
                      </svg>
                    </div>
                    <div className={v.tone === "ok" ? "okline" : v.tone === "warn" ? "warnline" : "errline"}>
                      {v.headline}
                      <div style={{ marginTop: 4 }}>{v.detail}</div>
                      {selfCheck.reasons.length > 0 && <ul style={{ margin: "4px 0 0 18px" }}>{selfCheck.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
          <div className="actions one tight">
            {report.passed && !saved && <button className="cta primary" disabled={!selfCheck?.passed} title={selfCheck?.passed ? undefined : "Run a passing self-check first."} onClick={() => void save()}>save calibration</button>}
            {saved && <span className="okline" style={{ margin: 0 }}>Saved as {saved}. Next: Settings → Validate.</span>}
            {!saved && <button className="cta" title="Move the board to a part of the bed this run has not covered, then sweep again; the solve combines all placements." onClick={() => void addPlacement()}>add a board placement</button>}
            <button className="cta" onClick={() => { setPhase("idle"); setSession(null); setSelfCheck(null); setPlacementIdx(0); }}>start over</button>
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
