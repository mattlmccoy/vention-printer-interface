import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_BOARD, boardConfigError, boardQuery, type BoardConfig } from "./board.ts";

test("boardQuery uses preset name and omits explicit geometry for a named preset", () => {
  const q = new URLSearchParams(boardQuery({ ...DEFAULT_BOARD, preset: "large_6x9" }));
  assert.equal(q.get("preset"), "large_6x9");
  assert.equal(q.get("squares_x"), null);
  assert.equal(q.get("format"), "svg");
  assert.equal(q.get("engrave_black"), "true");
});

test("boardQuery sends explicit geometry and no preset for custom", () => {
  const cfg: BoardConfig = { ...DEFAULT_BOARD, preset: "custom", squaresX: 8, squaresY: 6, squareMm: 15, markerMm: 11, format: "dxf" };
  const q = new URLSearchParams(boardQuery(cfg));
  assert.equal(q.get("preset"), null);
  assert.equal(q.get("squares_x"), "8");
  assert.equal(q.get("squares_y"), "6");
  assert.equal(q.get("square_mm"), "15");
  assert.equal(q.get("marker_mm"), "11");
  assert.equal(q.get("format"), "dxf");
});

test("boardQuery formatOverride forces the preview to SVG regardless of download format", () => {
  const q = new URLSearchParams(boardQuery({ ...DEFAULT_BOARD, format: "dxf" }, "svg"));
  assert.equal(q.get("format"), "svg");
});

test("boardConfigError only checks custom and rejects a marker not smaller than the square", () => {
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "medium_5x7" }), null);
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom", squareMm: 10, markerMm: 10 }), "marker must be > 0 and smaller than the square");
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom", squaresX: 99 }), "squares X must be 1–40");
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom" }), null);
});
