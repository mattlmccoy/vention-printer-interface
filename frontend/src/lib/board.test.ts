import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_BOARD, PRESET_GEOMETRY, boardConfigError, boardGeometry, boardQuery, fetchBoardPreview, markersNeeded, pickArucoDict,
  type BoardConfig,
} from "./board.ts";

test("boardQuery sends the cut-outline flag (on by default, off when disabled)", () => {
  assert.equal(new URLSearchParams(boardQuery(DEFAULT_BOARD)).get("cut_outline"), "true");
  const off = boardQuery({ ...DEFAULT_BOARD, cutOutline: false });
  assert.equal(new URLSearchParams(off).get("cut_outline"), "false");
});

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
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom", squaresX: 99 }), "squares X must be 2–40");
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom" }), null);
});

// ---- dictionary auto-pick + preview fetch (fix/charuco-board-calibrate) ----------------------

test("markersNeeded is floor(sx*sy/2), like cv2's CharucoBoard", () => {
  assert.equal(markersNeeded(9, 12), 54);
  assert.equal(markersNeeded(5, 7), 17);
});

test("pickArucoDict mirrors the backend: smallest adequate 4x4 dictionary", () => {
  assert.equal(pickArucoDict(4, 4), "DICT_4X4_50");
  assert.equal(pickArucoDict(10, 10), "DICT_4X4_50");
  assert.equal(pickArucoDict(9, 12), "DICT_4X4_100");
  assert.equal(pickArucoDict(20, 20), "DICT_4X4_250");
  assert.equal(pickArucoDict(40, 40), "DICT_4X4_1000");
});

test("PRESET_GEOMETRY mirrors backend board_gen.BOARD_PRESETS", () => {
  assert.deepEqual(PRESET_GEOMETRY.small_cylinder, { squaresX: 4, squaresY: 4, squareMm: 16, markerMm: 12 });
  assert.deepEqual(PRESET_GEOMETRY.medium_5x7, { squaresX: 5, squaresY: 7, squareMm: 25, markerMm: 18 });
  assert.deepEqual(PRESET_GEOMETRY.large_6x9, { squaresX: 6, squaresY: 9, squareMm: 30, markerMm: 22 });
  assert.deepEqual(boardGeometry({ ...DEFAULT_BOARD, preset: "large_6x9" }), PRESET_GEOMETRY.large_6x9);
  assert.deepEqual(boardGeometry({ ...DEFAULT_BOARD, preset: "custom", squaresX: 9, squaresY: 12, squareMm: 8, markerMm: 5 }),
    { squaresX: 9, squaresY: 12, squareMm: 8, markerMm: 5 });
});

test("boardConfigError rejects a 1-wide grid (cv2 crashes on it)", () => {
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom", squaresX: 1 }), "squares X must be 2–40");
  assert.equal(boardConfigError({ ...DEFAULT_BOARD, preset: "custom", squaresY: 1 }), "squares Y must be 2–40");
});

function fakeFetch(status: number, body: string, headers: Record<string, string> = {}) {
  return async (_url: string, _init?: { signal?: AbortSignal }) =>
    new Response(body, { status, headers });
}

test("fetchBoardPreview returns the SVG and the dictionary header on success", async () => {
  const r = await fetchBoardPreview("u", undefined, fakeFetch(200, "<svg/>", { "X-Board-Dict": "DICT_4X4_100" }));
  assert.deepEqual(r, { ok: true, svg: "<svg/>", dict: "DICT_4X4_100" });
});

test("fetchBoardPreview surfaces the backend's error detail instead of hiding it", async () => {
  const r = await fetchBoardPreview("u", undefined, fakeFetch(400, JSON.stringify({ detail: "invalid board spec: needs 54 markers" })));
  assert.deepEqual(r, { ok: false, error: "invalid board spec: needs 54 markers" });
  const r2 = await fetchBoardPreview("u", undefined, fakeFetch(500, "Internal Server Error"));
  assert.deepEqual(r2, { ok: false, error: "500 Internal Server Error" });
  const r3 = await fetchBoardPreview("u", undefined, async () => { throw new TypeError("Failed to fetch"); });
  assert.deepEqual(r3, { ok: false, error: "could not reach the operator: Failed to fetch" });
});
