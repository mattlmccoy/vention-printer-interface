/** Wait until a video has decoded a real frame. A resolved getUserMedia promise alone is not
 * enough: overloaded UVC cameras can return a live MediaStream that never produces pixels. */
export function waitForCameraFrame(
  video: HTMLVideoElement,
  signal: AbortSignal,
  timeoutMs = 6000,
): Promise<void> {
  return new Promise((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout>;
    const cleanup = () => {
      clearTimeout(timer);
      video.removeEventListener("loadeddata", ready);
      video.removeEventListener("playing", ready);
      video.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
    };
    const finish = (error?: Error) => {
      cleanup();
      if (error) reject(error); else resolve();
    };
    const ready = () => {
      if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) finish();
    };
    const failed = () => finish(new Error(video.error?.message || "camera video could not play"));
    const aborted = () => finish(new DOMException("camera open cancelled", "AbortError"));
    video.addEventListener("loadeddata", ready);
    video.addEventListener("playing", ready);
    video.addEventListener("error", failed);
    signal.addEventListener("abort", aborted, { once: true });
    timer = setTimeout(
      () => finish(new Error("camera opened but delivered no playable frames")),
      timeoutMs,
    );
    if (signal.aborted) aborted();
    else {
      video.play().then(ready).catch((error: unknown) => {
        finish(error instanceof Error ? error : new Error(String(error)));
      });
    }
  });
}

export const SCIENCE_FALLBACK_CONSTRAINTS: Omit<MediaTrackConstraints, "deviceId"> = {
  width: { ideal: 1920, max: 1920 },
  height: { ideal: 1080, max: 1080 },
  frameRate: { ideal: 10, max: 15 },
};

/** Setup shows two cameras while the persistent dock may already hold a third browser stream.
 * Keep those identification/settings previews deliberately small so identical cameras on one USB
 * controller can all deliver pixels. Recorded-capture settings remain independent. */
export const SETUP_PREVIEW_CONSTRAINTS: Omit<MediaTrackConstraints, "deviceId"> = {
  width: { ideal: 640, max: 1280 },
  height: { ideal: 480, max: 720 },
  frameRate: { ideal: 15, max: 15 },
};
