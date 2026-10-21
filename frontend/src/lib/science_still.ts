/** One-shot science-camera still capture for the CALIBRATION wizard.
 *
 * Calibration used to trigger a SERVER-side grab (cv2 index — the wrong camera on macOS), so the
 * intrinsics/bed homography were fit from a different source than the print-time science captures
 * (which the browser grabs by assigned deviceId). This opens the SAME assigned science camera in
 * the browser, grabs one still, and closes — so calibration shares the exact getUserMedia source
 * the print captures use. Opens on demand (unlike ScienceCaptureClient, which holds it during a
 * print) and takes the still exactly the way print stills are taken. */
import { loadRoleMap } from "./camera_roles.ts";
import { loadCameraSettings } from "./overview_settings.ts";
import { fullResScienceStill } from "../components/ScienceCaptureClient.tsx";

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
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;

  // Every science still — print, calibration, validation — is the RAW frame at the Camera-settings
  // resolution, taken with the science camera alone (fullResScienceStill). A calibration only holds
  // at the photo size it was fitted on, so all three must share this one path. (Before 0.15.0 the
  // Mac's non-lightweight path took stills from a <=1080p stream.)
  const r = await fullResScienceStill(deviceId, resolution, video);
  if (r.blob) return r.blob;
  throw new Error(
    `Could not grab a full-resolution science frame — check the camera is connected and not open elsewhere. (${r.attempts.join("; ") || "no reason recorded"})`,
  );
}
