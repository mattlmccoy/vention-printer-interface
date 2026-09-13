import { useState } from "react";
import { api } from "../lib/api.ts";
import { formatValidation, type FormattedValidation } from "../lib/vision.ts";
import type { Call } from "./views/types.ts";

// The bought board's nominal geometry (17x17 INNER corners, 4.5mm nominal pitch) — see the
// vision-followups spec's "Cameras (finalized 2026-09-13)" section. The nominal pitch drives
// detection (cv2.findChessboardCorners expects roughly-square-shaped cells); the operator's
// caliper-measured TRUE pitch is entered separately below and used to score accuracy.
const NOMINAL_COLS = 17;
const NOMINAL_ROWS = 17;
const NOMINAL_SQUARE_MM = 4.5;

/** Dimensional-accuracy validation against a certified checkerboard (protocol §5): detect the
 *  board, map corners to bed mm via the current calibration, and score against a +/-0.1mm
 *  target. Wired against `POST /api/vision/validate` (see backend
 *  vention_printer_interface/api/app.py's vision_validate). */
export function ValidationPanel({ call, printing }: { call: Call; printing: boolean }) {
  const [knownPitchMm, setKnownPitchMm] = useState(String(NOMINAL_SQUARE_MM));
  const [result, setResult] = useState<FormattedValidation | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const validate = () => {
    setErr(null);
    const pitch = Number(knownPitchMm);
    if (!Number.isFinite(pitch) || pitch <= 0) {
      setErr("known pitch must be a positive number");
      return;
    }
    call("validate", () =>
      api.visionValidate(
        { kind: "checkerboard", cols: NOMINAL_COLS, rows: NOMINAL_ROWS, square_size_mm: NOMINAL_SQUARE_MM },
        pitch,
      ).then((r) => setResult(formatValidation(r))));
  };

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Certified checkerboard: {NOMINAL_COLS}×{NOMINAL_ROWS} inner corners, {NOMINAL_SQUARE_MM} mm
        nominal pitch. Caliper-qualify the board's true pitch and enter it below — a bought board
        is not accuracy-certified out of the box.
      </div>
      {printing && <div className="lock">printing in progress — validation is disabled until the print finishes</div>}
      <div className="fields" style={{ marginTop: 16 }}>
        <span>known pitch (mm, caliper-measured)</span>
        <input type="number" step="0.001" value={knownPitchMm} onChange={(e) => setKnownPitchMm(e.target.value)} disabled={printing} />
      </div>
      {err && <div className="errline">{err}</div>}
      <div className="actions one tight">
        <button className="cta primary" disabled={printing} onClick={validate}>validate</button>
      </div>
      {result && (
        <div className="kv">
          <span>rms</span><span>{result.rmsMm.toFixed(4)} mm</span>
          <span>max</span><span>{result.maxMm.toFixed(4)} mm</span>
          <span>scale bias</span><span>{result.scaleBias.toFixed(4)}</span>
          <span>result</span><span className={result.pass ? "good" : "bad"}>{result.pass ? "PASS" : "FAIL"} (±0.1 mm target)</span>
        </div>
      )}
    </>
  );
}
