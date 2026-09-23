// Why a science still failed, in words. The browser grab has three attempts (full-res photo, live
// frame, video element) and each used to fail silently, so a capture that fell back to the operator
// only ever reported the operator's error (e.g. "503 science capture service is not running") and
// hid the browser's real reason. These helpers keep every reason and say it.

export interface ContentStats { ok: boolean; range: number; std: number; mean: number }

/** Grey-level spread of an RGBA raster (a small downsample of the frame). A frame "has content"
 *  when range >= 20 and std >= 8 — the blank/near-uniform rule used since the black-frame fix, now
 *  returning its numbers so a rejection can say how flat the frame was. */
export function contentStats(pixels: Uint8ClampedArray): ContentStats {
  const n = pixels.length / 4;
  if (n === 0) return { ok: false, range: 0, std: 0, mean: 0 };
  let min = 255;
  let max = 0;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    const y = (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
    min = Math.min(min, y);
    max = Math.max(max, y);
    sum += y;
    sumSq += y * y;
  }
  const mean = sum / n;
  const std = Math.sqrt(Math.max(0, sumSq / n - mean * mean));
  const range = max - min;
  return { ok: range >= 20 && std >= 8, range: Math.round(range), std: Math.round(std), mean: Math.round(mean) };
}

/** "looked blank (range 12, std 5, mean 131)" for a rejected frame. */
export function blankReason(s: ContentStats): string {
  return `looked blank (range ${s.range}, std ${s.std}, mean ${s.mean})`;
}

/** The one error line for a failed science capture: every browser attempt's reason (or that the
 *  still was fine but its upload was refused), then what the operator fallback answered. */
export function captureFailureMessage(i: { layer: number; attempts: string[]; upload: string | null; fallback: string }): string {
  const browser = i.upload != null
    ? `browser still taken but the upload was refused: ${i.upload}`
    : `browser: ${i.attempts.length ? i.attempts.join("; ") : "no reason recorded"}`;
  return `Science capture failed for layer ${i.layer} · ${browser} · operator fallback: ${i.fallback}`;
}
