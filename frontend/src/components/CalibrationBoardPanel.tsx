import { useEffect, useState } from "react";
import {
  BOARD_PRESETS, DEFAULT_BOARD, boardConfigError, boardGeometry, boardQuery, fetchBoardPreview, markersNeeded, pickArucoDict,
  type BoardConfig,
} from "../lib/board.ts";
import { boardDefFromConfig, saveBoardDef } from "../lib/board_def.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;
/** Wait this long after the last edit before fetching a preview: typing "12" must not fire a
 *  board generation for "1" (a 1-wide board can crash cv2) and one per keystroke. */
const PREVIEW_DEBOUNCE_MS = 400;

type PreviewState =
  | { status: "idle" }
  | { status: "loading"; url: string }
  | { status: "ok"; url: string; src: string; dict: string | null }
  | { status: "error"; url: string; error: string };

/** `value`, but only after it has stopped changing for `ms`. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** Calibration-board download panel (A8 GET /api/vision/board, wired into the Cameras view for
 *  A7). Picks a preset (or CUSTOM geometry) + file format for the true-vector ChArUco board the
 *  operator laser-engraves onto dual-color ABS — see backend api/app.py's vision_board. A plain
 *  download link handles the file; a debounced inline SVG preview (fetched, never saved) lets the
 *  operator confirm the board before committing it to the laser, and shows the backend's error
 *  text when the board is invalid. The selected board is saved for the Calibrate page
 *  (lib/board_def.ts) so calibration uses the same geometry + ArUco dictionary. */
export function CalibrationBoardPanel({ base }: { base: string }) {
  const [cfg, setCfg] = useState<BoardConfig>(DEFAULT_BOARD);
  const [showPreview, setShowPreview] = useState(false);
  const [preview, setPreview] = useState<PreviewState>({ status: "idle" });
  const set = (patch: Partial<BoardConfig>) => setCfg((c) => ({ ...c, ...patch }));

  const err = boardConfigError(cfg);
  const downloadHref = `${base}/api/vision/board?${boardQuery(cfg)}`;
  const previewHref = `${base}/api/vision/board?${boardQuery(cfg, "svg")}`; // always SVG for the render
  const settledPreviewHref = useDebounced(previewHref, PREVIEW_DEBOUNCE_MS);

  const geom = boardGeometry(cfg);
  const serverDict = preview.status === "ok" && preview.url === previewHref ? preview.dict : null;
  const dict = serverDict ?? (err ? null : pickArucoDict(geom.squaresX, geom.squaresY));

  // Hand the selected board to the Calibrate page whenever it changes (valid boards only).
  useEffect(() => {
    const def = boardDefFromConfig(cfg, serverDict);
    if (def) saveBoardDef(storage, def);
  }, [cfg, serverDict]);

  // Fetch the preview only once edits settle; abort a stale in-flight one.
  useEffect(() => {
    if (!showPreview || err) return;
    const ctrl = new AbortController();
    let objectUrl: string | null = null;
    setPreview({ status: "loading", url: settledPreviewHref });
    fetchBoardPreview(settledPreviewHref, ctrl.signal).then((r) => {
      if (ctrl.signal.aborted) return;
      if (!r.ok) { setPreview({ status: "error", url: settledPreviewHref, error: r.error }); return; }
      objectUrl = URL.createObjectURL(new Blob([r.svg], { type: "image/svg+xml" }));
      setPreview({ status: "ok", url: settledPreviewHref, src: objectUrl, dict: r.dict });
    }).catch(() => { /* aborted: a newer preview replaced this one */ });
    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // Keyed on the SETTLED url only: while the operator is still typing, the last good preview
    // stays up (marked "updating") instead of being torn down per keystroke.
  }, [showPreview, settledPreviewHref, err]);

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
            <input type="number" min={2} max={40} value={cfg.squaresX} onChange={(e) => set({ squaresX: Number(e.target.value) })} style={{ width: 60 }} /> ×
            <input type="number" min={2} max={40} value={cfg.squaresY} onChange={(e) => set({ squaresY: Number(e.target.value) })} style={{ width: 60 }} />
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
      {!err && dict && (
        <div className="hint" style={{ marginTop: 10 }}>
          ArUco dictionary: <b>{dict}</b> ({markersNeeded(geom.squaresX, geom.squaresY)} markers on a {geom.squaresX}×{geom.squaresY} board)
          {" "}— the Calibrate page uses this same board.
        </div>
      )}
      <div className="actions one tight" style={{ gap: 8 }}>
        <button className="cta" disabled={!!err} onClick={() => setShowPreview((s) => !s)}>{showPreview ? "hide preview" : "preview board"}</button>
        <a className={`cta primary${err ? " disabled" : ""}`} href={err ? undefined : downloadHref} download aria-disabled={!!err}>download board ({cfg.format.toUpperCase()})</a>
      </div>
      {showPreview && !err && (
        <div className="board-preview" style={{ marginTop: 12, padding: 12, background: "#fff", borderRadius: 8, textAlign: "center" }}>
          {/* Rendered, never saved — a live SVG render of the exact board the download produces. */}
          {preview.status === "ok" && <img src={preview.src} alt="ChArUco board preview" style={{ maxWidth: "100%", height: "auto" }} />}
          {(preview.status === "loading" || preview.status === "idle" || (preview.status === "ok" && preview.url !== previewHref)) && (
            <div className="hint" style={{ color: "#555" }}>updating preview…</div>
          )}
        </div>
      )}
      {showPreview && !err && preview.status === "error" && <div className="errline">preview failed: {preview.error}</div>}
    </>
  );
}
