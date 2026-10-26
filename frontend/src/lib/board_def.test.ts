import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_BOARD } from "./board.ts";
import {
  boardDefError, boardDefFromConfig, calibBoardChoices, defaultBoardChoice, describeBoardDef, loadBoardDef, saveBoardDef, sessionSpecFromDef, type BoardDef,
} from "./board_def.ts";

class Mem implements Storage {
  m = new Map<string, string>();
  get length() { return this.m.size; }
  clear() { this.m.clear(); }
  getItem(k: string) { return this.m.get(k) ?? null; }
  key(i: number) { return [...this.m.keys()][i] ?? null; }
  removeItem(k: string) { this.m.delete(k); }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

const CUSTOM: BoardDef = { dict: "DICT_4X4_100", squaresX: 9, squaresY: 12, squareMm: 8, markerMm: 5 };

test("boardDefFromConfig resolves a preset to its geometry + auto-picked dictionary", () => {
  assert.deepEqual(boardDefFromConfig({ ...DEFAULT_BOARD, preset: "medium_5x7" }),
    { dict: "DICT_4X4_50", squaresX: 5, squaresY: 7, squareMm: 25, markerMm: 18 });
});

test("boardDefFromConfig resolves a custom board and prefers the server-reported dictionary", () => {
  const cfg = { ...DEFAULT_BOARD, preset: "custom" as const, squaresX: 9, squaresY: 12, squareMm: 8, markerMm: 5 };
  assert.deepEqual(boardDefFromConfig(cfg), CUSTOM);
  assert.equal(boardDefFromConfig(cfg, "DICT_4X4_250")?.dict, "DICT_4X4_250");
});

test("boardDefFromConfig returns null for an invalid custom board (nothing to hand off)", () => {
  assert.equal(boardDefFromConfig({ ...DEFAULT_BOARD, preset: "custom", squaresX: 1 }), null);
});

test("save/load round-trips the board definition", () => {
  const s = new Mem();
  assert.equal(loadBoardDef(s), null);
  saveBoardDef(s, CUSTOM);
  assert.deepEqual(loadBoardDef(s), CUSTOM);
});

test("loadBoardDef ignores malformed or invalid stored data", () => {
  const s = new Mem();
  s.setItem("vpi.calibBoard.v1", "not json");
  assert.equal(loadBoardDef(s), null);
  s.setItem("vpi.calibBoard.v1", JSON.stringify({ ...CUSTOM, squaresX: "9" }));
  assert.equal(loadBoardDef(s), null);
  s.setItem("vpi.calibBoard.v1", JSON.stringify({ ...CUSTOM, squaresX: 1 }));
  assert.equal(loadBoardDef(s), null);
  assert.equal(loadBoardDef(null), null);
});

test("describeBoardDef reads plainly", () => {
  assert.equal(describeBoardDef(CUSTOM), "9×12 squares, 8 mm squares / 5 mm markers, DICT_4X4_100");
});

test("boardDefError mirrors the backend session validation", () => {
  assert.equal(boardDefError(CUSTOM), null);
  assert.equal(boardDefError({ ...CUSTOM, squaresX: 1 }), "squares X must be 2–40");
  assert.equal(boardDefError({ ...CUSTOM, squaresY: 41 }), "squares Y must be 2–40");
  assert.equal(boardDefError({ ...CUSTOM, markerMm: 8 }), "marker must be > 0 and smaller than the square");
  assert.equal(boardDefError({ ...CUSTOM, dict: "DICT_4X4_50" }), "a 9×12 board needs 54 markers but DICT_4X4_50 has only 50 — use DICT_4X4_100");
  // Dictionaries outside the 4x4 table are left to the backend to check.
  assert.equal(boardDefError({ ...CUSTOM, dict: "DICT_5X5_100" }), null);
});

test("sessionSpecFromDef carries the dictionary to the calibrate session", () => {
  assert.deepEqual(sessionSpecFromDef(CUSTOM), {
    kind: "charuco", squares_x: 9, squares_y: 12, square_length_mm: 8, marker_length_mm: 5, aruco_dict: "DICT_4X4_100",
  });
});

test("the Calibrate page offers every shipped preset as a ready board", () => {
  const c = calibBoardChoices(null);
  assert.deepEqual(c.map((x) => x.key), ["small_cylinder", "fine_20mp", "frame_zoom", "medium_5x7", "large_6x9"]);
  assert.deepEqual(c[2].def, { dict: "DICT_4X4_50", squaresX: 10, squaresY: 7, squareMm: 12, markerMm: 9 });
  assert.deepEqual(c[1].def, { dict: "DICT_4X4_100", squaresX: 12, squaresY: 12, squareMm: 5, markerMm: 3.75 });
  assert.deepEqual(c[0].def, { dict: "DICT_4X4_50", squaresX: 4, squaresY: 4, squareMm: 16, markerMm: 12 });
  assert.match(c[0].label, /4×4.*16 mm/);
});

test("with nothing saved in this browser the small board is chosen (the one engraved)", () => {
  assert.equal(defaultBoardChoice(calibBoardChoices(null), null), "small_cylinder");
});

test("a saved board that matches a preset selects that preset", () => {
  const saved = { dict: "DICT_4X4_50", squaresX: 5, squaresY: 7, squareMm: 25, markerMm: 18 };
  assert.equal(defaultBoardChoice(calibBoardChoices(saved), saved), "medium_5x7");
});

test("a saved custom board is offered and selected, never replaced by a preset", () => {
  const saved = { dict: "DICT_4X4_50", squaresX: 5, squaresY: 5, squareMm: 20, markerMm: 15 };
  const c = calibBoardChoices(saved);
  assert.equal(c.at(-1)?.key, "custom");
  assert.deepEqual(c.at(-1)?.def, saved);
  assert.equal(defaultBoardChoice(c, saved), "custom");
});
