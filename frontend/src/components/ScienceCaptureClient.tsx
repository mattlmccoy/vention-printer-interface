import { useEffect, useRef } from "react";
import { api } from "../lib/api.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Grab one LOSSLESS still from the science stream for layerwise CAD analysis. The frame is
 *  captured at the science camera's streamed resolution (set it to the camera's max — up to 20 MP —
 *  in Setup) and encoded as PNG, which is pixel-exact; the operator then stores it as lossless WebP.
 *  We deliberately do NOT use ImageCapture.takePhoto: it returns the camera's own JPEG (lossy), which
 *  corrupts sub-pixel edge detection against CAD. ImageCapture.grabFrame (when available) returns the
 *  current frame as a full-resolution ImageBitmap losslessly; else we draw the <video> element. Both
 *  paths are lossless — the only variable is the streamed resolution. */
async function grabScienceStill(stream: MediaStream | null, video: HTMLVideoElement | null): Promise<Blob | null> {
  const toPng = (source: CanvasImageSource, w: number, h: number): Promise<Blob | null> => {
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return Promise.resolve(null);
    ctx.drawImage(source, 0, 0, w, h);
    return new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/png")); // lossless
  };
  const track = stream?.getVideoTracks?.()[0] ?? null;
  const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => { grabFrame: () => Promise<ImageBitmap> } }).ImageCapture;
  if (track && IC) {
    try {
      const bmp = await new IC(track).grabFrame(); // full-res current frame, lossless
      const blob = await toPng(bmp, bmp.width, bmp.height);
      bmp.close();
      if (blob) return blob;
    } catch { /* fall through to drawing the video element */ }
  }
  if (!video || video.videoWidth === 0) return null;
  return await toPng(video, video.videoWidth, video.videoHeight);
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

  // On each new "capture now" signal, grab a LOSSLESS still and upload it (server re-encodes to
  // lossless WebP → pixel-exact end to end, for CAD comparison). Resolution = the science camera's
  // streamed resolution (set it to the max, up to 20 MP, in Setup). Dedup on seq.
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
