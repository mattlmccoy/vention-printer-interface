/** One-shot science-camera still capture for the CALIBRATION wizard.
 *
 * Calibration used to trigger a SERVER-side grab (cv2 index — the wrong camera on macOS), so the
 * intrinsics/bed homography were fit from a different source than the print-time science captures
 * (which the browser grabs by assigned deviceId). This opens the SAME assigned science camera in
 * the browser, grabs one still, and closes — so calibration shares the exact getUserMedia source
 * the print captures use. Opens on demand (unlike ScienceCaptureClient, which holds it during a
 * print) and reuses the same proven constraints + grab fallbacks. */
import {
  SCIENCE_CAPTURE_STREAM_CONSTRAINTS,
  SETUP_PREVIEW_CONSTRAINTS,
  waitForCameraFrame,
} from "./camera_ready.ts";
import { loadRoleMap } from "./camera_roles.ts";
import { loadCameraSettings } from "./overview_settings.ts";
import { lightweightEnabled } from "./camera_mode.ts";
import { fullResScienceStill, grabScienceStill } from "../components/ScienceCaptureClient.tsx";

export async function captureScienceStillOnce(storage: Storage | null): Promise<Blob> {
  const deviceId = loadRoleMap(storage).science;
  if (!deviceId) {
    throw new Error("No science camera assigned — set it in Cameras → identify & assign first.");
  }
  const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
  if (!md?.getUserMedia) {
    throw new Error("This browser can't open cameras (getUserMedia unavailable).");
  }
  const resolution = loadCameraSettings(storage, "science").resolution;
  const [w, h] = resolution.split("x").map(Number);
  const requested = { width: w || 1920, height: h || 1080 };
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;

  // Lightweight camera mode: print stills are raw full-resolution frames taken with the science
  // camera alone, so calibration/validation stills must be taken the same way — a calibration only
  // holds at the photo size it was fitted on (2026-10-20: these used the <=1080p stream instead).
  if (lightweightEnabled()) {
    const r = await fullResScienceStill(deviceId, resolution, video);
    if (r.blob) return r.blob;
    throw new Error(
      `Could not grab a full-resolution science frame (lightweight camera mode): ${r.attempts.join("; ") || "no reason recorded"}`,
    );
  }

  // Same fallback ladder as the print-capture client: full still constraints, then a lighter preview.
  const reasons: string[] = [];
  for (const constraints of [SCIENCE_CAPTURE_STREAM_CONSTRAINTS, SETUP_PREVIEW_CONSTRAINTS]) {
    let stream: MediaStream | null = null;
    const controller = new AbortController();
    try {
      stream = await md.getUserMedia({
        video: { deviceId: { exact: deviceId }, ...constraints },
      });
      video.srcObject = stream;
      await waitForCameraFrame(video, controller.signal);
      const { blob, attempts } = await grabScienceStill(stream, video, requested);
      if (blob) return blob;
      reasons.push(...attempts);
    } catch (e) {
      reasons.push(`open: ${e instanceof Error ? `${e.name}: ${e.message}` : String(e)}`); // try the next (lighter) set
    } finally {
      stream?.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
    }
  }
  throw new Error(
    `Could not grab a science frame — check the camera is connected and not open elsewhere. (${reasons.join("; ") || "no reason recorded"})`,
  );
}
