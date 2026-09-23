import { contentStats, type ContentStats } from "./capture_diagnostics.ts";

/** Wait until a video has decoded a real frame. A resolved getUserMedia promise alone is not
 * enough: overloaded UVC cameras can return a live MediaStream that never produces pixels. */
export function waitForCameraFrame(
  video: HTMLVideoElement,
  signal: AbortSignal,
  timeoutMs = 6000,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let poll: ReturnType<typeof setInterval> | undefined;
    let settled = false;
    const cleanup = () => {
      if (timer !== undefined) clearTimeout(timer);
      if (poll !== undefined) clearInterval(poll);
      video.removeEventListener("loadeddata", ready);
      video.removeEventListener("playing", ready);
      video.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
    };
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error); else resolve();
    };
    const ready = () => {
      if (
        video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0
        && cameraSourceHasContent(video, video.videoWidth, video.videoHeight)
      ) finish();
    };
    const failed = () => finish(new Error(video.error?.message || "camera video could not play"));
    const aborted = () => finish(new DOMException("camera open cancelled", "AbortError"));
    video.addEventListener("loadeddata", ready);
    video.addEventListener("playing", ready);
    video.addEventListener("error", failed);
    signal.addEventListener("abort", aborted, { once: true });
    timer = setTimeout(
      () => finish(new Error("camera opened but delivered no usable image")),
      timeoutMs,
    );
    poll = setInterval(ready, 120);
    if (signal.aborted) aborted();
    else {
      video.play().then(ready).catch((error: unknown) => {
        finish(error instanceof Error ? error : new Error(String(error)));
      });
    }
  });
}

/** Grey-level stats of a 48×36 downsample of a camera source (null when it can't be drawn). */
export function cameraSourceStats(source: CanvasImageSource, width: number, height: number): ContentStats | null {
  if (width <= 0 || height <= 0) return null;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 48;
    canvas.height = 36;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    return contentStats(ctx.getImageData(0, 0, canvas.width, canvas.height).data);
  } catch {
    return null;
  }
}

/** Reject all-black, all-white, and near-uniform camera frames. Some UVC failures still report
 * valid dimensions and timestamps while returning an empty grey/black raster. */
export function cameraSourceHasContent(source: CanvasImageSource, width: number, height: number): boolean {
  return cameraSourceStats(source, width, height)?.ok ?? false;
}

export const SCIENCE_FALLBACK_CONSTRAINTS: Omit<MediaTrackConstraints, "deviceId"> = {
  width: { ideal: 1920, max: 1920 },
  height: { ideal: 1080, max: 1080 },
  frameRate: { ideal: 10, max: 15 },
};

/** Stable browser stream used to own layer captures. Full-resolution stills are requested from its
 * exact USB-camera track through ImageCapture.takePhoto when the browser supports it. */
export const SCIENCE_CAPTURE_STREAM_CONSTRAINTS: Omit<MediaTrackConstraints, "deviceId"> = {
  width: { ideal: 1920, max: 1920 },
  height: { ideal: 1080, max: 1080 },
  frameRate: { ideal: 7.5, max: 10 },
};

/** Setup shows two cameras while the persistent dock may already hold a third browser stream.
 * Keep those identification/settings previews deliberately small so identical cameras on one USB
 * controller can all deliver pixels. Recorded-capture settings remain independent. */
export const SETUP_PREVIEW_CONSTRAINTS: Omit<MediaTrackConstraints, "deviceId"> = {
  width: { ideal: 640, max: 1280 },
  height: { ideal: 480, max: 720 },
  frameRate: { ideal: 15, max: 15 },
};
