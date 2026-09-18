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
import { formatExposure, maxFps } from "../lib/camera_caps.ts";
import { api } from "../lib/api.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

const ROLE_LABEL: Record<SettingsRole, string> = { overview: "Overview", science: "Science" };
const ROLE_NOTE: Record<SettingsRole, string> = {
  overview: "Applies to the overview live view (dock) and is remembered.",
  science: "Remembered and applied when the science camera records bed stills.",
};

/** One capability-driven panel per camera role. A live preview, a resolution DROPDOWN, an fps SLIDER
 *  capped at the documented mode ceiling (YUY2 20 MP → 7.5 fps, MJPG → 27.5, lower res → 30), an
 *  exposure SLIDER read from the camera's REAL range and shown in real time (value → ms), plus the
 *  server-only YUY2/MJPG pixel-format control (getUserMedia can't force a format). The resolution /
 *  fps / format / exposure choices are written through to the server capture settings so recorded
 *  bed stills use them; the sliders also apply live to the preview. Reads the camera assigned to this
 *  role in the tiles above. */
export function CameraSettingsPanel({ role }: { role: SettingsRole }) {
  const deviceIdFor = (): string | null =>
    role === "overview" ? loadOverviewCameraId(storage) : loadRoleMap(storage).science;

  const [deviceId, setDeviceId] = useState<string | null>(() => deviceIdFor());
  const [settings, setSettings] = useState<OverviewSettings>(() => loadCameraSettings(storage, role));
  const [controls, setControls] = useState<NumericControl[]>([]);
  const [status, setStatus] = useState<"idle" | "live" | "none" | "denied">("idle");
  const [reloadNonce, setReloadNonce] = useState(0);
  const [format, setFormat] = useState<string>(""); // "" = auto, else YUY2 / MJPG (server-side)
  const [model, setModel] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const trackRef = useRef<MediaStreamTrack | null>(null);
  const pushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Seed the panel from the server-side capture settings once, so it shows what will ACTUALLY be
  // recorded (e.g. the science default 20 MP · YUY2 · 7.5 fps) rather than a client-side guess. Format
  // lives only server-side; resolution / fps / exposure are mirrored into the client settings.
  useEffect(() => {
    api.visionGetSettings().then((all) => {
      const s = all[role];
      if (!s) return;
      if (typeof s.format === "string") setFormat(s.format);
      setSettings((prev) => {
        const next: OverviewSettings = { ...prev, manual: { ...prev.manual } };
        if (Array.isArray(s.resolution) && s.resolution.length === 2) next.resolution = `${s.resolution[0]}x${s.resolution[1]}`;
        else if (typeof s.resolution === "string") next.resolution = s.resolution;
        if (typeof s.fps === "number") next.frameRate = s.fps;
        if (typeof s.exposure === "number") next.manual.exposureTime = s.exposure;
        saveCameraSettings(storage, role, next);
        return next;
      });
    }).catch(() => {});
    api.visionDevices().then((d) => { const dev = d.devices.find((x) => x.role === role); setModel(dev?.name ?? null); }).catch(() => {});
  }, [role]);

  // Push resolution / fps / format / exposure through to the server capture settings (debounced, so
  // dragging a slider doesn't flood the operator). Only set fields are sent (server merges per field).
  const pushServer = (over: { fps?: number; format?: string; exposure?: number | null } = {}) => {
    if (pushTimer.current) clearTimeout(pushTimer.current);
    pushTimer.current = setTimeout(() => {
      setSettings((s) => {
        const { width, height } = resolutionWH(s.resolution);
        const exposure = "exposure" in over ? over.exposure : (s.manual.exposureTime ?? null);
        const body: { resolution: [number, number]; fps: number; format?: string; exposure?: number } = {
          resolution: [width, height],
          fps: over.fps ?? s.frameRate,
        };
        const fmt = over.format ?? format;
        if (fmt) body.format = fmt;
        if (typeof exposure === "number") body.exposure = exposure;
        api.visionSetSettings({ [role]: body }).catch(() => {});
        return s;
      });
    }, 300);
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
          // fps has its own dedicated slider (capped at the documented mode ceiling), so drop the
          // browser's frameRate control here to avoid a second, differently-scaled fps slider.
          setControls(numericControls(caps, set).filter((c) => c.key !== "frameRate"));
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

  const px = resolutionWH(settings.resolution);
  const fpsCeiling = maxFps(format || null, px.width, px.height);

  const setResolution = (resolution: string) => {
    const wh = resolutionWH(resolution);
    const ceiling = maxFps(format || null, wh.width, wh.height);
    setSettings((s) => {
      const frameRate = Math.min(s.frameRate, ceiling);
      const next = { ...s, resolution, frameRate };
      saveCameraSettings(storage, role, next);
      return next;
    });
    setReloadNonce((n) => n + 1);
    pushServer();
  };
  const setFrameRate = (value: number) => {
    trackRef.current?.applyConstraints({ frameRate: value }).catch(() => {});
    setSettings((s) => { const next = { ...s, frameRate: value }; saveCameraSettings(storage, role, next); return next; });
    pushServer({ fps: value });
  };
  const setFormatChoice = (fmt: string) => {
    setFormat(fmt);
    // A stricter format can lower the fps ceiling (YUY2 at 20 MP → 7.5); clamp so we never persist an
    // fps the mode can't sustain.
    const ceiling = maxFps(fmt || null, px.width, px.height);
    setSettings((s) => {
      const frameRate = Math.min(s.frameRate, ceiling);
      const next = { ...s, frameRate };
      saveCameraSettings(storage, role, next);
      return next;
    });
    pushServer({ format: fmt, fps: Math.min(settings.frameRate, ceiling) });
  };
  const setControl = (key: string, value: number) => {
    setControls((cs) => cs.map((c) => (c.key === key ? { ...c, value } : c)));
    trackRef.current?.applyConstraints(applyPayload(key, value)).catch(() => {});
    setSettings((s) => {
      const next: OverviewSettings = { ...s, manual: { ...s.manual, [key]: value } };
      saveCameraSettings(storage, role, next);
      return next;
    });
    if (key === "exposureTime") pushServer({ exposure: value });
  };

  // Above ~4K the camera usually can't stream (only shoot a still), so a failed open is expected.
  const captureOnly = px.width * px.height > 8_300_000; // > 4K (e.g. 20 MP)
  const notLiveMsg = status === "denied"
    ? (captureOnly
        ? "This resolution is a still-capture size — the live preview may not run this large."
        : "camera blocked — allow it in the browser")
    : "starting camera…";
  const fmtNote = format === "YUY2" ? "uncompressed / lossless — best for CAD"
    : format === "MJPG" ? "compressed — higher fps/resolution"
    : "driver picks the format";

  return (
    <div className="grid-gap">
      <b style={{ fontSize: 13 }}>{ROLE_LABEL[role]} camera <span className="hint" style={{ fontWeight: 400 }}>· {model ?? "assign above"}</span></b>
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
            <span className="hint" style={{ marginTop: 0 }}>{captureOnly ? "stills capture at full res · live preview runs at 4K" : "reopens the stream"}</span>
          </label>

          <label className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className="hint" style={{ minWidth: 96, marginTop: 0 }} data-tip="YUY2 = uncompressed (LOSSLESS — best for CAD, lower max fps); MJPG = compressed (higher fps/resolution); auto = let the driver choose. Forced server-side on the recorded stills — the browser can't pick a pixel format.">format</span>
            <select value={format} onChange={(e) => setFormatChoice(e.target.value)}>
              <option value="">auto</option>
              <option value="YUY2">YUY2 — lossless</option>
              <option value="MJPG">MJPG — compressed</option>
            </select>
            <span className="hint" style={{ marginTop: 0 }}>{fmtNote}</span>
          </label>

          <label className="row" style={{ gap: 8, alignItems: "center" }}>
            <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>fps</span>
            <input type="range" min={1} max={fpsCeiling} step={0.5} value={Math.min(settings.frameRate, fpsCeiling)}
              onChange={(e) => setFrameRate(Number(e.target.value))} style={{ flex: 1 }} />
            <span className="hint" style={{ minWidth: 88, textAlign: "right", marginTop: 0 }}>{Math.min(settings.frameRate, fpsCeiling)} / {fpsCeiling} fps</span>
          </label>

          {status === "live" && (controls.length === 0 ? (
            <span className="hint" style={{ marginTop: 0 }}>this camera/browser exposes no adjustable controls (exposure is auto)</span>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {controls.map((c) => (
                <label key={c.key} className="row" style={{ gap: 8, alignItems: "center" }}>
                  <span className="hint" style={{ minWidth: 96, marginTop: 0 }}
                    data-tip={c.key === "exposureTime" ? "Exposure time. The raw value is in 100-microsecond units (value 1 = 0.1 ms); the ms readout is shown live. Longer = brighter but more motion blur." : undefined}>{c.label}</span>
                  <input type="range" min={c.min} max={c.max} step={c.step} value={c.value}
                    onChange={(e) => setControl(c.key, Number(e.target.value))} style={{ flex: 1 }} />
                  <span className="hint" style={{ minWidth: 88, textAlign: "right", marginTop: 0 }}>
                    {c.key === "exposureTime" ? formatExposure(c.value) : c.value.toFixed(c.step < 1 ? 2 : 0)}
                  </span>
                </label>
              ))}
            </div>
          ))}

          <span className="hint" style={{ marginTop: 0 }}>
            {ROLE_NOTE[role]} Resolution / format / fps / exposure are written to the recorded-still capture; the sliders also tune the live preview. The exposure-to-ms readout uses the UVC/W3C 100 µs unit — verify against the recorded still on the host.
          </span>
        </>
      )}
    </div>
  );
}
