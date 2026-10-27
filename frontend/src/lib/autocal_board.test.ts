import { test } from "node:test";
import assert from "node:assert/strict";
import { autocalSpec, CERTIFIED_PLATE, lengthReferenceText } from "./autocal_board.ts";
import type { BoardDef } from "./board_def.ts";

const SMALL: BoardDef = { dict: "DICT_4X4_50", squaresX: 4, squaresY: 4, squareMm: 16, markerMm: 12 };

test("the certified plate runs as a checkerboard of its real size", () => {
  assert.deepEqual(autocalSpec(CERTIFIED_PLATE.key, null),
    { kind: "checkerboard", cols: 17, rows: 17, square_size_mm: 4.5 });
});

test("any other choice is the ChArUco board it names", () => {
  assert.deepEqual(autocalSpec("small_cylinder", SMALL), {
    kind: "charuco", squares_x: 4, squares_y: 4, square_length_mm: 16, marker_length_mm: 12, aruco_dict: "DICT_4X4_50",
  });
});

test("no board picked gives no spec", () => {
  assert.equal(autocalSpec("small_cylinder", null), null);
});

test("a plate run says the plate is the ruler and how far the encoder disagrees", () => {
  assert.equal(lengthReferenceText({ scale_reference: "board", scale_ratio: 0.99912 }),
    "the certified plate; the recoater encoder disagrees by 0.09 %");
});

test("a ChArUco run says it was rescaled to the encoder", () => {
  assert.equal(lengthReferenceText({ scale_reference: "encoder", scale_ratio: 1.0018 }),
    "the recoater encoder (the board measured 0.18 % off and was rescaled)");
  assert.equal(lengthReferenceText({ scale_ratio: 1.0018 }),
    "the recoater encoder (the board measured 0.18 % off and was rescaled)");  // before 0.23.0
});
