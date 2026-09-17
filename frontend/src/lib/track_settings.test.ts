import { test } from "node:test";
import assert from "node:assert/strict";
import { applyPayload, numericControls } from "./track_settings.ts";

test("numericControls surfaces only device-reported numeric ranges, in order", () => {
  const caps = {
    frameRate: { min: 1, max: 30 },
    exposureTime: { min: 10, max: 2000, step: 5 },
    width: { min: 640, max: 3840 }, // not a slider control -> ignored
    whiteBalanceMode: ["manual", "continuous"], // enum -> ignored
    focusMode: ["manual"],
  };
  const settings = { frameRate: 30, exposureTime: 300 };
  const ctls = numericControls(caps, settings);
  assert.deepEqual(ctls.map((c) => c.key), ["frameRate", "exposureTime"]);
  const fps = ctls[0];
  assert.equal(fps.min, 1);
  assert.equal(fps.max, 30);
  assert.equal(fps.value, 30); // from current settings
  const exp = ctls[1];
  assert.equal(exp.step, 5); // device-reported step honoured
  assert.equal(exp.value, 300);
});

test("numericControls invents a ~100-division step when the device omits one, clamps value", () => {
  const ctls = numericControls({ brightness: { min: 0, max: 255 } }, {}); // no current -> min
  assert.equal(ctls.length, 1);
  assert.equal(ctls[0].key, "brightness");
  assert.equal(ctls[0].step, 2.55);
  assert.equal(ctls[0].value, 0);
  // a current value outside the range is clamped in
  assert.equal(numericControls({ zoom: { min: 1, max: 4 } }, { zoom: 99 })[0].value, 4);
});

test("numericControls skips malformed / inverted ranges", () => {
  assert.deepEqual(numericControls({ frameRate: { min: 30, max: 30 } }, {}), []); // max<=min
  assert.deepEqual(numericControls({ frameRate: "junk" }, {}), []);
});

test("applyPayload: frameRate is top-level, manual controls flip their mode", () => {
  assert.deepEqual(applyPayload("frameRate", 24), { frameRate: 24 });
  assert.deepEqual(applyPayload("exposureTime", 500), {
    advanced: [{ exposureTime: 500, exposureMode: "manual" }],
  });
  assert.deepEqual(applyPayload("focusDistance", 3), {
    advanced: [{ focusDistance: 3, focusMode: "manual" }],
  });
  assert.deepEqual(applyPayload("brightness", 128), { advanced: [{ brightness: 128 }] });
});
