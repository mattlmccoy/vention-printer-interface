import { test } from "node:test";
import assert from "node:assert/strict";
import { fullResConstraints, LIGHT_LIVE, lightweightDefault, liveConstraints, loadLightweight, saveLightweight } from "./camera_mode.ts";

const store = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) } as unknown as Storage; };

test("the live cap is the size both cameras shared cleanly on the Windows PC (1280x720 @ 15)", () => {
  assert.deepEqual(LIGHT_LIVE, { width: 1280, height: 720, frameRate: 15 });
});

test("lightweight mode is on by default on Windows only", () => {
  assert.equal(lightweightDefault("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140"), true);
  assert.equal(lightweightDefault("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140"), false);
});

test("an explicit choice overrides the default and is remembered", () => {
  const s = store();
  assert.equal(loadLightweight(s, "Windows NT 10.0"), true);
  saveLightweight(s, false);
  assert.equal(loadLightweight(s, "Windows NT 10.0"), false);
  saveLightweight(s, true);
  assert.equal(loadLightweight(null, "Macintosh"), false); // no storage: the OS default
});

test("lightweight caps a live request at 1280x720 @ 15; off leaves it untouched", () => {
  const base = { deviceId: { exact: "cam" }, width: { ideal: 3840 }, height: { ideal: 2160 }, frameRate: { ideal: 30 } };
  assert.deepEqual(liveConstraints(base, false), base);
  assert.deepEqual(liveConstraints(base, true), {
    deviceId: { exact: "cam" }, width: { ideal: 1280, max: 1280 }, height: { ideal: 720, max: 720 }, frameRate: { ideal: 15, max: 15 },
  });
  // a request already smaller than the cap keeps its own size
  const small = { deviceId: { exact: "cam" }, width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 10 } };
  assert.deepEqual(liveConstraints(small, true), {
    deviceId: { exact: "cam" }, width: { ideal: 640, max: 1280 }, height: { ideal: 480, max: 720 }, frameRate: { ideal: 10, max: 15 },
  });
});

test("a full-res still asks for the saved resolution at a low rate (the camera alone picks uncompressed)", () => {
  assert.deepEqual(fullResConstraints("sci", "5120x3840"), {
    deviceId: { exact: "sci" }, width: { ideal: 5120 }, height: { ideal: 3840 }, frameRate: { ideal: 7.5 },
  });
});
