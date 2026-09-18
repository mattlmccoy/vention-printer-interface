import { useEffect, useRef } from "react";
import { api } from "../lib/api.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Grab one still from the science stream: full-resolution via ImageCapture.takePhoto when the
 *  browser/camera support it (up to ~20 MP), else a lossless PNG of the current ≤4K video frame. */
async function grabScienceStill(stream: MediaStream | null, video: HTMLVideoElement | null): Promise<Blob | null> {
  const track = stream?.getVideoTracks?.()[0] ?? null;
  const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => { takePhoto: () => Promise<Blob> } }).ImageCapture;
  if (track && IC) {
    try {
      const photo = await new IC(track).takePhoto();
      if (photo && photo.size > 0) return photo; // camera's full-res still (usually JPEG)
    } catch { /* fall through to the live-frame grab */ }
  }
  if (!video || video.videoWidth === 0) return null;
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return await new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/png"));
}

/** Headless client-side SCIENCE capture (the wrong-camera fix). During a recorded print it holds the
 * ASSIGNED science camera open (opened by its browser deviceId — reliable on macOS, unlike the
 * server's cv2 device index that mis-resolves two identical ELPs), heartbeats the operator so the
 * server skips its own grab, and — on each "capture now" signal (status.capture_request.seq) — grabs
 * a frame and uploads it. Decoupled from any live view: renders only a hidden <video>. */
export function ScienceCaptureClient({ status }: { status: StatusPayload | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastSeq = useRef(0);

  const deviceId = loadRoleMap(storage).science;
  const recording = !!status?.recording.active;
  const active = recording && !!deviceId;

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Hold the science camera open (hidden) only while a recorded print is running.
  useEffect(() => {
    if (!active || !deviceId) { stop(); return; }
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        const settings = loadCameraSettings(storage, "science");
        const stream = await md.getUserMedia({ video: videoConstraints(deviceId, settings) });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      } catch {
        // Science camera couldn't open (busy/hi-res not streamable): the operator's fallback grab
        // still runs (the heartbeat below only suppresses it while we're actually holding the cam).
      }
    })();
    return () => { cancelled = true; stop(); };
  }, [active, deviceId]);

  // Heartbeat so the operator knows a client is capturing and skips its own (wrong-camera) grab.
  useEffect(() => {
    if (!active || !streamRef.current) return;
    api.scienceClientHeartbeat().catch(() => {});
    const id = window.setInterval(() => api.scienceClientHeartbeat().catch(() => {}), 3000);
    return () => window.clearInterval(id);
  }, [active, status?.capture_request?.seq]);

  // On each new "capture now" signal, grab a still and upload it (server re-encodes to lossless
  // WebP). Prefers ImageCapture.takePhoto for the camera's FULL sensor resolution (up to ~20 MP on
  // the science ELP) — capture marks fire at gantry-parked dwell points, so the photo latency is
  // fine. Falls back to an instant, pixel-lossless grab of the live frame (≤4K) where takePhoto
  // isn't supported. NOTE: takePhoto returns the camera's own (typically JPEG) encoding, so the
  // full-res path trades pixel-exactness for resolution; the fallback stays lossless. Dedup on seq.
  useEffect(() => {
    const cr = status?.capture_request;
    if (!active || !cr || cr.seq <= lastSeq.current) return;
    lastSeq.current = cr.seq;
    if (cr.layer == null) return;
    const layer = cr.layer;
    const cadLayer = cr.cad_layer ?? undefined;
    const stage = cr.stage;
    let cancelled = false;
    (async () => {
      const blob = await grabScienceStill(streamRef.current, videoRef.current);
      if (!cancelled && blob) api.scienceCaptureUpload(blob, { layer, stage, cadLayer }).catch(() => {});
    })();
    return () => { cancelled = true; };
  }, [status?.capture_request?.seq, active]);

  return <video ref={videoRef} autoPlay playsInline muted style={{ display: "none" }} aria-hidden="true" />;
}
