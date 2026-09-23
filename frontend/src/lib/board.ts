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

/** Grid bounds — mirror backend board_gen.MIN_SQUARES / MAX_SQUARES. A board 1 square wide makes
 *  cv2 raise SystemError and can crash the operator process, so it is rejected up front. */
export const MIN_SQUARES = 2;
export const MAX_SQUARES = 40;

/** Custom geometry is only valid when the marker fits inside the square and the grid is sane —
 *  mirrors the backend's range checks so the UI can flag it before the request 400s. */
export function boardConfigError(cfg: BoardConfig): string | null {
  if (cfg.preset !== "custom") return null;
  return geometryError(cfg);
}

/** Shared grid/size checks for a board geometry (board panel + calibrate wizard). */
export function geometryError(g: BoardGeometry): string | null {
  const inRange = (n: number) => Number.isInteger(n) && n >= MIN_SQUARES && n <= MAX_SQUARES;
  if (!inRange(g.squaresX)) return `squares X must be ${MIN_SQUARES}–${MAX_SQUARES}`;
  if (!inRange(g.squaresY)) return `squares Y must be ${MIN_SQUARES}–${MAX_SQUARES}`;
  if (!(g.squareMm > 0)) return "square size must be > 0 mm";
  if (!(g.markerMm > 0 && g.markerMm < g.squareMm)) return "marker must be > 0 and smaller than the square";
  return null;
}

export interface BoardGeometry { squaresX: number; squaresY: number; squareMm: number; markerMm: number }

/** Geometry of the shipped presets — mirrors backend vision/board_gen.py BOARD_PRESETS. */
export const PRESET_GEOMETRY: Record<BoardPreset, BoardGeometry> = {
  small_cylinder: { squaresX: 4, squaresY: 4, squareMm: 16, markerMm: 12 },
  medium_5x7: { squaresX: 5, squaresY: 7, squareMm: 25, markerMm: 18 },
  large_6x9: { squaresX: 6, squaresY: 9, squareMm: 30, markerMm: 22 },
};

/** The geometry a config actually generates: the preset's, or the custom fields. */
export function boardGeometry(cfg: BoardConfig): BoardGeometry {
  if (cfg.preset !== "custom") return { ...PRESET_GEOMETRY[cfg.preset] };
  return { squaresX: cfg.squaresX, squaresY: cfg.squaresY, squareMm: cfg.squareMm, markerMm: cfg.markerMm };
}

/** 4x4 ArUco dictionaries in auto-pick order with their marker counts (real cv2 sizes, see
 *  backend board_gen.ARUCO_4X4_FAMILY / dict_capacity). */
export const ARUCO_4X4_FAMILY: ReadonlyArray<readonly [string, number]> = [
  ["DICT_4X4_50", 50], ["DICT_4X4_100", 100], ["DICT_4X4_250", 250], ["DICT_4X4_1000", 1000],
];

/** Markers a ChArUco board uses: one per white square, floor(sx*sy/2) (cv2's own count). */
export function markersNeeded(squaresX: number, squaresY: number): number {
  return Math.floor((squaresX * squaresY) / 2);
}

/** Smallest 4x4 dictionary that holds the board's markers — the backend's auto-pick rule. */
export function pickArucoDict(squaresX: number, squaresY: number): string | null {
  const need = markersNeeded(squaresX, squaresY);
  const hit = ARUCO_4X4_FAMILY.find(([, cap]) => cap >= need);
  return hit ? hit[0] : null;
}

export type BoardPreviewResult = { ok: true; svg: string; dict: string | null } | { ok: false; error: string };
type FetchLike = (url: string, init?: { signal?: AbortSignal }) => Promise<Response>;

/** Fetch the SVG preview so an error can be SHOWN (an <img> hides it) and the dictionary the
 *  backend used (X-Board-Dict header) can be read. Never throws except on abort. */
export async function fetchBoardPreview(url: string, signal?: AbortSignal, fetchImpl: FetchLike = fetch): Promise<BoardPreviewResult> {
  let res: Response;
  try {
    res = await fetchImpl(url, { signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    return { ok: false, error: `could not reach the operator: ${e instanceof Error ? e.message : String(e)}` };
  }
  const text = await res.text();
  if (res.ok) return { ok: true, svg: text, dict: res.headers.get("X-Board-Dict") };
  try {
    const j = JSON.parse(text) as unknown;
    if (j && typeof j === "object" && "detail" in j) return { ok: false, error: String((j as { detail: unknown }).detail) };
  } catch { /* not JSON — fall through */ }
  return { ok: false, error: `${res.status} ${text || res.statusText}` };
}
