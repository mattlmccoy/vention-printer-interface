import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.ts";
import {
  cameraSourceStats,
  cameraSourceTruncation,
  SCIENCE_CAPTURE_STREAM_CONSTRAINTS,
  SETUP_PREVIEW_CONSTRAINTS,
  waitForCameraFrame,
} from "../lib/camera_ready.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings } from "../lib/overview_settings.ts";
import { blankReason, captureFailureMessage } from "../lib/capture_diagnostics.ts";
import { cameraBus, captureFullResStill } from "../lib/camera_bus.ts";
import { fullResConstraints, lightweightEnabled } from "../lib/camera_mode.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Grab one still from the exact assigned science-camera track for layerwise CAD analysis. Prefer
 *  ImageCapture.takePhoto at the requested still resolution; if the browser/camera does not expose
 *  it, use the current validated stream frame and encode it as PNG before upload.
 *
 *  HARDWARE CAVEAT (be honest): a UVC camera at 20 MP streams MJPEG — the frames are already
 *  JPEG-compressed ON THE CAMERA (uncompressed 20 MP won't fit USB bandwidth), and no browser API
 *  can bypass that. So this is "as lossless as the stream allows", not truly lossless at 20 MP. For
 *  PIXEL-exact stills, pick a lower-resolution UNCOMPRESSED (YUY2) mode if the camera offers one.
 *  Every path rejects blank and near-uniform frames before they can be recorded as captures, and
 *  every failed path records WHY in `attempts` (it used to fail silently). */
export async function grabScienceStill(
  stream: MediaStream | null,
  video: HTMLVideoElement | null,
  requested: { width: number; height: number },
  opts: { skipPhoto?: boolean } = {},
): Promise<{ blob: Blob | null; attempts: string[] }> {
  const attempts: string[] = [];
  const why = (e: unknown) => (e instanceof Error ? `${e.name}: ${e.message}` : String(e));
  const toPng = (source: CanvasImageSource, w: number, h: number, path: string): Promise<Blob | null> => {
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) { attempts.push(`${path}: no 2D canvas`); return Promise.resolve(null); }
    ctx.drawImage(source, 0, 0, w, h);
    const stats = cameraSourceStats(canvas, w, h);
    if (!stats?.ok) { attempts.push(`${path}: ${stats ? blankReason(stats) : "could not be read"} at ${w}x${h}`); return Promise.resolve(null); }
    const cut = cameraSourceTruncation(canvas);
    if (cut) { attempts.push(`${path}: ${cut} at ${w}x${h}`); return Promise.resolve(null); }
    return new Promise((resolve) => canvas.toBlob((b) => {
      if (!b) attempts.push(`${path}: PNG encode failed`);
      resolve(b);
    }, "image/png")); // lossless
  };
  const track = stream?.getVideoTracks?.()[0] ?? null;
  const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => {
    takePhoto?: (settings?: { imageWidth?: number; imageHeight?: number }) => Promise<Blob>;
    grabFrame: () => Promise<ImageBitmap>;
  } }).ImageCapture;
  if (!track) attempts.push(`camera: no live track (${stream ? "stream has no video" : "no stream"})`);
  else if (track.readyState !== "live") attempts.push(`camera: track ${track.readyState}`);
  if (track && IC) {
    const capture = new IC(track);
    // skipPhoto: the full-res lightweight path wants the RAW frame (PNG, lossless), never the
    // camera's own JPEG photo.
    if (capture.takePhoto && !opts.skipPhoto) {
      try {
        const photo = await capture.takePhoto({
          imageWidth: requested.width,
          imageHeight: requested.height,
        });
        const bitmap = await createImageBitmap(photo);
        const stats = cameraSourceStats(bitmap, bitmap.width, bitmap.height);
        const cut = stats?.ok ? cameraSourceTruncation(bitmap) : null;
        const size = `${bitmap.width}x${bitmap.height}`;
        bitmap.close();
        if (stats?.ok && !cut) return { blob: photo, attempts };
        attempts.push(`photo: ${cut ?? (stats ? blankReason(stats) : "could not be read")} at ${size}`);
      } catch (e) { attempts.push(`photo ${requested.width}x${requested.height}: ${why(e)}`); }
    } else if (!opts.skipPhoto) attempts.push("photo: takePhoto unsupported");
    try {
      const bmp = await capture.grabFrame();
      const blob = await toPng(bmp, bmp.width, bmp.height, "frame");
      bmp.close();
      if (blob) return { blob, attempts };
    } catch (e) { attempts.push(`frame: ${why(e)}`); }
  } else if (track) attempts.push("photo/frame: ImageCapture unavailable");
  if (!video || video.videoWidth === 0) {
    attempts.push(`video: no picture (${video ? `${video.videoWidth}x${video.videoHeight}` : "no element"})`);
    return { blob: null, attempts };
  }
  return { blob: await toPng(video, video.videoWidth, video.videoHeight, "video"), attempts };
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
  // Lightweight camera mode (shared USB bus): don't hold the science camera open during the print —
  // open it ALONE at full resolution for each still (camera_bus.ts), so the overview keeps the bus.
  const light = lightweightEnabled();

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
      for (const constraints of [SCIENCE_CAPTURE_STREAM_CONSTRAINTS, SETUP_PREVIEW_CONSTRAINTS]) {
        let stream: MediaStream | null = null;
        try {
          stream = await md.getUserMedia({
            video: { deviceId: { exact: deviceId }, ...constraints },
          });
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
          if (light) {
            // Probe only: the camera produces real frames, so this client can own captures. It is
            // released at once and reopened at full resolution for each still.
            stream.getTracks().forEach((t) => t.stop());
            video.srcObject = null;
          } else {
            streamRef.current = stream;
          }
          setStreamReady(true);
          return;
        } catch (cause) {
          stream?.getTracks().forEach((t) => t.stop());
          video.srcObject = null;
          if (cause instanceof Error && cause.name === "AbortError") return;
        }
      }
      // No exact-device stream produced a real image. Do not heartbeat: the status banner will
      // report the capture unavailable, and macOS will never try an unsafe index fallback.
    })();
    return () => { controller.abort(); stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, deviceId, light]);

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

  // On each new "capture now" signal, ask the exact assigned track for a full-resolution still.
  // Fall back to its validated live frame, never to an OS camera index. Dedup on seq.
  useEffect(() => {
    const cr = status?.capture_request;
    if (!active || !cr || cr.seq <= lastSeq.current) return;
    lastSeq.current = cr.seq;
    if (!captureOwnerRef.current) {
      if (cr.server_fallback_blocked) {
        onError(`Science capture failed for layer ${cr.cad_layer ?? cr.layer}: assigned USB camera did not produce a usable frame; unsafe macOS index fallback was blocked.`);
      }
      return;
    }
    if (cr.layer == null) return;
    const layer = cr.layer;
    const cadLayer = cr.cad_layer ?? undefined;
    const stage = cr.stage;
    let cancelled = false;
    (async () => {
      const resolution = loadCameraSettings(storage, "science").resolution;
      const desired = resolution.split("x").map(Number);
      const requested = {
        width: Number.isFinite(desired[0]) ? desired[0] : 1920,
        height: Number.isFinite(desired[1]) ? desired[1] : 1080,
      };
      const video = videoRef.current;
      const { blob, attempts } = light && deviceId && video
        ? await (async () => {
          const r = await captureFullResStill({
            bus: cameraBus,
            releaseMs: 300,
            open: async () => {
              const s = await navigator.mediaDevices.getUserMedia({ video: fullResConstraints(deviceId, resolution) });
              video.srcObject = s;
              await waitForCameraFrame(video, new AbortController().signal, 8000);
              return s;
            },
            grab: (s) => grabScienceStill(s, video, requested, { skipPhoto: true }),
          });
          video.srcObject = null;
          console.info(`science still layer ${cadLayer ?? layer} ${stage}: full-res open ${Math.round(r.openMs)} ms, total ${Math.round(r.totalMs)} ms (lightweight camera mode)`);
          return r;
        })()
        : await grabScienceStill(streamRef.current, videoRef.current, requested);
      if (cancelled) return;
      const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));
      if (!blob) {
        if (!light) stop(); // a held stream that failed is dropped; on-demand keeps capture duty
        try {
          await api.scienceClientFallback(cr.seq);
          // The operator took this one; keep the browser's reason visible for diagnosis.
          console.warn(`science capture layer ${cadLayer ?? layer}: browser grab failed (${attempts.join("; ")}); operator fallback took it`);
        } catch (error) {
          onError(captureFailureMessage({ layer: cadLayer ?? layer, attempts, upload: null, fallback: msg(error) }));
        }
        return;
      }
      try {
        await api.scienceCaptureUpload(blob, { layer, stage, cadLayer });
      } catch (error) {
        if (!light) stop();
        try {
          await api.scienceClientFallback(cr.seq);
        } catch (fallbackError) {
          onError(captureFailureMessage({ layer: cadLayer ?? layer, attempts, upload: msg(error), fallback: msg(fallbackError) }));
        }
      }
    })();
    return () => { cancelled = true; };
  }, [status?.capture_request?.seq, active, captureOwner, onError]);

  return <video ref={videoRef} autoPlay playsInline muted style={{ display: "none" }} aria-hidden="true" />;
}
