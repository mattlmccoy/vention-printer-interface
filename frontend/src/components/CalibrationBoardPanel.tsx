import { useState } from "react";
import { BOARD_PRESETS, DEFAULT_BOARD, boardConfigError, boardQuery, type BoardConfig } from "../lib/board.ts";

/** Calibration-board download panel (A8 GET /api/vision/board, wired into the Cameras view for
 *  A7). Picks a preset (or CUSTOM geometry) + file format for the true-vector ChArUco board the
 *  operator laser-engraves onto dual-color ABS — see backend api/app.py's vision_board. A plain
 *  download link handles the file; a live inline SVG preview (rendered, never saved) lets the
 *  operator confirm the board before committing it to the laser. */
export function CalibrationBoardPanel({ base }: { base: string }) {
  const [cfg, setCfg] = useState<BoardConfig>(DEFAULT_BOARD);
  const [showPreview, setShowPreview] = useState(false);
  const set = (patch: Partial<BoardConfig>) => setCfg((c) => ({ ...c, ...patch }));

  const err = boardConfigError(cfg);
  const downloadHref = `${base}/api/vision/board?${boardQuery(cfg)}`;
  const previewHref = `${base}/api/vision/board?${boardQuery(cfg, "svg")}`; // always SVG for the render

  return (
    <>
      <div className="hint" style={{ marginTop: 0 }}>
        Generate a true-vector ChArUco calibration board for laser engraving onto dual-color ABS.
      </div>
      <div className="fields" style={{ marginTop: 16 }}>
        <span title="A stock size, or Custom to enter your own grid + square/marker dimensions.">preset</span>
        <select value={cfg.preset} onChange={(e) => set({ preset: e.target.value as BoardConfig["preset"] })}>
          {BOARD_PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          <option value="custom">custom — enter your own size</option>
        </select>
        {cfg.preset === "custom" && <>
          <span title="Number of chessboard SQUARES across (X) and down (Y).">grid (squares)</span>
          <span className="row" style={{ gap: 6 }}>
            <input type="number" min={1} max={40} value={cfg.squaresX} onChange={(e) => set({ squaresX: Number(e.target.value) })} style={{ width: 60 }} /> ×
            <input type="number" min={1} max={40} value={cfg.squaresY} onChange={(e) => set({ squaresY: Number(e.target.value) })} style={{ width: 60 }} />
          </span>
          <span title="Side length of each chessboard square (mm).">square (mm)</span>
          <input type="number" min={0} step={0.5} value={cfg.squareMm} onChange={(e) => set({ squareMm: Number(e.target.value) })} style={{ width: 80 }} />
          <span title="Side length of each ArUco marker (mm) — must be smaller than the square.">marker (mm)</span>
          <input type="number" min={0} step={0.5} value={cfg.markerMm} onChange={(e) => set({ markerMm: Number(e.target.value) })} style={{ width: 80 }} />
        </>}
        <span title="SVG for laser cutters that take vector art; DXF for CAD/CAM.">format</span>
        <select value={cfg.format} onChange={(e) => set({ format: e.target.value as BoardConfig["format"] })}>
          <option value="svg">SVG</option>
          <option value="dxf">DXF</option>
        </select>
        <span title="Engrave the dark elements; invert if your top ABS layer is the light color.">engrave polarity</span>
        <label className="row">
          <input type="checkbox" checked={cfg.engraveBlack} onChange={(e) => set({ engraveBlack: e.target.checked })} />
          {" "}engrave black squares/markers (invert if your top ABS layer is the light color)
        </label>
        <span data-tip="Adds a red CUT-layer rectangle around the board so the laser cuts it free from the stock. Turn off if you're engraving onto pre-cut pieces.">cut outline</span>
        <label className="row">
          <input type="checkbox" checked={cfg.cutOutline} onChange={(e) => set({ cutOutline: e.target.checked })} />
          {" "}cut the board out (red CUT layer at the perimeter)
        </label>
      </div>
      {err && <div className="errline">{err}</div>}
      <div className="actions one tight" style={{ gap: 8 }}>
        <button className="cta" disabled={!!err} onClick={() => setShowPreview((s) => !s)}>{showPreview ? "hide preview" : "preview board"}</button>
        <a className={`cta primary${err ? " disabled" : ""}`} href={err ? undefined : downloadHref} download aria-disabled={!!err}>download board ({cfg.format.toUpperCase()})</a>
      </div>
      {showPreview && !err && (
        <div className="board-preview" style={{ marginTop: 12, padding: 12, background: "#fff", borderRadius: 8, textAlign: "center" }}>
          {/* Rendered, never saved — a live SVG render of the exact board the download produces. */}
          <img src={previewHref} alt="ChArUco board preview" style={{ maxWidth: "100%", height: "auto" }} onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
        </div>
      )}
    </>
  );
}
