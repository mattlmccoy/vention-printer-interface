/** The board an automatic calibration runs on: one of the ChArUco boards, or the certified plate
 *  (2026-10-27: DEvision Q18-100-4.5, a flat manufactured chessboard; the engraved ChArUco is about
 *  0.2 % small). The plate has no markers, so the operator numbers its corners across the sweep
 *  (vision/plate_labels.py) and keeps the plate's own millimetres. */

import type { VisionBoardSpecBody } from "./api.ts";
import { sessionSpecFromDef, type BoardDef } from "./board_def.ts";

export const CERTIFIED_PLATE = {
  key: "certified_plate",
  label: "Certified chessboard — DEvision Q18-100-4.5: 17×17 corners, 4.5 mm squares (the plate is the ruler)",
  spec: { kind: "checkerboard", cols: 17, rows: 17, square_size_mm: 4.5 } as VisionBoardSpecBody,
};

/** The session spec for the chosen board, or null when no board is picked. */
export function autocalSpec(key: string, board: BoardDef | null): VisionBoardSpecBody | null {
  if (key === CERTIFIED_PLATE.key) return { ...CERTIFIED_PLATE.spec };
  return board ? sessionSpecFromDef(board) : null;
}

/** Which ruler the calibration's millimetres come from, and how far the other one disagreed. */
export function lengthReferenceText(r: { scale_reference?: "board" | "encoder"; scale_ratio: number }): string {
  const pct = `${(Math.abs(r.scale_ratio - 1) * 100).toFixed(2)} %`;
  return r.scale_reference === "board"
    ? `the certified plate; the recoater encoder disagrees by ${pct}`
    : `the recoater encoder (the board measured ${pct} off and was rescaled)`;
}
