// The real "scale" behind the two ELP AR2020 camera controls, so the UI can contextualize a raw
// exposure value and cap the fps slider at the documented ceiling instead of showing a blind number.
//
// Sourced from the layerwise-vision spec (docs/superpowers/specs/2026-09-12-layerwise-vision-design.md,
// "Cameras (finalized 2026-09-13)"): both cameras are ELP modules on the Onsemi AR2020 sensor
// (max 5120×3840, USB3/UVC). Science full-res is YUY2 @ 7.5 fps or MJPG @ 27.5 fps; every lower
// resolution streams at 30 fps (the overview live mode). The resolution ladder itself lives in
// overview_settings.ts (role-aware); this module owns only the exposure unit and the fps ceiling.

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

/** The documented max fps for a (format, resolution): full-res 5120×3840 → YUY2 7.5 / MJPG 27.5
 *  (spec); every lower resolution runs at the 30 fps overview mode. Unknown/auto format at full res
 *  uses the compressed (higher) ceiling so the slider isn't pinned to the YUY2 floor by default. */
export function maxFps(format: string | null, width: number, height: number): number {
  const fullRes = width >= SENSOR_MAX.width && height >= SENSOR_MAX.height;
  if (!fullRes) return 30;
  return (format ?? "").toUpperCase() === "YUY2" ? 7.5 : 27.5;
}
