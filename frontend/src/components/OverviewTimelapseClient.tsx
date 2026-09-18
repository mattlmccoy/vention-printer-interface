import { useEffect, useRef } from "react";
import { api } from "../lib/api.ts";
import type { StatusPayload } from "../lib/telemetry.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";
import { loadOverviewTimelapse } from "../lib/timelapse_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Headless OVERVIEW timelapse recorder (opt-in). While a print is recording AND the overview
 *  timelapse is enabled AND an overview camera is assigned, this holds the overview stream open and
 *  uploads a wide-view frame every `intervalS` seconds — building a whole-print timelapse of the
 *  streaming overview camera (distinct from the always-on per-layer science timelapse). Visual only,
 *  so frames are moderate-quality WebP. Renders only a hidden <video>. */
export function OverviewTimelapseClient({ status }: { status: StatusPayload | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const settings = loadOverviewTimelapse(storage);
  const deviceId = loadRoleMap(storage).overview;
  const active = !!status?.recording.active && !!deviceId && settings.enabled;

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Hold the overview camera open (hidden) only while a recorded print is running + enabled.
  useEffect(() => {
    if (!active || !deviceId) { stop(); return; }
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        const stream = await md.getUserMedia({ video: videoConstraints(deviceId, loadCameraSettings(storage, "overview")) });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      } catch { /* overview busy/unavailable — no timelapse this run */ }
    })();
    return () => { cancelled = true; stop(); };
  }, [active, deviceId]);

  // Grab + upload one frame every intervalS while active.
  useEffect(() => {
    if (!active) return;
    let busy = false;
    const grab = async () => {
      if (busy) return;
      busy = true;
      try {
        const stream = streamRef.current;
        const video = videoRef.current;
        const track = stream?.getVideoTracks?.()[0] ?? null;
        const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => { grabFrame: () => Promise<ImageBitmap> } }).ImageCapture;
        let source: CanvasImageSource | null = null; let w = 0, h = 0; let bmp: ImageBitmap | null = null;
        if (track && IC) {
          try { bmp = await new IC(track).grabFrame(); source = bmp; w = bmp.width; h = bmp.height; } catch { source = null; }
        }
        if (!source) { if (!video || !video.videoWidth) return; source = video; w = video.videoWidth; h = video.videoHeight; }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) { bmp?.close(); return; }
        ctx.drawImage(source, 0, 0, w, h);
        bmp?.close();
        const blob = await new Promise<Blob | null>((res) => canvas.toBlob((b) => res(b), "image/webp", 0.85));
        if (blob) await api.overviewTimelapseUpload(blob).catch(() => {});
      } finally { busy = false; }
    };
    const id = window.setInterval(grab, Math.max(500, settings.intervalS * 1000));
    return () => window.clearInterval(id);
  }, [active, settings.intervalS]);

  return <video ref={videoRef} autoPlay playsInline muted style={{ display: "none" }} aria-hidden="true" />;
}
