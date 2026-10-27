import { useState } from "react";
import { api, operatorBase, type VisionValidateScaleResult } from "../lib/api.ts";
import { captureScienceStillOnce } from "../lib/science_still.ts";
import { validationCoverageText, validationScaleText } from "../lib/validation_text.ts";
import { ToleranceBand } from "./ToleranceBand.tsx";
import { PlotExportButtons } from "./PlotExportButtons.tsx";
import { CalibrationSizeNote } from "./CalibrationSizeNote.tsx";
import type { Call } from "./views/types.ts";

// The bought board's nominal pitch (4.5 mm; 17x17 inner corners, 81 mm — larger than the science
// camera's ~74 mm view). Detection finds the VISIBLE part, so no corner count is needed; the
// operator's caliper-measured TRUE pitch is entered below and used to score.
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
      const r = await api.visionValidateScaleUpload(blob, { certifiedMm: pitch, targetMm: target });
      setResult(r);
    });
  };

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Certified chessboard ({NOMINAL_SQUARE_MM} mm nominal pitch). Caliper-measure the true square pitch and enter it
        below, then place the chessboard where the calibration board was and capture it with the science camera (same
        source as your prints). It may run off the edges of the photo: the visible part is used, and only corners inside the
        calibrated area are scored.
      </div>
      {printing && <div className="lock">printing in progress — validation is disabled until the print finishes</div>}
      <CalibrationSizeNote />
      <div className="fields" style={{ marginTop: 16 }}>
        <span title="The certified board's true square size, measured with calipers (e.g. 10 squares ÷ 10).">square pitch (mm, caliper-measured)</span>
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
            hint={`rms ${result.rms_mm.toFixed(3)} mm · scale bias ${result.scale_bias.toFixed(4)}${result.image_size ? ` · ${result.image_size[0]}×${result.image_size[1]} photo` : ""}`}
          />
          <div className={result.area_known === true ? "hint" : "warnline"} style={{ marginTop: 4 }}>{validationCoverageText(result)}</div>
          {validationScaleText(result) && <div className="hint" style={{ marginTop: 4 }}>{validationScaleText(result)}</div>}
          {result.annotated_url && (
            <figure style={{ margin: "10px 0 0" }}>
              <img src={`${operatorBase()}${result.annotated_url}`} alt="validation photo with every corner's error" style={{ width: "100%", display: "block", border: "1px solid var(--line)" }} />
              {result.raw_url && <a className="hint" href={`${operatorBase()}${result.raw_url}`} target="_blank" rel="noreferrer">Open the photo as taken (unmarked, full size) — kept under Settings → Calibrations.</a>}
              <figcaption className="hint" style={{ margin: "4px 0 0" }}>Each chessboard corner on the actual photo: green within the target, amber within 2×, red beyond; the arrow points to where the calibration says that corner should be (enlarged). Grey = outside the calibrated area (green outline), not scored. Arrows all pointing outward or inward from the centre mean a scale error; a pattern only at the edges means the lens fit.</figcaption>
            </figure>
          )}
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
