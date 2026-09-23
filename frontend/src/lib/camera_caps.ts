// The real "scale" behind the two ELP AR2020 camera controls, so the UI can contextualize a raw
// exposure value and cap the fps slider at the documented ceiling instead of showing a blind number.
//
// Sourced from the layerwise-vision spec (docs/superpowers/specs/2026-09-12-layerwise-vision-design.md,
// "Cameras (finalized 2026-09-13)"): both cameras are ELP modules on the Onsemi AR2020 sensor
// (max 5120×3840, USB3/UVC). The per-resolution fps ceilings come from the camera's own mode list
// (MODES below). The resolution ladder itself lives in overview_settings.ts (role-aware); this module
// owns the exposure unit, the fps ceiling and the uncompressed-bandwidth warning.

/** AR2020 sensor maximum (spec) — full-res is where the YUY2/MJPG fps ceilings apply. */
export const SENSOR_MAX = { width: 5120, height: 3840 };

/** The W3C Image Capture spec defines `exposureTime` in 100-microsecond units, so a raw value of 1
 *  means 0.1 ms. This is the unit the live browser preview reports and applies. */
export const EXPOSURE_UNIT_MS = 0.1;

/** Milliseconds for a raw exposure value. */
export function exposureMs(value: number): number {
  return value * EXPOSURE_UNIT_MS;
}

/** A human readout for a raw exposure value: "156 (15.6 ms)" — sub-millisecond shows µs. */
export function formatExposure(value: number): string {
  const ms = exposureMs(value);
  const readout = ms >= 1 ? `${ms.toFixed(1)} ms` : `${Math.round(ms * 1000)} µs`;
  return `${Math.round(value)} (${readout})`;
}

// The ELP 20MP U3's REAL video modes: max fps per resolution for each pixel format, decoded from its
// USB configuration descriptor (captured 2026-09-23, backend/tests/fixtures/uvc/elp_20mp_*.desc.hex).
// The old rule ("every lower resolution runs at 30 fps") was wrong: e.g. 4K YUY2 tops out at 23.
const MODES: Record<string, { mjpg: number; yuy2: number }> = {
  "5120x3840": { mjpg: 27.5, yuy2: 7.5 },
  "4608x3456": { mjpg: 27.5, yuy2: 10 },
  "5120x2880": { mjpg: 30, yuy2: 10 },
  "4096x3072": { mjpg: 27.5, yuy2: 15 },
  "4000x3000": { mjpg: 27.5, yuy2: 15 },
  "4096x2160": { mjpg: 30, yuy2: 20 },
  "3840x2160": { mjpg: 30, yuy2: 23 },
  "3264x2448": { mjpg: 27.5, yuy2: 23 },
  "2592x1944": { mjpg: 27.5, yuy2: 27.5 },
  "2560x1440": { mjpg: 30, yuy2: 30 },
  "2048x1536": { mjpg: 27.5, yuy2: 27.5 },
  "1600x1200": { mjpg: 27.5, yuy2: 27.5 },
  "1920x1080": { mjpg: 30, yuy2: 30 },
  "1280x960": { mjpg: 27.5, yuy2: 27.5 },
  "1280x720": { mjpg: 30, yuy2: 30 },
  "640x480": { mjpg: 27.5, yuy2: 27.5 },
};

/** The camera's max fps for a (format, resolution). Unknown/auto format uses the compressed (MJPG)
 *  ceiling so the slider isn't pinned to the uncompressed floor by default. A size the camera doesn't
 *  list keeps the old conservative 30. */
export function maxFps(format: string | null, width: number, height: number): number {
  const mode = MODES[`${width}x${height}`];
  if (!mode) return 30;
  return (format ?? "").toUpperCase() === "YUY2" ? mode.yuy2 : mode.mjpg;
}

/** Above this, uncompressed video tends to arrive truncated on a shared USB hub. The failing Windows
 *  setup ran ~295 MB/s (5120x3840 YUY2 @ 7.5); one USB 3 port realistically sustains ~300-400 MB/s for
 *  a single device, so this leaves room for a second camera and an adapter on the same hub. */
export const YUY2_WARN_MB_S = 150;

/** A warning when an UNCOMPRESSED (YUY2, 2 bytes/pixel) mode needs more USB bandwidth than a shared
 *  hub reliably carries; null for compressed/auto formats or modest rates. */
export function bandwidthWarning(format: string | null, width: number, height: number, fps: number): string | null {
  if ((format ?? "").toUpperCase() !== "YUY2") return null;
  const mbs = (width * height * 2 * fps) / 1e6;
  if (mbs <= YUY2_WARN_MB_S) return null;
  return `YUY2 at ${width}×${height} · ${fps} fps needs ~${Math.round(mbs)} MB/s of USB bandwidth — frames can arrive incomplete (a green band at the bottom) on a shared hub. Use MJPG, or give this camera its own USB 3 port.`;
}
