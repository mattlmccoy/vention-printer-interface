import { test } from "node:test";
import assert from "node:assert/strict";
import { browserResetPlan, defaultUvcCamera, type UvcCamera } from "./uvc_controls.ts";

const A: UvcCamera = { unique_id: "0x23100032e42020", name: "20MP U3 Camera", science: false };
const B: UvcCamera = { unique_id: "0x23400032e42020", name: "20MP U3 Camera", science: true };

test("a saved pick wins while that camera is still attached", () => {
  assert.equal(defaultUvcCamera("overview", [A, B], B.unique_id), B.unique_id);
  assert.equal(defaultUvcCamera("overview", [A], B.unique_id), A.unique_id); // gone -> fallback
});

test("science defaults to the bound science camera", () => {
  assert.equal(defaultUvcCamera("science", [A, B], null), B.unique_id);
});

test("overview takes the other camera only when that is unambiguous", () => {
  assert.equal(defaultUvcCamera("overview", [A, B], null), A.unique_id);
  const C = { ...A, unique_id: "0x1", science: false };
  assert.equal(defaultUvcCamera("overview", [A, C, B], null), null); // two candidates: operator picks
  assert.equal(defaultUvcCamera("science", [A, { ...B, science: false }], null), null); // none bound
});

test("a single camera is the default for either role", () => {
  assert.equal(defaultUvcCamera("science", [A], null), A.unique_id);
  assert.equal(defaultUvcCamera("overview", [], null), null);
});

test("browser reset: auto modes back on, where the browser offers continuous", () => {
  const plan = browserResetPlan({
    exposureMode: ["manual", "continuous"], whiteBalanceMode: ["manual", "continuous"], focusMode: ["manual"],
  });
  assert.deepEqual(plan.constraints, [{ exposureMode: "continuous" }, { whiteBalanceMode: "continuous" }]);
});

test("browser reset applies the ELP factory default only when the range matches the camera's", () => {
  // Ranges captured from the ELP 20MP U3 over UVC (GET_MIN/MAX/DEF): brightness 0..255 def 128,
  // contrast 0..128 def 65. A matching range means the browser uses the same raw scale.
  const plan = browserResetPlan({
    brightness: { min: 0, max: 255, step: 1 },
    contrast: { min: 0, max: 128, step: 1 },
    saturation: { min: -100, max: 100, step: 1 }, // different scale: can't know its default
  });
  assert.deepEqual(plan.constraints, [{ brightness: 128 }, { contrast: 65 }]);
  assert.deepEqual(plan.unknown, ["saturation"]);
});

test("browser reset with no controls is empty, not an error", () => {
  assert.deepEqual(browserResetPlan({}), { constraints: [], unknown: [] });
});
