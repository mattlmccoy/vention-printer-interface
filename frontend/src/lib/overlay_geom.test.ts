import { test } from "node:test";
import assert from "node:assert/strict";
import { arrowGain, convexHull, markerQuads, scaleOverlay } from "./overlay_geom.ts";

test("points found on a full-res still are scaled onto a smaller live frame", () => {
  assert.deepEqual(scaleOverlay([[5120, 3840], [2560, 0]], [5120, 3840], [1280, 960]), [[1280, 960], [640, 0]]);
});

test("the convex hull of the points seen so far is the growing calibrated area", () => {
  const pts: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10], [5, 5], [2, 8]];
  const hull = convexHull(pts);
  assert.equal(hull.length, 4);
  for (const corner of [[0, 0], [10, 0], [10, 10], [0, 10]]) assert.ok(hull.some((p) => p[0] === corner[0] && p[1] === corner[1]));
});

test("a hull of fewer than 3 distinct points is empty (nothing to outline)", () => {
  assert.deepEqual(convexHull([[1, 1], [1, 1]]), []);
});

test("marker corners come in fours after the chessboard corners and outline each marker", () => {
  // the operator returns chessboard corners first, then each marker's 4 corners in order
  const pts: [number, number][] = [[0, 0], [1, 1], [10, 10], [12, 10], [12, 12], [10, 12], [20, 20], [22, 20], [22, 22], [20, 22]];
  const quads = markerQuads(pts, 2);
  assert.equal(quads.length, 2);
  assert.deepEqual(quads[0], [[10, 10], [12, 10], [12, 12], [10, 12]]);
});

test("residual arrows are enlarged so the 95th-percentile one draws 2% of the photo width", () => {
  const res: [number, number][] = Array.from({ length: 100 }, (_, i) => [i < 95 ? 1 : 3, 0]);
  // numpy-style linear p95 (as the operator's overlay): rank 94.05 -> 1 + 0.05 * 2 = 1.1 px
  assert.ok(Math.abs(arrowGain(res, 5120) - 0.02 * 5120 / 1.1) < 1e-9);
  assert.equal(arrowGain([], 5120), 1);
});
