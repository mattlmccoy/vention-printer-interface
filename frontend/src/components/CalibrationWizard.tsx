import { useState } from "react";
import { api, type VisionCalibFinalizeResult, type VisionCalibSession } from "../lib/api.ts";
import { calibrationReady } from "../lib/vision.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import type { Call } from "./views/types.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

const DEFAULT_SPEC = { squares_x: 7, squares_y: 5, square_length_mm: 20, marker_length_mm: 15, aruco_dict: "DICT_4X4_50" };

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
  const [squaresX, setSquaresX] = useState(DEFAULT_SPEC.squares_x);
  const [squaresY, setSquaresY] = useState(DEFAULT_SPEC.squares_y);
  const [squareMm, setSquareMm] = useState(DEFAULT_SPEC.square_length_mm);
  const [markerMm, setMarkerMm] = useState(DEFAULT_SPEC.marker_length_mm);

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
      api.visionCalibrateSessionStart({
        kind: "charuco",
        squares_x: squaresX,
        squares_y: squaresY,
        square_length_mm: squareMm,
        marker_length_mm: markerMm,
      }).then(setSession));
  };

  const captureView = () => {
    call("capture calibration view", async () => {
      const blob = await captureScienceStillOnce(storage);  // browser grab: same source as prints
      const r = await api.visionCalibrateCaptureUpload(blob);
      setCaptureNote(r.captured ? `board found — ${r.corners_found ?? 0} corners (view ${r.count ?? "?"})` : (r.reason ?? "no board detected"));
      return api.visionCalibrateSessionGet().then(setSession);
    });
  };

  const finalize = () => {
    setFinalizeErr(null);
    let body: Parameters<typeof api.visionCalibrateFinalize>[0];
    try {
      const mm = Number(mmPerPx);
      if (!Number.isFinite(mm) || mm <= 0) throw new Error("mm/px must be a positive number");
      const extent = bedExtent.split(",").map(Number);
      if (extent.length !== 4 || extent.some((v) => !Number.isFinite(v))) throw new Error("bed extent needs 4 numbers: x0,y0,x1,y1");
      body = { mm_per_px: mm, bed_extent_mm: extent as [number, number, number, number], use_last_capture_as_bed: useLastAsBed };
    } catch (e) {
      setFinalizeErr(e instanceof Error ? e.message : String(e));
      return;
    }
    call("finalize calibration", () => api.visionCalibrateFinalize(body).then(setResult));
  };

  const ready = session !== null && calibrationReady(session);

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Guided calibration: start a session against your laser-engraved ChArUco board, capture at
        least 3 views from different bed positions/tilts, then finalize.
      </div>
      {printing && <div className="lock">printing in progress — calibration is disabled until the print finishes</div>}
      <div className="fields" style={{ marginTop: 16 }}>
        <span>squares (x × y)</span>
        <span className="row">
          <input type="number" min={1} value={squaresX} onChange={(e) => setSquaresX(Number(e.target.value))} style={{ width: 64 }} disabled={printing} />
          {" × "}
          <input type="number" min={1} value={squaresY} onChange={(e) => setSquaresY(Number(e.target.value))} style={{ width: 64 }} disabled={printing} />
        </span>
        <span>square / marker (mm)</span>
        <span className="row">
          <input type="number" step="0.1" value={squareMm} onChange={(e) => setSquareMm(Number(e.target.value))} style={{ width: 64 }} disabled={printing} />
          {" / "}
          <input type="number" step="0.1" value={markerMm} onChange={(e) => setMarkerMm(Number(e.target.value))} style={{ width: 64 }} disabled={printing} />
        </span>
      </div>
      <div className="actions tight">
        <button className="cta primary" disabled={printing} onClick={startSession}>start session</button>
        <button disabled={printing || session === null} onClick={captureView}>capture view</button>
      </div>
      {session && (
        <div className="kv">
          <span>views captured</span><span>{session.n_views}</span>
          <span>ready to finalize</span><span>{ready ? "yes (≥ 3 views)" : "no — capture more views"}</span>
        </div>
      )}
      {captureNote && <div className="hint">science camera — {captureNote}</div>}

      <div className="fields" style={{ marginTop: 16 }}>
        <span>mm / px</span>
        <input type="number" step="0.01" value={mmPerPx} onChange={(e) => setMmPerPx(e.target.value)} disabled={printing} />
        <span>bed extent (mm)</span>
        <input type="text" placeholder="x0,y0,x1,y1" value={bedExtent} onChange={(e) => setBedExtent(e.target.value)} disabled={printing} />
        <span>bed correspondence</span>
        <label className="row">
          <input type="checkbox" checked={useLastAsBed} onChange={(e) => setUseLastAsBed(e.target.checked)} disabled={printing} />
          {" "}use the last captured board view as the bed reference
        </label>
      </div>
      {finalizeErr && <div className="errline">{finalizeErr}</div>}
      <div className="actions one tight">
        <button className="cta primary" disabled={printing || !ready} onClick={finalize}>finalize calibration</button>
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
