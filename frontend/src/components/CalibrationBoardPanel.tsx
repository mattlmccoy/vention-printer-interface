import { useState } from "react";

const PRESETS = [
  { value: "small_cylinder", label: "small — fits Ø101.6 mm (4 in) cylinder top" },
  { value: "medium_5x7", label: "medium — 5×7" },
  { value: "large_6x9", label: "large — 6×9" },
] as const;
type Preset = (typeof PRESETS)[number]["value"];

/** Calibration-board download panel (A8 GET /api/vision/board, wired into the Cameras view for
 *  A7). Picks a preset + file format for the true-vector ChArUco board the operator laser-
 *  engraves onto dual-color ABS — see backend vention_printer_interface/api/app.py's
 *  vision_board. A plain download link is enough: this is a local operator app, so the browser's
 *  normal file-download handling just works; no fetch/blob plumbing needed. */
export function CalibrationBoardPanel({ base }: { base: string }) {
  const [preset, setPreset] = useState<Preset>("medium_5x7");
  const [format, setFormat] = useState<"svg" | "dxf">("svg");
  const [engraveBlack, setEngraveBlack] = useState(true);

  const href = `${base}/api/vision/board?format=${format}&preset=${encodeURIComponent(preset)}&engrave_black=${engraveBlack}`;

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Generate a true-vector ChArUco calibration board for laser engraving onto dual-color ABS.
      </div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span>preset</span>
        <select value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
          {PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <span>format</span>
        <select value={format} onChange={(e) => setFormat(e.target.value as "svg" | "dxf")}>
          <option value="svg">SVG</option>
          <option value="dxf">DXF</option>
        </select>
        <span>engrave polarity</span>
        <label className="row">
          <input type="checkbox" checked={engraveBlack} onChange={(e) => setEngraveBlack(e.target.checked)} />
          {" "}engrave black squares/markers (invert if your top ABS layer is the light color)
        </label>
      </div>
      <div className="actions one tight">
        <a className="cta primary" href={href} download>download board ({format.toUpperCase()})</a>
      </div>
    </>
  );
}
