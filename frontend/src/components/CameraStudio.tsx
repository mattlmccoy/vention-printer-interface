import { useEffect, useRef, useState } from "react";
import type { CameraRole } from "../lib/camera_roles.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";
import { recordingFilename, snapshotFilename, snapshotOverlay } from "../lib/camera_export.ts";
import { SCIENCE_FALLBACK_CONSTRAINTS, waitForCameraFrame } from "../lib/camera_ready.ts";
import { cameraBus, captureFullResStill } from "../lib/camera_bus.ts";
import { fullResConstraints, lightweightEnabled } from "../lib/camera_mode.ts";
import { grabScienceStill } from "./ScienceCaptureClient.tsx";
import { useLiveCamera } from "./useLiveCamera.ts";
import type { StatusPayload } from "../lib/telemetry.ts";

const ROLE_LABEL: Record<CameraRole, string> = { overview: "overview", science: "science" };

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** One live camera pane: streams the assigned deviceId, with SNAPSHOT (still, metadata burned in +
 *  metadata filename) and RECORD (WebM via MediaRecorder). Hardware-only — getUserMedia can't run
 *  in the headless preview, so this is verified on the machine; the labeling logic is unit-tested
 *  (camera_export.test.ts). */
function CameraPane({ role, deviceId, run }: { role: CameraRole; deviceId: string | null; run: string | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [previewNote, setPreviewNote] = useState("");
  const [retry, setRetry] = useState(0);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const stopLive = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setReady(false);
  };
  const live = useLiveCamera(stopLive, () => setRetry((n) => n + 1));

  useEffect(() => {
    const controller = new AbortController();
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
    setError(null);
    setReady(false);
    setPreviewNote("");
    if (!deviceId) { setError("not assigned — pick this camera in Setup"); return; }
    if (!md?.getUserMedia) { setError("camera access unavailable in this browser"); return; }
    if (cameraBus.paused()) return; // a full-res still has the bus; reopened on resume
    const video = videoRef.current;
    if (!video) return;
    const settings = loadCameraSettings(typeof localStorage === "undefined" ? null : localStorage, role);
    const configured = videoConstraints(deviceId, settings);
    const fallback: MediaTrackConstraints = {
      deviceId: { exact: deviceId },
      ...SCIENCE_FALLBACK_CONSTRAINTS,
    };
    (async () => {
      let lastError = "could not open this camera (in use, or permission denied)";
      for (const [index, constraints] of [configured, fallback].entries()) {
        let stream: MediaStream | null = null;
        try {
          stream = await md.getUserMedia({ video: constraints });
          if (controller.signal.aborted) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          video.srcObject = stream;
          await waitForCameraFrame(video, controller.signal);
          streamRef.current = stream;
          live.watch(stream.getVideoTracks()[0] ?? null);
          setReady(true);
          setPreviewNote(index > 0 ? "reduced-bandwidth preview · saved capture settings unchanged" : "");
          return;
        } catch (cause) {
          stream?.getTracks().forEach((t) => t.stop());
          video.srcObject = null;
          if (cause instanceof Error && cause.name === "AbortError") return;
          if (cause instanceof Error) lastError = cause.message;
        }
      }
      setError(lastError);
    })();
    return () => {
      controller.abort();
      recorderRef.current?.state === "recording" && recorderRef.current.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      video.srcObject = null;
    };
  }, [deviceId, role, retry]);

  // LOSSLESS still at the streamed resolution (set the camera to its max — up to 20 MP — in Setup).
  // Uses ImageCapture.grabFrame (full-res current frame, lossless) when available, else the live
  // <video> frame; NOT takePhoto, whose JPEG encoding is lossy and unfit for CAD-grade analysis.
  // The source is drawn to a canvas so the date/time/metadata overlay is burned into the PNG.
  // Lightweight camera mode (shared USB bus): the live view is capped at 1280x720, so the snapshot is
  // taken as a separate FULL-RES still with this camera alone on the bus (other views paused).
  const fullResSnapshot = async () => {
    if (!deviceId) return;
    setBusy(true);
    try {
      const settings = loadCameraSettings(typeof localStorage === "undefined" ? null : localStorage, role);
      const probe = document.createElement("video");
      probe.muted = true; probe.playsInline = true;
      const [rw, rh] = settings.resolution.split("x").map(Number);
      const r = await captureFullResStill({
        bus: cameraBus,
        releaseMs: 300,
        open: async () => {
          const s = await navigator.mediaDevices.getUserMedia({ video: fullResConstraints(deviceId, settings.resolution) });
          probe.srcObject = s;
          await waitForCameraFrame(probe, new AbortController().signal, 8000);
          return s;
        },
        grab: (s) => grabScienceStill(s, probe, { width: rw || 1920, height: rh || 1080 }, { skipPhoto: true }),
      });
      probe.srcObject = null;
      console.info(`[camera studio] ${role} full-res snapshot: open ${Math.round(r.openMs)} ms, total ${Math.round(r.totalMs)} ms`);
      if (!r.blob) { setError(`full-res snapshot failed: ${r.attempts.join("; ") || "no reason recorded"}`); return; }
      const bmp = await createImageBitmap(r.blob);
      burnAndDownload(bmp, bmp.width, bmp.height);
      bmp.close();
    } finally { setBusy(false); }
  };

  const burnAndDownload = (source: CanvasImageSource, w: number, h: number) => {
    const now = new Date();
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(source, 0, 0, w, h);
    const label = snapshotOverlay(role, w, h, now, run);
    const fs = Math.max(14, Math.round(h / 45));
    ctx.font = `${fs}px monospace`;
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(8, h - fs - 16, tw + 16, fs + 12);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, 16, h - 14);
    canvas.toBlob((b) => { if (b) download(b, snapshotFilename(role, now)); }, "image/png");
  };

  const snapshot = async () => {
    if (lightweightEnabled()) return fullResSnapshot();
    let source: CanvasImageSource | null = null;
    let w = 0, h = 0;
    let bmp: ImageBitmap | null = null;
    const track = streamRef.current?.getVideoTracks?.()[0] ?? null;
    const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => { grabFrame: () => Promise<ImageBitmap> } }).ImageCapture;
    if (track && IC) {
      try {
        bmp = await new IC(track).grabFrame();
        source = bmp; w = bmp.width; h = bmp.height;
      } catch { source = null; }
    }
    if (!source) {
      const v = videoRef.current;
      if (!v || !v.videoWidth) return;
      source = v; w = v.videoWidth; h = v.videoHeight;
    }
    burnAndDownload(source, w, h);
    bmp?.close();
  };

  const toggleRecord = () => {
    const stream = streamRef.current;
    if (!stream) return;
    if (recording) { recorderRef.current?.stop(); return; }
    try {
      const rec = new MediaRecorder(stream, { mimeType: "video/webm" });
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = () => { download(new Blob(chunksRef.current, { type: "video/webm" }), recordingFilename(role, new Date())); setRecording(false); };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
    } catch { setError("recording not supported in this browser"); }
  };

  return (
    <div className="cs-pane" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <b>{ROLE_LABEL[role]}</b>
        {recording && <span className="bad" style={{ fontSize: 12 }}>● REC</span>}
      </div>
      <div style={{ background: "#000", borderRadius: 8, aspectRatio: "16 / 9", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <video ref={videoRef} autoPlay playsInline muted style={{ display: ready ? "block" : "none", width: "100%", height: "100%", objectFit: "contain" }} />
        {!ready && <span role={error ? "alert" : "status"} className="hint" style={{ padding: 12, textAlign: "center" }}>{
          live.paused ? "paused for a full-resolution still…" : live.dropped ? "camera disconnected — reconnecting…" : (error ?? "starting camera…")}</span>}
      </div>
      {previewNote && <span className="hint">{previewNote}</span>}
      <div className="row" style={{ gap: 8 }}>
        {error && deviceId && <button className="small" onClick={() => setRetry((n) => n + 1)}>retry preview</button>}
        <button className="cta sm" disabled={!ready || busy} title={lightweightEnabled() ? "Full-resolution lossless PNG, taken with this camera alone (the live views pause for a moment), with date/time and metadata." : "PNG still at the displayed stream resolution with date/time and metadata. Saved print capture settings are unchanged."} onClick={snapshot}>{busy ? "capturing…" : "snapshot"}</button>
        <button className={`cta sm${recording ? " danger" : ""}`} disabled={!ready} onClick={toggleRecord}>{recording ? "stop recording" : "record"}</button>
      </div>
    </div>
  );
}

/** Double-wide both-cameras studio (#12). Opened from the top-banner camera button. Streams the
 *  overview + science cameras side by side with per-camera snapshot (date/time/metadata burned in)
 *  and WebM recording. */
export function CameraStudio({ status, onClose }: { status: StatusPayload | null; onClose: () => void }) {
  const map = loadRoleMap(typeof localStorage === "undefined" ? null : localStorage);
  const run = status?.recording.run ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="camera studio" onClick={onClose}>
      <div className="cs-panel" onClick={(e) => e.stopPropagation()}
        style={{ width: "min(98vw, 1680px)", maxHeight: "94vh", overflow: "auto", background: "var(--panel, #14161a)", borderRadius: 12, padding: 20 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
          <h3 style={{ margin: 0 }}>camera studio</h3>
          <button className="small" onClick={onClose}>close</button>
        </div>
        <div className="hint" style={{ marginTop: 0 }}>
          Live overview + science cameras. Snapshots and recordings are labeled with date/time and metadata.
          {run ? ` Recording run: ${run}.` : ""}
        </div>
        <div className="cs-grid" style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <CameraPane role="overview" deviceId={map.overview} run={run} />
          <CameraPane role="science" deviceId={map.science} run={run} />
        </div>
      </div>
    </div>
  );
}
