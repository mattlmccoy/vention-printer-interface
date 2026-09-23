import { test } from "node:test";
import assert from "node:assert/strict";
import { bandwidthWarning, EXPOSURE_UNIT_MS, exposureMs, formatExposure, maxFps, SENSOR_MAX } from "./camera_caps.ts";

test("exposureTime is the W3C 100-microsecond unit: value 1 = 0.1 ms", () => {
  assert.equal(EXPOSURE_UNIT_MS, 0.1);
  assert.equal(exposureMs(1), 0.1);
  assert.ok(Math.abs(exposureMs(156) - 15.6) < 1e-9);
});

test("formatExposure contextualizes the raw value with a real-time readout", () => {
  assert.equal(formatExposure(1), "1 (100 µs)"); // sub-millisecond shows µs
  assert.equal(formatExposure(156), "156 (15.6 ms)");
  assert.equal(formatExposure(300), "300 (30.0 ms)");
});

test("maxFps reflects the documented ELP snapshot ceilings", () => {
  // Spec: full-res 5120×3840 → YUY2 7.5 fps, MJPG 27.5 fps.
  assert.equal(maxFps("YUY2", 5120, 3840), 7.5);
  assert.equal(maxFps("MJPG", 5120, 3840), 27.5);
  // Unknown/auto format at full res is the safe (compressed) ceiling, not the YUY2 floor.
  assert.equal(maxFps(null, 5120, 3840), 27.5);
  // Below full res runs at the overview mode's 30 fps regardless of format.
  assert.equal(maxFps("YUY2", 1920, 1080), 30);
  assert.equal(maxFps("MJPG", 1280, 720), 30);
});

test("the fps ceilings are anchored to the AR2020 sensor max", () => {
  assert.deepEqual(SENSOR_MAX, { width: 5120, height: 3840 });
});

test("maxFps follows the camera's REAL modes (ELP descriptor, backend/tests/fixtures/uvc)", () => {
  // The old rule said "every lower resolution runs at 30 fps"; the camera disagrees:
  assert.equal(maxFps("YUY2", 3840, 2160), 23);   // 4K uncompressed tops out at 23
  assert.equal(maxFps("MJPG", 3840, 2160), 30);
  assert.equal(maxFps("YUY2", 4000, 3000), 15);
  assert.equal(maxFps("MJPG", 4000, 3000), 27.5); // 4:3 modes cap at 27.5 even compressed
  assert.equal(maxFps("YUY2", 2592, 1944), 27.5);
  assert.equal(maxFps(null, 3840, 2160), 30);     // auto: the compressed ceiling
  // a size the camera doesn't list keeps the old conservative default
  assert.equal(maxFps("YUY2", 1000, 1000), 30);
});

test("uncompressed modes that need a lot of USB bandwidth are flagged", () => {
  // The failing Windows setup: 5120x3840 YUY2 at 7.5 fps = ~295 MB/s -> truncated frames.
  const w = bandwidthWarning("YUY2", 5120, 3840, 7.5);
  assert.ok(w);
  assert.match(w, /295 MB\/s/);
  assert.match(w, /MJPG/);
  assert.equal(bandwidthWarning("YUY2", 1920, 1080, 30), null); // ~124 MB/s: fine
  assert.equal(bandwidthWarning("MJPG", 5120, 3840, 27.5), null); // compressed on the camera
  assert.equal(bandwidthWarning(null, 5120, 3840, 27.5), null);
});
