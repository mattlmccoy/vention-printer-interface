import { useEffect, useRef, useState } from "react";
import type { View } from "../lib/console.ts";
import { panelVisible, setPanelVisible } from "../lib/vision.ts";
import {
  loadOverviewCameraId,
  pickOverviewDeviceId,
  saveOverviewCameraId,
  videoInputs,
  type VideoInput,
} from "../lib/webcam.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

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
        const stream = await md.getUserMedia({ video: { deviceId: { exact: selectedId } } });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        saveOverviewCameraId(storage, selectedId);
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
          <video
            ref={videoRef}
            className="cam-panel-img"
            autoPlay
            playsInline
            muted
            style={{ display: status === "live" ? "block" : "none", width: "100%" }}
          />
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
