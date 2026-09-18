import { useEffect, useRef, useState } from "react";
import { loadOverviewCameraId } from "../lib/webcam.ts";
import { loadRoleMap } from "../lib/camera_roles.ts";
import {
  loadCameraSettings,
  resolutionsFor,
  resolutionWH,
  saveCameraSettings,
  videoConstraints,
  type OverviewSettings,
  type SettingsRole,
} from "../lib/overview_settings.ts";
import { applyPayload, numericControls, type NumericControl } from "../lib/track_settings.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

const ROLE_LABEL: Record<SettingsRole, string> = { overview: "Overview", science: "Science" };
const ROLE_NOTE: Record<SettingsRole, string> = {
  overview: "Applies to the overview live view (dock) and is remembered.",
  science: "Remembered and applied when the science camera records bed stills.",
};

/** Live camera settings for one client-side camera role (overview OR science): a live preview, a
 * resolution selector (720p / 1080p / 4K, default 4K@30) and capability-driven sliders (fps,
 * exposure, …) with the camera's REAL min/max via track.getCapabilities(). Resolution needs a fresh
 * stream (reload); the sliders apply live. All choices persist to vpi.<role>Settings. Reads the
 * camera assigned to this role in the tiles above (overview: vpi.overviewCameraId; science:
 * vpi.scienceCameraId). */
export function CameraSettingsPanel({ role }: { role: SettingsRole }) {
  const deviceIdFor = (): string | null =>
    role === "overview" ? loadOverviewCameraId(storage) : loadRoleMap(storage).science;

  const [deviceId, setDeviceId] = useState<string | null>(() => deviceIdFor());
  const [settings, setSettings] = useState<OverviewSettings>(() => loadCameraSettings(storage, role));
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

  // Pick up an (re)assignment made in the tiles above while on this step.
  useEffect(() => {
    const id = window.setInterval(() => setDeviceId(deviceIdFor()), 1500);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, settings.resolution, settings.frameRate, reloadNonce]);

  useEffect(() => stop, []);

  const setResolution = (resolution: string) => {
    setSettings((s) => { const next = { ...s, resolution }; saveCameraSettings(storage, role, next); return next; });
    setReloadNonce((n) => n + 1);
  };
  const setControl = (key: string, value: number) => {
    setControls((cs) => cs.map((c) => (c.key === key ? { ...c, value } : c)));
    trackRef.current?.applyConstraints(applyPayload(key, value)).catch(() => {});
    setSettings((s) => {
      const next: OverviewSettings = key === "frameRate"
        ? { ...s, frameRate: value }
        : { ...s, manual: { ...s.manual, [key]: value } };
      saveCameraSettings(storage, role, next);
      return next;
    });
  };

  // Above ~4K the camera usually can't stream (only shoot a still), so a failed open is expected,
  // not an error — show a "capture-only" note instead of "camera blocked".
  const px = resolutionWH(settings.resolution);
  const captureOnly = px.width * px.height > 8_300_000; // > 4K (e.g. 20 MP)
  const notLiveMsg = status === "denied"
    ? (captureOnly
        ? "This resolution is a still-capture size — the live preview may not run this large."
        : "camera blocked — allow it in the browser")
    : "starting camera…";

  return (
    <div className="grid-gap">
      <b style={{ fontSize: 13 }}>{ROLE_LABEL[role]} camera</b>
      {status === "none" ? (
        <div className="hint" style={{ marginTop: 0 }}>
          Assign a {role} camera above first — these settings tune that camera.
        </div>
      ) : (
        <>
          <div style={{ maxWidth: 480, background: "var(--image-bg, #000)", borderRadius: "var(--radius)", overflow: "hidden", aspectRatio: "16 / 9" }}>
            <video ref={videoRef} autoPlay playsInline muted style={{ display: status === "live" ? "block" : "none", width: "100%", height: "100%", objectFit: "cover" }} />
            {status !== "live" && <div className="chart-empty" style={{ height: "100%", display: "grid", placeItems: "center", textAlign: "center", padding: 12 }}>{notLiveMsg}</div>}
          </div>

          <label className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>resolution</span>
            <select value={settings.resolution} onChange={(e) => setResolution(e.target.value)}>
              {resolutionsFor(role).map((rr) => <option key={rr.key} value={rr.key}>{rr.label}</option>)}
            </select>
            <span className="hint" style={{ marginTop: 0 }}>{captureOnly ? "still capture · fps limited at this size" : "reopens the stream"}</span>
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
            {ROLE_NOTE[role]} Default is 4K @ 30; the browser negotiates down if the camera or USB hub can’t sustain it.
          </span>
        </>
      )}
    </div>
  );
}
