import { useState } from "react";
import { api, type VisionValidateScaleResult } from "../lib/api.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import { ToleranceBand } from "./ToleranceBand.tsx";
import { PlotExportButtons } from "./PlotExportButtons.tsx";
import type { Call } from "./views/types.ts";

// The bought board's nominal geometry (17x17 INNER corners, 4.5mm nominal pitch). The nominal pitch
// drives detection; the operator's caliper-measured TRUE pitch is entered below and used to score.
const NOMINAL_COLS = 17;
const NOMINAL_ROWS = 17;
const NOMINAL_SQUARE_MM = 4.5;
const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Independent scale validation: capture the certified chessboard through the SCIENCE camera (same
 *  browser getUserMedia source as the prints + calibration), map corners to world-mm through the
 *  current calibration, and score the worst corner-spacing error against a tolerance band. */
export function ValidationPanel({ call, printing }: { call: Call; printing: boolean }) {
  const [knownPitchMm, setKnownPitchMm] = useState(String(NOMINAL_SQUARE_MM));
  const [targetMm, setTargetMm] = useState("0.05");
  const [result, setResult] = useState<VisionValidateScaleResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const validate = () => {
    setErr(null);
    const pitch = Number(knownPitchMm);
    const target = Number(targetMm);
    if (!Number.isFinite(pitch) || pitch <= 0) { setErr("known pitch must be a positive number"); return; }
    if (!Number.isFinite(target) || target <= 0) { setErr("target must be a positive number"); return; }
    call("scale validate", async () => {
      const blob = await captureScienceStillOnce(storage);  // same camera as prints + calibration
      const r = await api.visionValidateScaleUpload(blob, {
        cols: NOMINAL_COLS, rows: NOMINAL_ROWS, squareSizeMm: NOMINAL_SQUARE_MM,
        certifiedMm: pitch, targetMm: target,
      });
      setResult(r);
    });
  };

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Certified checkerboard: {NOMINAL_COLS}×{NOMINAL_ROWS} inner corners, {NOMINAL_SQUARE_MM} mm
        nominal pitch. Caliper-qualify the board's true pitch and enter it below, then capture it with
        the science camera (same source as your prints) to measure real world-mm accuracy.
      </div>
      {printing && <div className="lock">printing in progress — validation is disabled until the print finishes</div>}
      <div className="fields" style={{ marginTop: 16 }}>
        <span>known pitch (mm, caliper-measured)</span>
        <input type="number" step="0.001" value={knownPitchMm} onChange={(e) => setKnownPitchMm(e.target.value)} disabled={printing} />
        <span>target (± mm)</span>
        <input type="number" step="0.01" value={targetMm} onChange={(e) => setTargetMm(e.target.value)} disabled={printing} />
      </div>
      {err && <div className="errline">{err}</div>}
      <div className="actions one tight">
        <button className="cta primary" disabled={printing} onClick={validate}>capture chessboard &amp; validate</button>
      </div>
      {result && (
        <div style={{ marginTop: 12 }}>
          <ToleranceBand
            label="worst corner-spacing error"
            value={result.max_mm}
            limit={result.target_mm}
            unit="mm"
            mode="max"
            hint={`rms ${result.rms_mm.toFixed(3)} mm · scale bias ${result.scale_bias.toFixed(4)} · ${result.n_points} corners`}
          />
          {result.per_point && result.per_point.length > 0 && (
            <PlotExportButtons
              fetchBlob={(fmt) => api.plotValidation(
                result.per_point!.map((p) => p.error_mm), result.target_mm, fmt)}
              filename="scale_validation"
              label="Seaborn plot"
            />
          )}
        </div>
      )}
    </>
  );
}
