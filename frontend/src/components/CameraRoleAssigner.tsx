import { useEffect, useState } from "react";
import { CameraTile } from "./CameraTiles.tsx";
import { CameraAccessPrompt } from "./CameraAccessPrompt.tsx";
import { labelCandidates, overviewCandidates, videoInputs, type VideoInput } from "../lib/webcam.ts";
import { assignRole, loadRoleMap, roleOf, saveRoleMap, type RoleChoice } from "../lib/camera_roles.ts";

const storage = typeof localStorage === "undefined" ? null : localStorage;

/** Assign BOTH camera roles by sight on the live tiles: each tile shows its live feed and a role
 * dropdown (— / overview / science). The overview selection is shared with the dock's live view
 * (vpi.overviewCameraId); science is remembered (vpi.scienceCameraId) for the capture-by-UID work.
 * The tiles are the ONLY identification surface — two identical ELPs share a label, so the picture
 * is how you tell them apart. Assignments are saved immediately on change. */
export function CameraRoleAssigner() {
  const [inputs, setInputs] = useState<VideoInput[]>([]);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]); // raw list: tells "hidden" from "none"
  const [scan, setScan] = useState(0); // bumped after a permission grant to re-enumerate
  const [map, setMap] = useState(() => loadRoleMap(storage));

  useEffect(() => {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.getUserMedia) return;
    let cancelled = false;
    (async () => {
      try {
        // Never call getUserMedia({video:true}) automatically to unlock labels: macOS may select and
        // wake an iPhone Continuity Camera. Existing site permission exposes labels; otherwise
        // CameraAccessPrompt offers an explicit, user-clicked grant.
        const devs = await md.enumerateDevices();
        if (!cancelled) { setDevices(devs); setInputs(videoInputs(devs)); }
      } catch {
        // Camera blocked: fall through to the hint below.
      }
    })();
    return () => { cancelled = true; };
  }, [scan]);

  const setRole = (deviceId: string, role: RoleChoice) => {
    setMap((m) => {
      const next = assignRole(m, deviceId, role);
      saveRoleMap(storage, next);
      return next;
    });
  };

  const cands = overviewCandidates(inputs);
  const tiles = cands.length ? cands : inputs.filter((d) => d.label);
  if (!tiles.length) {
    return <CameraAccessPrompt devices={devices} onGranted={() => setScan((n) => n + 1)} />;
  }
  const labeled = labelCandidates(tiles);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="cam-tiles" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {labeled.map((c) => {
          const role = roleOf(map, c.deviceId);
          return (
            <CameraTile
              key={c.deviceId}
              cam={c}
              display={c.display}
              active={role !== ""}
              badge={role || undefined}
              footer={
                <select
                  aria-label={`role for ${c.display}`}
                  value={role}
                  onChange={(e) => setRole(c.deviceId, e.target.value as RoleChoice)}
                  style={{ width: "100%", fontSize: 12 }}
                >
                  <option value="">— unassigned</option>
                  <option value="overview">overview (live)</option>
                  <option value="science">science (bed stills)</option>
                </select>
              }
            />
          );
        })}
      </div>
      <span className="hint" style={{ marginTop: 0 }}>
        Set each camera by its live picture: <b>overview</b> is the wide live view in the dock;
        <b> science</b> is the bed-stills camera. A camera can hold only one role.
      </span>
    </div>
  );
}
