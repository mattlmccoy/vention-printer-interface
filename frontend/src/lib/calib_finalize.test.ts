import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_BED_IMAGE_PX, bedImageSize, parseFinalizeInputs } from "./calib_finalize.ts";

test("bedImageSize matches the backend's warp_to_bed raster size", () => {
  assert.deepEqual(bedImageSize(0.5, [0, 0, 200, 200]), [400, 400]);
  assert.deepEqual(bedImageSize(0.05, [0, 0, 200, 200]), [4000, 4000]);
});

test("parseFinalizeInputs accepts sane inputs", () => {
  assert.deepEqual(parseFinalizeInputs("0.5", "0,0,200,200"), { ok: true, mmPerPx: 0.5, extent: [0, 0, 200, 200] });
  assert.deepEqual(parseFinalizeInputs("0.05", " 0, 0, 200, 200 "), { ok: true, mmPerPx: 0.05, extent: [0, 0, 200, 200] });
});

test("parseFinalizeInputs rejects a non-positive mm/px on the mm/px field", () => {
  for (const v of ["0", "-1", "abc", ""]) {
    const r = parseFinalizeInputs(v, "0,0,200,200");
    assert.equal(r.ok, false);
    if (!r.ok) assert.equal(r.field, "mmPerPx");
  }
});

test("parseFinalizeInputs rejects a malformed or reversed bed extent on the extent field", () => {
  const cases: Array<[string, string]> = [
    ["0,0,200", "bed extent needs 4 numbers: left, top, right, bottom (mm)"],
    ["0,0,x,200", "bed extent needs 4 numbers: left, top, right, bottom (mm)"],
    ["100,0,100,80", "right must be greater than left (got left 100, right 100)"],
    ["0,80,120,10", "bottom must be greater than top (got top 80, bottom 10)"],
  ];
  for (const [ext, msg] of cases) {
    assert.deepEqual(parseFinalizeInputs("0.5", ext), { ok: false, field: "bedExtent", error: msg });
  }
});

test("parseFinalizeInputs rejects a bed image over the 25 MP cap and names the size + minimum", () => {
  assert.equal(MAX_BED_IMAGE_PX, 25_000_000);
  const r = parseFinalizeInputs("0.01", "0,0,200,200");
  assert.deepEqual(r, {
    ok: false,
    field: "mmPerPx",
    error: "0.01 mm/px on a 200×200 mm bed makes a 20000×20000 px image (400.0 MP) — the limit is 25 MP, so use at least 0.04 mm/px",
  });
});
