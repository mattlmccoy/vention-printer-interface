import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.ts";
import { waitForCameraFrame } from "../lib/camera_ready.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Grab one still from the science stream for layerwise CAD analysis, adding NO avoidable loss.
 *  We deliberately do NOT use ImageCapture.takePhoto — it returns the camera's own JPEG and can
 *  re-compress, hurting sub-pixel edge detection. Instead we take the current frame via
 *  ImageCapture.grabFrame (full-res ImageBitmap) or the <video> element and encode PNG (the operator
 *  then stores lossless WebP), so the pipeline adds zero loss on top of the stream.
 *
 *  HARDWARE CAVEAT (be honest): a UVC camera at 20 MP streams MJPEG — the frames are already
 *  JPEG-compressed ON THE CAMERA (uncompressed 20 MP won't fit USB bandwidth), and no browser API
 *  can bypass that. So this is "as lossless as the stream allows", not truly lossless at 20 MP. For
 *  PIXEL-exact stills, pick a lower-resolution UNCOMPRESSED (YUY2) mode if the camera offers one —
 *  trading resolution for true losslessness. Either way this path never adds a second compression. */
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
export function ScienceCaptureClient({ status, onError }: {
  status: StatusPayload | null;
  onError: (message: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastSeq = useRef(0);
  const captureOwnerRef = useRef(false);
  const [streamReady, setStreamReady] = useState(false);
  const [captureOwner, setCaptureOwner] = useState(false);

  const deviceId = loadRoleMap(storage).science;
  const recording = !!status?.recording.active;
  const active = recording && !!deviceId;

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setStreamReady(false);
    captureOwnerRef.current = false;
    setCaptureOwner(false);
  };

  // Hold the science camera open (hidden) only while a recorded print is running.
  useEffect(() => {
    if (!active || !deviceId) { stop(); return; }
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    const controller = new AbortController();
    const video = videoRef.current;
    if (!video) return;
    (async () => {
      const configured = videoConstraints(deviceId, loadCameraSettings(storage, "science"));
      let stream: MediaStream | null = null;
      try {
        stream = await md.getUserMedia({ video: configured });
        if (controller.signal.aborted) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        video.srcObject = stream;
        await waitForCameraFrame(video, controller.signal);
        if (controller.signal.aborted) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        setStreamReady(true);
      } catch {
        stream?.getTracks().forEach((t) => t.stop());
        video.srcObject = null;
        // The configured science mode did not deliver pixels. Do not silently lower the capture
        // resolution because that invalidates calibration; send no heartbeat and let the server
        // capture on demand using its configured camera mode.
      }
    })();
    return () => { controller.abort(); stop(); };
  }, [active, deviceId]);

  // Claim capture ownership only after a real decoded frame exists. A MediaStream object with no
  // pixels must never suppress the server fallback (the former black-panel / lost-layer bug).
  useEffect(() => {
    if (!active || !streamReady) { setCaptureOwner(false); return; }
    let live = true;
    const beat = () => api.scienceClientHeartbeat()
      .then(() => {
        if (live) { captureOwnerRef.current = true; setCaptureOwner(true); }
      })
      .catch(() => {
        if (live) { captureOwnerRef.current = false; setCaptureOwner(false); }
      });
    beat();
    const id = window.setInterval(beat, 3000);
    return () => {
      live = false;
      captureOwnerRef.current = false;
      window.clearInterval(id);
      setCaptureOwner(false);
    };
  }, [active, streamReady]);

  // On each new "capture now" signal, grab a LOSSLESS still and upload it (server re-encodes to
  // lossless WebP → pixel-exact end to end, for CAD comparison). Resolution = the science camera's
  // streamed resolution (set it to the max, up to 20 MP, in Setup). Dedup on seq.
  useEffect(() => {
    const cr = status?.capture_request;
    if (!active || !cr || cr.seq <= lastSeq.current) return;
    lastSeq.current = cr.seq;
    // No verified heartbeat means the server already owns this event and has queued its capture.
    if (!captureOwnerRef.current) return;
    if (cr.layer == null) return;
    const layer = cr.layer;
    const cadLayer = cr.cad_layer ?? undefined;
    const stage = cr.stage;
    let cancelled = false;
    (async () => {
      const blob = await grabScienceStill(streamRef.current, videoRef.current);
      if (cancelled) return;
      if (!blob) {
        stop();
        try {
          await api.scienceClientFallback(cr.seq);
        } catch (error) {
          onError(`Science capture failed for layer ${cadLayer ?? layer}: ${error instanceof Error ? error.message : String(error)}`);
        }
        return;
      }
      try {
        await api.scienceCaptureUpload(blob, { layer, stage, cadLayer });
      } catch (error) {
        stop();
        try {
          await api.scienceClientFallback(cr.seq);
        } catch {
          onError(`Science capture failed for layer ${cadLayer ?? layer}: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [status?.capture_request?.seq, active, captureOwner, onError]);

  return <video ref={videoRef} autoPlay playsInline muted style={{ display: "none" }} aria-hidden="true" />;
}
