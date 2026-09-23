import { useState } from "react";
import { api, type VisionCalibFinalizeResult, type VisionCalibSession } from "../lib/api.ts";
import { ARUCO_4X4_FAMILY, PRESET_GEOMETRY, pickArucoDict } from "../lib/board.ts";
import { boardDefError, describeBoardDef, loadBoardDef, sameBoardDef, sessionSpecFromDef, type BoardDef } from "../lib/board_def.ts";
import { bedImageSize, parseFinalizeInputs } from "../lib/calib_finalize.ts";
import { calibrationReady } from "../lib/vision.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import type { Call } from "./views/types.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

// Fallback when no board was generated in this browser: the board panel's default preset
// (medium 5×7), so an untouched Calibrate page matches an untouched board download.
const FALLBACK_BOARD: BoardDef = {
  ...PRESET_GEOMETRY.medium_5x7,
  dict: pickArucoDict(PRESET_GEOMETRY.medium_5x7.squaresX, PRESET_GEOMETRY.medium_5x7.squaresY) ?? "DICT_4X4_50",
};

const HELP_MM_PER_PX = "The size of one pixel in the corrected top-down bed image. 0.5 means each pixel covers 0.5 mm. Smaller = more detail but much bigger images (0.05 on a 200 mm bed is 4000×4000 px). Measurements are converted to mm using this value.";
const HELP_BED_EXTENT = "Which region of the bed, in mm (left, top, right, bottom), the corrected image covers — measured from the board's origin (its first inner corner). Anything outside is cropped.";
const HELP_BED_CORR = "Uses your last captured board view to link camera pixels to real bed millimetres — take that last capture with the board lying flat on the bed. The board's position becomes the bed coordinate origin.";

/** Guided intrinsics + bed-homography calibration (A6b): start a ChArUco capture session, grab
 *  a handful of board views, then finalize into a full calibration (intrinsics_rms +
 *  reprojection_error). Wired against `POST /api/vision/calibrate/session|capture|finalize`
 *  and `GET /api/vision/calibrate/session` (see backend vention_printer_interface/api/app.py).
 *
 *  Capture grabs one still from the ASSIGNED science camera in the BROWSER (by deviceId — reliable
 *  on macOS) and POSTs it to `/calibrate/capture-upload`, so the intrinsics/bed homography are fit
 *  from the SAME getUserMedia source the print-time science captures use (not a server cv2 grab,
 *  which opens the wrong camera on macOS). Feedback is per-capture (board found / corner count);
 *  there is no continuous live video feed here. */
export function CalibrationWizard({ call, printing }: { call: Call; printing: boolean }) {
  // The board generated/selected in the Calibration board panel (null if none in this browser).
  const [generated] = useState<BoardDef | null>(() => loadBoardDef(storage));
  const [board, setBoard] = useState<BoardDef>(() => generated ?? FALLBACK_BOARD);
  const setB = (patch: Partial<BoardDef>) => setBoard((b) => ({ ...b, ...patch }));
  const boardErr = boardDefError(board);
  const dictOptions = ARUCO_4X4_FAMILY.map(([name]) => name).concat(
    ARUCO_4X4_FAMILY.some(([name]) => name === board.dict) ? [] : [board.dict]);

  const [session, setSession] = useState<VisionCalibSession | null>(null);
  const [captureNote, setCaptureNote] = useState<string | null>(null);

  const [mmPerPx, setMmPerPx] = useState("0.5");
  const [bedExtent, setBedExtent] = useState("0,0,200,200");
  const [useLastAsBed, setUseLastAsBed] = useState(true);
  const [finalizeErr, setFinalizeErr] = useState<string | null>(null);
  const [result, setResult] = useState<VisionCalibFinalizeResult | null>(null);

  const startSession = () => {
    setResult(null);
    setCaptureNote(null);
    call("start calibration session", () =>
      api.visionCalibrateSessionStart(sessionSpecFromDef(board)).then(setSession));
  };

  const captureView = () => {
    call("capture calibration view", async () => {
      const blob = await captureScienceStillOnce(storage);  // browser grab: same source as prints
      const r = await api.visionCalibrateCaptureUpload(blob);
      setCaptureNote(r.captured ? `board found — ${r.corners_found ?? 0} corners (view ${r.count ?? "?"})` : (r.reason ?? "no board detected"));
      return api.visionCalibrateSessionGet().then(setSession);
    });
  };

  // Checked live (inline under each field) and again on finalize — mirrors the backend's 400s.
  const inputs = parseFinalizeInputs(mmPerPx, bedExtent);
  const finalize = () => {
    setFinalizeErr(null);
    if (!inputs.ok) { setFinalizeErr(inputs.error); return; }
    const body = { mm_per_px: inputs.mmPerPx, bed_extent_mm: inputs.extent, use_last_capture_as_bed: useLastAsBed };
    call("finalize calibration", () => api.visionCalibrateFinalize(body).then(setResult));
  };

  const ready = session !== null && calibrationReady(session);
  // Coverage gate: finalize only once the frame + tilt coverage is met (falls back to the ≥3-view
  // readiness when an older backend doesn't report coverage).
  const covEnough = session?.coverage ? session.coverage.enough : ready;

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Guided calibration: start a session against your laser-engraved ChArUco board, capture at
        least 3 views from different bed positions/tilts, then finalize.
      </div>
      {printing && <div className="lock">printing in progress — calibration is disabled until the print finishes</div>}
      <div className={generated && sameBoardDef(generated, board) ? "okline" : "warnline"}>
        Calibrating against: {describeBoardDef(board)}
        {generated && sameBoardDef(generated, board) && " (from the board you generated)"}
        {generated && !sameBoardDef(generated, board) && <>
          {" "}— edited; the board you generated is {describeBoardDef(generated)}.{" "}
          <button className="small" onClick={() => setBoard(generated)} disabled={printing}>use generated board</button>
        </>}
        {!generated && " — no generated board found in this browser; make sure these match your physical board exactly (a wrong square size silently scales every mm measurement)."}
      </div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span>squares (x × y)</span>
        <span className="row">
          <input type="number" min={2} max={40} value={board.squaresX} onChange={(e) => setB({ squaresX: Number(e.target.value) })} style={{ width: 64 }} disabled={printing} />
          {" × "}
          <input type="number" min={2} max={40} value={board.squaresY} onChange={(e) => setB({ squaresY: Number(e.target.value) })} style={{ width: 64 }} disabled={printing} />
        </span>
        <span>square / marker (mm)</span>
        <span className="row">
          <input type="number" step="0.1" value={board.squareMm} onChange={(e) => setB({ squareMm: Number(e.target.value) })} style={{ width: 64 }} disabled={printing} />
          {" / "}
          <input type="number" step="0.1" value={board.markerMm} onChange={(e) => setB({ markerMm: Number(e.target.value) })} style={{ width: 64 }} disabled={printing} />
        </span>
        <span title="The ArUco marker family printed on the board — it must match the board exactly.">ArUco dictionary</span>
        <select value={board.dict} onChange={(e) => setB({ dict: e.target.value })} disabled={printing}>
          {dictOptions.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>
      {boardErr && <div className="errline">{boardErr}</div>}
      <div className="actions tight">
        <button className="cta primary" disabled={printing || !!boardErr} onClick={startSession}>start session</button>
        <button disabled={printing || session === null} onClick={captureView}>capture view</button>
      </div>
      {session && (
        <div className="kv">
          <span>views captured</span><span>{session.n_views}</span>
          <span>ready to finalize</span><span>{covEnough ? "yes — coverage met" : "no — fill the coverage map"}</span>
        </div>
      )}
      {session?.coverage && (
        <div className="cov" style={{ marginTop: 8 }}>
          <div className="hint" style={{ marginTop: 0, textTransform: "none", letterSpacing: 0 }}>coverage — move the board across the frame AND tilt it a few ways</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 30px)", gap: 4, marginTop: 4 }}>
            {[1, 2, 3].flatMap((r) => [1, 2, 3].map((c) => {
              const filled = !session.coverage!.gaps.includes(`r${r}c${c}`);
              return <div key={`r${r}c${c}`} title={`cell r${r}c${c}`} style={{ width: 30, height: 22, borderRadius: 4, background: filled ? "var(--ok, #2e7d32)" : "var(--track, #2a2f3a)" }} />;
            }))}
          </div>
          <div className="hint" style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }}>
            {session.coverage.tilt_bins_filled}/3 tilt angles{session.coverage.gaps.includes("tilt") ? " — tilt the board more" : " ✓"} · {session.coverage.total_views} views{session.coverage.enough ? " · ✓ enough" : ""}
          </div>
        </div>
      )}
      {captureNote && <div className="hint">science camera — {captureNote}</div>}

      <div className="fields" style={{ marginTop: 16 }}>
        <span title={HELP_MM_PER_PX}>mm / px</span>
        <input type="number" step="0.01" min={0} value={mmPerPx} onChange={(e) => setMmPerPx(e.target.value)} disabled={printing} />
        <div className="field-help">{HELP_MM_PER_PX}</div>
        {!inputs.ok && inputs.field === "mmPerPx" && <div className="field-err">{inputs.error}</div>}
        <span title={HELP_BED_EXTENT}>bed extent (mm)</span>
        <input type="text" placeholder="left,top,right,bottom" value={bedExtent} onChange={(e) => setBedExtent(e.target.value)} disabled={printing} />
        <div className="field-help">{HELP_BED_EXTENT}</div>
        {!inputs.ok && inputs.field === "bedExtent" && <div className="field-err">{inputs.error}</div>}
        {inputs.ok && <div className="field-help">corrected bed image: {bedImageSize(inputs.mmPerPx, inputs.extent).join(" × ")} px</div>}
        <span title={HELP_BED_CORR}>bed correspondence</span>
        <label className="row">
          <input type="checkbox" checked={useLastAsBed} onChange={(e) => setUseLastAsBed(e.target.checked)} disabled={printing} />
          {" "}use the last captured board view as the bed reference
        </label>
        <div className="field-help">{HELP_BED_CORR}</div>
      </div>
      {finalizeErr && <div className="errline">{finalizeErr}</div>}
      <div className="actions one tight">
        <button className="cta primary" disabled={printing || !covEnough || !inputs.ok} onClick={finalize}>finalize calibration</button>
      </div>
      {result && (
        <div className="kv">
          <span>intrinsics RMS</span><span>{result.intrinsics_rms.toFixed(4)} px</span>
          <span>reprojection error</span><span>{result.reprojection_error.toFixed(4)} mm</span>
          <span>calibration version</span><span>{result.calibration_version}</span>
        </div>
      )}
    </>
  );
}
