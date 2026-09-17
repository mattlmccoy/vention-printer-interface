import { useEffect, useState } from "react";
import { api, type VisionDevice, type VisionRoleMap } from "../lib/api.ts";
import { cameraAccessMessage, type CameraAccessStatus } from "../lib/vision.ts";
import {
  loadOverviewCameraId,
  overviewCandidates,
  saveOverviewCameraId,
  videoInputs,
  type VideoInput,
} from "../lib/webcam.ts";
import { CameraTiles } from "./CameraTiles.tsx";
import type { Call } from "./views/types.ts";

const ROLES = ["overview", "science"] as const;
type Role = (typeof ROLES)[number];

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** First-run / re-assign camera-role wizard (A7 "Camera connection & role persistence").
 *
 *  The two ELPs share a sensor and enumerate with identical browser labels, so a text list can't
 *  tell them apart. This wizard splits the two roles along the two ID spaces they actually live in:
 *
 *   - OVERVIEW (live wide view) is rendered client-side (getUserMedia). We show a LIVE tile per real
 *     camera — the operator clicks the one showing the print bed. That selection is saved in the
 *     browser (vpi.overviewCameraId) and is what the dock's OverviewCameraPanel displays. This is
 *     the reliable path on macOS, where the server's cv2 index mis-orders the cameras.
 *   - SCIENCE (bed stills) is captured server-side, so it needs the OS device id. We list the
 *     detected devices (GET /api/vision/devices) and persist a stable_id->role map. (Server capture
 *     of one of two identical cameras by uid is the next backend step; until then this records the
 *     assignment.) */
export function QuickStartVision({ call, onSkip, onSaved }: {
  call: Call;
  onSkip: () => void;
  onSaved: () => void;
}) {
  const [devices, setDevices] = useState<VisionDevice[] | null>(null);
  const [cameraAccess, setCameraAccess] = useState<CameraAccessStatus | null>(null);
  const [assign, setAssign] = useState<Record<string, Role | "">>({});
  const [err, setErr] = useState<string | null>(null);
  // Client-side (browser) cameras for the live overview tiles — a different id space than the
  // server devices above, so it is tracked separately.
  const [browserInputs, setBrowserInputs] = useState<VideoInput[]>([]);
  const [overviewPick, setOverviewPick] = useState<string | null>(() => loadOverviewCameraId(storage));

  const loadDevices = (live: () => boolean) => {
    api.visionDevices()
      .then(({ devices: detected, camera_access }) => {
        if (!live()) return;
        setDevices(detected);
        setCameraAccess(camera_access);
        const initial: Record<string, Role | ""> = {};
        for (const dev of detected) {
          const key = dev.stable_id ?? String(dev.index);
          initial[key] = dev.role === "overview" || dev.role === "science" ? dev.role : "";
        }
        setAssign(initial);
      })
      .catch(() => { if (live()) { setDevices([]); setCameraAccess(null); } });
  };

  const rescan = () => {
    setDevices(null);
    setCameraAccess(null);
    loadDevices(() => true);
  };

  useEffect(() => {
    let live = true;
    loadDevices(() => live);
    return () => { live = false; };
  }, []);

  // Enumerate the browser's cameras (for the live overview tiles). Labels need camera permission —
  // if they're blank, prompt once with a throwaway stream, then re-enumerate.
  useEffect(() => {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        let devs = await md.enumerateDevices();
        if (!videoInputs(devs).some((d) => d.label)) {
          const probe = await md.getUserMedia({ video: true });
          probe.getTracks().forEach((t) => t.stop());
          devs = await md.enumerateDevices();
        }
        if (!cancelled) setBrowserInputs(videoInputs(devs));
      } catch {
        // Camera blocked in the browser: the server device list + role dropdowns still work.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const setRole = (key: string, role: Role | "") => setAssign((a) => ({ ...a, [key]: role }));

  const pickOverview = (deviceId: string) => {
    saveOverviewCameraId(storage, deviceId);
    setOverviewPick(deviceId);
  };

  const scienceKey = Object.entries(assign).find(([, r]) => r === "science")?.[0];
  const overviewKey = Object.entries(assign).find(([, r]) => r === "overview")?.[0];
  const sameDevice = overviewKey !== undefined && overviewKey === scienceKey;
  // Save with AT LEAST ONE server role assigned; the client overview tile is saved on its own,
  // separately, so this button governs only the persistent server-side map (science, and optionally
  // a server overview record). The two server roles can't be the same device.
  const canSave = (!!overviewKey || !!scienceKey) && !sameDevice;

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

  const overviewTiles = (() => {
    const cands = overviewCandidates(browserInputs);
    return cands.length ? cands : browserInputs.filter((d) => d.label);
  })();

  return (
    <div className="banner quickstart-vision">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b>Set up cameras</b>
        <span className="hint" style={{ marginTop: 0 }}>
          Pick the overview (wide live view) by clicking its live feed below, and label the science
          camera (bed stills). Both are remembered and reconnect next time.
        </span>
      </div>

      {/* OVERVIEW — client-side live tiles. Click the feed that shows the print bed. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
        <b style={{ fontSize: 13 }}>Overview — live wide view</b>
        {overviewTiles.length > 0 ? (
          <>
            <span className="hint" style={{ marginTop: 0 }}>
              Click the camera showing the print bed. This is the dock’s live view, remembered on
              this computer.
            </span>
            <CameraTiles candidates={overviewTiles} selectedId={overviewPick} onPick={pickOverview} />
          </>
        ) : (
          <span className="hint" style={{ marginTop: 0 }}>
            No external camera live-view available yet — allow camera access in the browser, or plug
            in the overview camera.
          </span>
        )}
      </div>

      {/* SCIENCE / persistence — server-side device list. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
        <b style={{ fontSize: 13 }}>Science camera — bed stills</b>
        {devices === null && <div className="hint">detecting cameras…</div>}
        {devices !== null && (cameraAccess === "denied" || cameraAccess === "no_devices") && (
          <div className="banner err" style={{ marginTop: 0 }}>
            <span className="reason">{cameraAccessMessage(cameraAccess)}</span>
            <button className="small" style={{ marginLeft: "auto" }} onClick={rescan}>rescan</button>
          </div>
        )}
        {devices !== null && devices.length === 0 && (cameraAccess === "ok" || cameraAccess === "unknown") && <div className="hint">no cameras detected</div>}
        {devices !== null && devices.length > 0 && cameraAccess === "unknown" && (
          <div className="hint" style={{ marginTop: 0 }}>Identified from the OS by name — no camera was opened. Access is verified when a camera is first used.</div>
        )}
        {devices !== null && devices.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 4 }}>
            {devices.map((dev) => {
              const key = dev.stable_id ?? String(dev.index);
              return (
                <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4, width: 220 }}>
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
      </div>

      {sameDevice && <div className="errline">overview and science can't be the same device</div>}
      {err && <div className="errline">{err}</div>}
      <div className="actions">
        <button className="cta primary" disabled={!canSave} onClick={save}>save camera roles</button>
        <button className="small" onClick={onSkip}>skip for now</button>
      </div>
    </div>
  );
}
