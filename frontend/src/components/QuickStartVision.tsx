import { useEffect, useState } from "react";
import { api, type VisionDevice, type VisionRoleMap } from "../lib/api.ts";
import { cameraAccessMessage, type CameraAccessStatus } from "../lib/vision.ts";
import type { Call } from "./views/types.ts";

const ROLES = ["overview", "science"] as const;
type Role = (typeof ROLES)[number];

/** First-run / re-assign camera-role wizard (A7 "Camera connection & role persistence").
 *
 *  Both finalized cameras share the same sensor and enumerate with near-identical names, so
 *  the operator confirms identity once by eye: this lists every detected device (GET
 *  /api/vision/devices — each already carrying its currently RESOLVED role from resolve_roles,
 *  plus a best-effort live preview for whichever one is wired as "overview") and lets the
 *  operator label which physical device is overview vs science. Saving PUTs the confirmed
 *  stable_id->role map (persistent role memory); the backend re-opens both sources against it
 *  immediately, guarded so a still-unassigned/missing device can never crash the save. */
export function QuickStartVision({ base, call, onSkip, onSaved }: {
  base: string;
  call: Call;
  onSkip: () => void;
  onSaved: () => void;
}) {
  const [devices, setDevices] = useState<VisionDevice[] | null>(null);
  const [cameraAccess, setCameraAccess] = useState<CameraAccessStatus | null>(null);
  const [assign, setAssign] = useState<Record<string, Role | "">>({});
  const [err, setErr] = useState<string | null>(null);

  const rescan = () => {
    setDevices(null);
    setCameraAccess(null);
    api.visionDevices()
      .then(({ devices: detected, camera_access }) => {
        setDevices(detected);
        setCameraAccess(camera_access);
        const initial: Record<string, Role | ""> = {};
        for (const dev of detected) {
          const key = dev.stable_id ?? String(dev.index);
          initial[key] = dev.role === "overview" || dev.role === "science" ? dev.role : "";
        }
        setAssign(initial);
      })
      .catch(() => { setDevices([]); setCameraAccess(null); });
  };

  useEffect(() => {
    let live = true;
    api.visionDevices()
      .then(({ devices: detected, camera_access }) => {
        if (!live) return;
        setDevices(detected);
        setCameraAccess(camera_access);
        const initial: Record<string, Role | ""> = {};
        for (const dev of detected) {
          const key = dev.stable_id ?? String(dev.index);
          initial[key] = dev.role === "overview" || dev.role === "science" ? dev.role : "";
        }
        setAssign(initial);
      })
      .catch(() => { if (live) { setDevices([]); setCameraAccess(null); } });
    return () => { live = false; };
  }, []);

  const setRole = (key: string, role: Role | "") => setAssign((a) => ({ ...a, [key]: role }));

  const overviewKey = Object.entries(assign).find(([, r]) => r === "overview")?.[0];
  const scienceKey = Object.entries(assign).find(([, r]) => r === "science")?.[0];
  const sameDevice = overviewKey !== undefined && overviewKey === scienceKey;
  const canSave = !!overviewKey && !!scienceKey && !sameDevice;

  const save = () => {
    setErr(null);
    if (!devices) return;
    const mapping: VisionRoleMap = {};
    for (const dev of devices) {
      const key = dev.stable_id ?? String(dev.index);
      const role = assign[key];
      // Only a device with a stable id can be persisted — an index-only fallback id would not
      // survive a USB re-enumeration, defeating the whole point of persistent role memory.
      if (role && dev.stable_id) mapping[dev.stable_id] = role;
    }
    if (Object.keys(mapping).length === 0) {
      setErr("assign at least one camera with a stable device id");
      return;
    }
    call("save camera roles", () => api.visionSetRoles(mapping).then(onSaved));
  };

  return (
    <div className="banner quickstart-vision">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b>Set up cameras</b>
        <span className="hint" style={{ marginTop: 0 }}>
          Label which detected camera is the overview (wide live view) and which is the science
          camera (bed stills) — this is remembered and reconnects automatically next time.
        </span>
      </div>
      {devices === null && <div className="hint">detecting cameras…</div>}
      {devices !== null && cameraAccess !== null && cameraAccess !== "ok" && (
        <div className="banner err" style={{ marginTop: 8 }}>
          <span className="reason">{cameraAccessMessage(cameraAccess)}</span>
          <button className="small" style={{ marginLeft: "auto" }} onClick={rescan}>rescan</button>
        </div>
      )}
      {devices !== null && devices.length === 0 && cameraAccess === "ok" && <div className="hint">no cameras detected</div>}
      {devices !== null && devices.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
          {devices.map((dev) => {
            const key = dev.stable_id ?? String(dev.index);
            return (
              <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4, width: 220 }}>
                {dev.preview_url
                  ? <img style={{ width: "100%", aspectRatio: "4/3", objectFit: "cover" }} src={`${base}${dev.preview_url}`} alt={`camera index ${dev.index} preview`} />
                  : <div className="cam-panel-empty" style={{ aspectRatio: "4/3" }}><span className="cam-panel-ph" aria-hidden="true" /><span>no preview</span></div>}
                <span>{dev.name ?? `camera index ${dev.index}`}</span>
                {dev.stable_id === null && <span className="hint" style={{ marginTop: 0 }}>no stable id — won't persist across reboot</span>}
                <select value={assign[key] ?? ""} onChange={(e) => setRole(key, e.target.value as Role | "")} disabled={dev.stable_id === null}>
                  <option value="">unassigned</option>
                  <option value="overview">overview</option>
                  <option value="science">science</option>
                </select>
              </div>
            );
          })}
        </div>
      )}
      {sameDevice && <div className="errline">overview and science can't be the same device</div>}
      {err && <div className="errline">{err}</div>}
      <div className="actions">
        <button className="cta primary" disabled={!canSave} onClick={save}>save camera roles</button>
        <button className="small" onClick={onSkip}>skip for now</button>
      </div>
    </div>
  );
}
