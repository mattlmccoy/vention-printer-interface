/** The calibration-board DEFINITION handed from the board panel to the Calibrate page.
 *
 * The Calibrate session builds the same cv2 CharucoBoard for detection, so it needs the exact
 * grid, square/marker sizes and ArUco dictionary of the board that was engraved. A wrong square
 * size still detects but silently scales every mm measurement wrongly, so the board panel saves
 * whatever the operator last selected/generated here and the Calibrate page defaults to it.
 * Persisted in localStorage (storage injected; every access guarded). */

import { ARUCO_4X4_FAMILY, boardConfigError, boardGeometry, geometryError, markersNeeded, pickArucoDict, type BoardConfig } from "./board.ts";
import type { VisionBoardSpecBody } from "./api.ts";

export interface BoardDef {
  dict: string;
  squaresX: number;
  squaresY: number;
  squareMm: number;
  markerMm: number;
}

const KEY = "vpi.calibBoard.v1";

/** The board a panel config generates, or null when the config is invalid. `serverDict` (the
 *  backend's X-Board-Dict header) wins over the local auto-pick when it is known. */
export function boardDefFromConfig(cfg: BoardConfig, serverDict?: string | null): BoardDef | null {
  if (boardConfigError(cfg)) return null;
  const g = boardGeometry(cfg);
  const dict = serverDict || pickArucoDict(g.squaresX, g.squaresY);
  return dict ? { dict, ...g } : null;
}

/** Same rules as the backend session validation (board_gen.validate_charuco_spec). Only 4x4
 *  dictionaries are capacity-checked here; any other name is left to the backend. */
export function boardDefError(d: BoardDef): string | null {
  const g = geometryError(d);
  if (g) return g;
  const known = ARUCO_4X4_FAMILY.find(([name]) => name === d.dict);
  const need = markersNeeded(d.squaresX, d.squaresY);
  if (known && known[1] < need) {
    const fit = pickArucoDict(d.squaresX, d.squaresY);
    return `a ${d.squaresX}×${d.squaresY} board needs ${need} markers but ${d.dict} has only ${known[1]}${fit ? ` — use ${fit}` : ""}`;
  }
  return null;
}

export function describeBoardDef(d: BoardDef): string {
  return `${d.squaresX}×${d.squaresY} squares, ${d.squareMm} mm squares / ${d.markerMm} mm markers, ${d.dict}`;
}

export function sessionSpecFromDef(d: BoardDef): VisionBoardSpecBody {
  return {
    kind: "charuco",
    squares_x: d.squaresX,
    squares_y: d.squaresY,
    square_length_mm: d.squareMm,
    marker_length_mm: d.markerMm,
    aruco_dict: d.dict,
  };
}

export function sameBoardDef(a: BoardDef | null, b: BoardDef | null): boolean {
  if (!a || !b) return a === b;
  return a.dict === b.dict && a.squaresX === b.squaresX && a.squaresY === b.squaresY
    && a.squareMm === b.squareMm && a.markerMm === b.markerMm;
}

export function loadBoardDef(storage: Storage | null): BoardDef | null {
  try {
    const raw = storage?.getItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<BoardDef>;
    const nums = [p.squaresX, p.squaresY, p.squareMm, p.markerMm];
    if (typeof p.dict !== "string" || !nums.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
    const d: BoardDef = { dict: p.dict, squaresX: p.squaresX!, squaresY: p.squaresY!, squareMm: p.squareMm!, markerMm: p.markerMm! };
    return boardDefError(d) ? null : d;
  } catch {
    return null;
  }
}

export function saveBoardDef(storage: Storage | null, d: BoardDef): void {
  try { storage?.setItem(KEY, JSON.stringify(d)); } catch { /* storage disabled */ }
}
