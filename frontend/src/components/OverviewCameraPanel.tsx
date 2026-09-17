import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { View } from "../lib/console.ts";
import { panelVisible, setPanelVisible } from "../lib/vision.ts";
import {
  loadOverviewCameraId,
  pickOverviewDeviceId,
  saveOverviewCameraId,
  videoInputs,
  type VideoInput,
} from "../lib/webcam.ts";
import { clampZoom, cropStyle, loadCrop, NO_CROP, panOrigin, saveCrop, type Crop } from "../lib/crop.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

// Request the sharpest live view the camera can stream (browser negotiates down if unsupported).
// Higher capture res keeps the digital crop crisp. 20MP@30 isn't streamable (USB3 bandwidth); 4K@30
// usually is, else it falls back to 1080p.
const HIRES: MediaTrackConstraints = {
  width: { ideal: 3840 },
  height: { ideal: 2160 },
  frameRate: { ideal: 30 },
};

/** Compact, collapsible live view of the OVERVIEW camera.
 *
 * Rendered client-side via getUserMedia (NOT the server MJPEG stream): the browser enumerates
 * cameras by their real label, so it always shows the physical camera we mean — unlike the server's
 * cv2 index, which mis-orders external vs Continuity cameras and kept opening the iPhone as the ELP
 * (2026-09-17). A single real (non-phone/built-in) camera auto-selects; when two are ambiguous the
 * operator picks once and it's remembered. Degrades to a labelled placeholder, never a broken icon.
 */
export function OverviewCameraPanel({ view }: { base?: string; view: View }) {
  const [visible, setVisible] = useState(() => panelVisible(view, storage));
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [inputs, setInputs] = useState<VideoInput[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => loadOverviewCameraId(storage));
  const [status, setStatus] = useState<"idle" | "live" | "pick" | "denied" | "unsupported">("idle");
  const [crop, setCrop] = useState<Crop>(NO_CROP);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const stop = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  // Enumerate cameras (needs permission for labels) and resolve which one is the overview.
  useEffect(() => {
    if (!visible) return;
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) {
      setStatus("unsupported");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Unlock device labels: enumerate, and if labels are blank, prompt once with a temp stream.
        let devs = await md.enumerateDevices();
        if (!videoInputs(devs).some((d) => d.label)) {
          const probe = await md.getUserMedia({ video: true });
          probe.getTracks().forEach((t) => t.stop());
          devs = await md.enumerateDevices();
        }
        if (cancelled) return;
        const ins = videoInputs(devs);
        setInputs(ins);
        const saved = loadOverviewCameraId(storage);
        const id = pickOverviewDeviceId(ins, saved, null);
        if (id) setSelectedId(id);
        else setStatus("pick");
      } catch {
        if (!cancelled) setStatus("denied");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible]);

  // Open the selected camera and feed the <video>.
  useEffect(() => {
    if (!visible || !selectedId) return;
    const md = navigator.mediaDevices;
    let cancelled = false;
    (async () => {
      try {
        stop();
        const stream = await md.getUserMedia({ video: { deviceId: { exact: selectedId }, ...HIRES } });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        saveOverviewCameraId(storage, selectedId);
        setCrop(loadCrop(storage, selectedId));
        setStatus("live");
      } catch {
        if (!cancelled) setStatus("pick");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, selectedId]);

  // Release the camera when hidden or unmounted.
  useEffect(() => {
    if (!visible) stop();
    return stop;
  }, [visible]);

  const toggle = () => {
    const next = !visible;
    setVisible(next);
    setPanelVisible(view, next, storage);
  };

  const changeCamera = () => {
    stop();
    setSelectedId(null);
    setStatus("pick");
  };

  const applyCrop = (next: Crop) => {
    setCrop(next);
    if (selectedId) saveCrop(storage, selectedId, next);
  };
  const onDown = (e: ReactPointerEvent) => {
    if (crop.zoom <= 1) return;
    drag.current = { x: e.clientX, y: e.clientY };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: ReactPointerEvent) => {
    if (!drag.current) return;
    const box = boxRef.current;
    if (!box) return;
    const dx = e.clientX - drag.current.x;
    const dy = e.clientY - drag.current.y;
    drag.current = { x: e.clientX, y: e.clientY };
    applyCrop(panOrigin(crop, dx, dy, box.clientWidth, box.clientHeight));
  };
  const onUp = () => {
    drag.current = null;
  };

  return (
    <section className="cam-panel">
      <header className="cam-panel-head">
        <span className="cam-panel-title">overview camera</span>
        <span className="row" style={{ gap: 6 }}>
          {status === "live" && (
            <button className="small" onClick={changeCamera} title="choose a different camera">camera</button>
          )}
          <button className="small" aria-expanded={visible} onClick={toggle}>{visible ? "hide" : "show"}</button>
        </span>
      </header>
      {visible && (
        <div className="cam-panel-body">
          <div
            ref={boxRef}
            className="cam-crop-box"
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
            onPointerLeave={onUp}
            style={{
              display: status === "live" ? "block" : "none",
              overflow: "hidden",
              width: "100%",
              cursor: crop.zoom > 1 ? (drag.current ? "grabbing" : "grab") : "default",
              touchAction: "none",
            }}
          >
            <video
              ref={videoRef}
              className="cam-panel-img"
              autoPlay
              playsInline
              muted
              style={{ display: "block", width: "100%", ...cropStyle(crop) }}
            />
          </div>
          {status === "live" && (
            <div className="row cam-crop-ctl" style={{ gap: 8, alignItems: "center", marginTop: 4 }}>
              <span className="hint">zoom</span>
              <input
                type="range" min={1} max={4} step={0.1} value={crop.zoom}
                onChange={(e) => applyCrop({ ...crop, zoom: clampZoom(Number(e.target.value)) })}
                style={{ flex: 1 }}
              />
              <span className="hint" style={{ minWidth: 34, textAlign: "right" }}>{crop.zoom.toFixed(1)}×</span>
              {(crop.zoom > 1 || crop.ox !== 50 || crop.oy !== 50) && (
                <button className="small" onClick={() => applyCrop(NO_CROP)} title="reset zoom & pan">reset</button>
              )}
            </div>
          )}
          {status !== "live" && (
            <div className="cam-panel-empty">
              <span className="cam-panel-ph" aria-hidden="true" />
              {status === "pick" ? (
                <label className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <span>select the overview camera</span>
                  <select
                    value=""
                    onChange={(e) => e.target.value && setSelectedId(e.target.value)}
                  >
                    <option value="" disabled>choose…</option>
                    {inputs.map((d) => (
                      <option key={d.deviceId} value={d.deviceId}>{d.label || d.deviceId}</option>
                    ))}
                  </select>
                </label>
              ) : (
                <span>
                  {status === "denied"
                    ? "camera access blocked — allow it in the browser"
                    : status === "unsupported"
                      ? "camera not available in this browser"
                      : "starting camera…"}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
