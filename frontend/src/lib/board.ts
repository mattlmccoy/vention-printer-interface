/** ChArUco calibration-board request building for CalibrationBoardPanel (#13).
 *
 * The backend GET /api/vision/board (see api/app.py vision_board) takes EITHER a named `preset`
 * OR an explicit squares_x/squares_y/square_mm/marker_mm set — this module builds the right query
 * for each, and the same query is reused (with format=svg) to render a non-saved inline preview. */

export const BOARD_PRESETS = [
  { value: "small_cylinder", label: "small — fits Ø101.6 mm (4 in) cylinder top" },
  { value: "medium_5x7", label: "medium — 5×7" },
  { value: "large_6x9", label: "large — 6×9" },
] as const;

export type BoardPreset = (typeof BOARD_PRESETS)[number]["value"];
export type BoardFormat = "svg" | "dxf";

export interface BoardConfig {
  preset: BoardPreset | "custom";
  format: BoardFormat;
  engraveBlack: boolean;
  /** Include the red CUT-layer perimeter (laser cuts the board free). Off = pre-cut stock. */
  cutOutline: boolean;
  squaresX: number;
  squaresY: number;
  squareMm: number;
  markerMm: number;
}

export const DEFAULT_BOARD: BoardConfig = {
  preset: "medium_5x7",
  format: "svg",
  engraveBlack: true,
  cutOutline: true,
  squaresX: 5,
  squaresY: 7,
  squareMm: 12,
  markerMm: 9,
};

/** Build the query string for /api/vision/board. `formatOverride` forces a format (the preview
 *  always requests SVG, whatever the chosen download format is). Custom omits `preset` and sends
 *  the explicit geometry; a named preset sends only `preset`. */
export function boardQuery(cfg: BoardConfig, formatOverride?: BoardFormat): string {
  const p = new URLSearchParams();
  p.set("format", formatOverride ?? cfg.format);
  if (cfg.preset === "custom") {
    p.set("squares_x", String(cfg.squaresX));
    p.set("squares_y", String(cfg.squaresY));
    p.set("square_mm", String(cfg.squareMm));
    p.set("marker_mm", String(cfg.markerMm));
  } else {
    p.set("preset", cfg.preset);
  }
  p.set("engrave_black", String(cfg.engraveBlack));
  p.set("cut_outline", String(cfg.cutOutline));
  return p.toString();
}

/** Custom geometry is only valid when the marker fits inside the square and the grid is sane —
 *  mirrors the backend's range checks so the UI can flag it before the request 400s. */
export function boardConfigError(cfg: BoardConfig): string | null {
  if (cfg.preset !== "custom") return null;
  if (!(cfg.squaresX >= 1 && cfg.squaresX <= 40)) return "squares X must be 1–40";
  if (!(cfg.squaresY >= 1 && cfg.squaresY <= 40)) return "squares Y must be 1–40";
  if (!(cfg.squareMm > 0)) return "square size must be > 0 mm";
  if (!(cfg.markerMm > 0 && cfg.markerMm < cfg.squareMm)) return "marker must be > 0 and smaller than the square";
  return null;
}
