import { useEffect, useRef, useState } from "react";
import type { CameraRole } from "../lib/camera_roles.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import { loadCameraSettings, videoConstraints } from "../lib/overview_settings.ts";
import { recordingFilename, snapshotFilename, snapshotOverlay } from "../lib/camera_export.ts";
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
  const [recording, setRecording] = useState(false);

  useEffect(() => {
    let alive = true;
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : null;
    setError(null);
    if (!deviceId) { setError("not assigned — pick this camera in Setup"); return; }
    if (!md?.getUserMedia) { setError("camera access unavailable in this browser"); return; }
    const settings = loadCameraSettings(typeof localStorage === "undefined" ? null : localStorage, role);
    md.getUserMedia({ video: videoConstraints(deviceId, settings) })
      .then((stream) => {
        if (!alive) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) { videoRef.current.srcObject = stream; videoRef.current.play().catch(() => {}); }
      })
      .catch(() => { if (alive) setError("could not open this camera (in use, or permission denied)"); });
    return () => {
      alive = false;
      recorderRef.current?.state === "recording" && recorderRef.current.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [deviceId, role]);

  // Full-resolution still: prefer ImageCapture.takePhoto (the camera's FULL sensor size — up to
  // ~20 MP on the science ELP), independent of the ≤4K preview stream. Falls back to grabbing the
  // live video frame where ImageCapture/takePhoto isn't supported. Either source is drawn to a
  // canvas so the date/time/metadata overlay is burned into the exported PNG.
  const snapshot = async () => {
    const now = new Date();
    let source: CanvasImageSource | null = null;
    let w = 0, h = 0;
    let bmp: ImageBitmap | null = null;
    const track = streamRef.current?.getVideoTracks?.()[0] ?? null;
    const IC = (window as unknown as { ImageCapture?: new (t: MediaStreamTrack) => { takePhoto: () => Promise<Blob> } }).ImageCapture;
    if (track && IC) {
      try {
        const blob = await new IC(track).takePhoto();
        bmp = await createImageBitmap(blob);
        source = bmp; w = bmp.width; h = bmp.height;
      } catch { source = null; }
    }
    if (!source) {
      const v = videoRef.current;
      if (!v || !v.videoWidth) return;
      source = v; w = v.videoWidth; h = v.videoHeight;
    }
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) { bmp?.close(); return; }
    ctx.drawImage(source, 0, 0, w, h);
    bmp?.close();
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
        {error
          ? <span className="hint" style={{ padding: 12, textAlign: "center" }}>{error}</span>
          : <video ref={videoRef} autoPlay playsInline muted style={{ width: "100%", height: "100%", objectFit: "contain" }} />}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="cta sm" disabled={!!error} title="Full-resolution still (uses the camera's full sensor, up to 20 MP, where supported) with date/time + metadata burned in." onClick={snapshot}>snapshot</button>
        <button className={`cta sm${recording ? " danger" : ""}`} disabled={!!error} onClick={toggleRecord}>{recording ? "stop recording" : "record"}</button>
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
