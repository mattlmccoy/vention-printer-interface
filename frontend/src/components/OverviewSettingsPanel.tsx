import { useEffect, useRef, useState } from "react";
import { loadOverviewCameraId } from "../lib/webcam.ts";
import {
  loadOverviewSettings,
  RESOLUTIONS,
  saveOverviewSettings,
  videoConstraints,
  type OverviewSettings,
} from "../lib/overview_settings.ts";
import { applyPayload, numericControls, type NumericControl } from "../lib/track_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Live camera settings for the OVERVIEW camera on the SETUP page: a live preview plus a resolution
 * selector (720p / 1080p / 4K, default 4K@30) and capability-driven sliders (fps, exposure, …) with
 * the camera's REAL min/max. Resolution needs a fresh stream (reload); the sliders apply live via
 * applyConstraints. All choices persist to vpi.overviewSettings, so the dock live view uses them too.
 * Reads the overview camera assigned in the tiles above (vpi.overviewCameraId). */
export function OverviewSettingsPanel() {
  const [deviceId, setDeviceId] = useState<string | null>(() => loadOverviewCameraId(storage));
  const [settings, setSettings] = useState<OverviewSettings>(() => loadOverviewSettings(storage));
  const [controls, setControls] = useState<NumericControl[]>([]);
  const [status, setStatus] = useState<"idle" | "live" | "none" | "denied">("idle");
  const [reloadNonce, setReloadNonce] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const trackRef = useRef<MediaStreamTrack | null>(null);

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Re-read the assigned overview if the operator (re)assigns it in the tiles above while on this step.
  useEffect(() => {
    const id = window.setInterval(() => setDeviceId(loadOverviewCameraId(storage)), 1500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!deviceId) { setStatus("none"); return; }
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) { setStatus("none"); return; }
    let cancelled = false;
    (async () => {
      try {
        stop();
        const stream = await md.getUserMedia({ video: videoConstraints(deviceId, settings) });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        const track = stream.getVideoTracks()[0] ?? null;
        trackRef.current = track;
        // Re-apply persisted manual controls (exposure, etc.) to the fresh stream.
        for (const [key, value] of Object.entries(settings.manual)) {
          track?.applyConstraints(applyPayload(key, value)).catch(() => {});
        }
        try {
          const caps = (track?.getCapabilities?.() ?? {}) as Record<string, unknown>;
          const set = (track?.getSettings?.() ?? {}) as Record<string, unknown>;
          setControls(numericControls(caps, set));
        } catch { setControls([]); }
        setStatus("live");
      } catch {
        if (!cancelled) setStatus("denied");
      }
    })();
    return () => { cancelled = true; };
    // settings.manual is intentionally excluded — manual tweaks apply live, they don't reopen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, settings.resolution, settings.frameRate, reloadNonce]);

  useEffect(() => stop, []);

  const setResolution = (resolution: string) => {
    setSettings((s) => { const next = { ...s, resolution }; saveOverviewSettings(storage, next); return next; });
    setReloadNonce((n) => n + 1);
  };

  // Live control: apply to the running track now, persist for next open (fps -> frameRate, rest -> manual).
  const setControl = (key: string, value: number) => {
    setControls((cs) => cs.map((c) => (c.key === key ? { ...c, value } : c)));
    trackRef.current?.applyConstraints(applyPayload(key, value)).catch(() => {});
    setSettings((s) => {
      const next: OverviewSettings = key === "frameRate"
        ? { ...s, frameRate: value }
        : { ...s, manual: { ...s.manual, [key]: value } };
      saveOverviewSettings(storage, next);
      return next;
    });
  };

  if (status === "none") {
    return (
      <div className="hint" style={{ marginTop: 0 }}>
        Assign an overview camera above first — these settings tune that camera’s live view.
      </div>
    );
  }

  return (
    <div className="grid-gap">
      <div style={{ maxWidth: 480, background: "var(--image-bg, #000)", borderRadius: "var(--radius)", overflow: "hidden", aspectRatio: "16 / 9" }}>
        <video ref={videoRef} autoPlay playsInline muted style={{ display: status === "live" ? "block" : "none", width: "100%", height: "100%", objectFit: "cover" }} />
        {status !== "live" && <div className="chart-empty" style={{ height: "100%" }}>{status === "denied" ? "camera blocked — allow it in the browser" : "starting camera…"}</div>}
      </div>

      <label className="row" style={{ gap: 8, alignItems: "center" }}>
        <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>resolution</span>
        <select value={settings.resolution} onChange={(e) => setResolution(e.target.value)}>
          {RESOLUTIONS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select>
        <span className="hint" style={{ marginTop: 0 }}>reopens the stream</span>
      </label>

      {status === "live" && (controls.length === 0 ? (
        <span className="hint" style={{ marginTop: 0 }}>this camera/browser exposes no adjustable controls</span>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {controls.map((c) => (
            <label key={c.key} className="row" style={{ gap: 8, alignItems: "center" }}>
              <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>{c.label}</span>
              <input type="range" min={c.min} max={c.max} step={c.step} value={c.value}
                onChange={(e) => setControl(c.key, Number(e.target.value))} style={{ flex: 1 }} />
              <span className="hint" style={{ minWidth: 56, textAlign: "right", marginTop: 0 }}>
                {c.key === "frameRate" ? `${Math.round(c.value)} fps` : c.value.toFixed(c.step < 1 ? 2 : 0)}
              </span>
            </label>
          ))}
        </div>
      ))}

      <span className="hint" style={{ marginTop: 0 }}>
        Applies to the overview live view (dock) and is remembered. Default is 4K @ 30; the browser
        negotiates down if the camera or USB hub can’t sustain it.
      </span>
    </div>
  );
}
