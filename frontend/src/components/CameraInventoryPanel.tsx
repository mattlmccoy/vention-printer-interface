import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";
import { inventoryRows, loadIgnoreSet, unignoreDevice, notifyIgnoreChanged, type InventoryRow } from "../lib/camera_ignore.ts";
import { applyIgnoredNames, ignoreCameraHere, useIgnoreVersion } from "../lib/camera_ignore_sync.ts";
import { allVideoInputs, isBuiltinOrPhoneLabel } from "../lib/webcam.ts";
import { CameraAccessPrompt } from "./CameraAccessPrompt.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;

type AvfCam = { index: number; name: string; unique_id: string };

const rowStyle = { justifyContent: "space-between", gap: 8, padding: "5px 0", borderTop: "1px solid var(--line)" } as const;
const tag = (text: string, tone: "ok" | "muted" | "warn" = "muted") => (
  <small className={tone === "ok" ? "okv" : "hint"} style={{ marginLeft: 6, color: tone === "warn" ? "var(--warn)" : undefined }}>{text}</small>
);

/** Settings → Camera inventory: every camera this computer sees, which are hidden from the pickers
 *  and why, and the controls to ignore / un-ignore them.
 *
 *  Two lists because the operator and the browser identify cameras differently:
 *  - Operator (macOS) cameras, keyed by a stable unique id. Ignoring one here hides it everywhere:
 *    the server drops it from roles, and every browser picker hides cameras with its name. It is
 *    also where the science camera is bound by unique id for unattended captures.
 *  - This browser's cameras, keyed by deviceId. "ignore here" is the only way to hide ONE of two
 *    identical ELPs (same name, so a name-based ignore would hide both). */
export function CameraInventoryPanel() {
  const [cams, setCams] = useState<AvfCam[]>([]);
  const [uid, setUid] = useState<string | null>(null);
  const [ignored, setIgnored] = useState<string[]>([]);
  const [ignoredNames, setIgnoredNames] = useState<string[] | null>(null); // null: older operator
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [rows, setRows] = useState<InventoryRow[]>([]);
  const [scan, setScan] = useState(0);
  const [msg, setMsg] = useState("");
  const ignoreVersion = useIgnoreVersion();

  const load = () => api.avfCameras().then((r) => {
    setCams(r.cameras); setUid(r.science_uid); setIgnored(r.ignored_uids);
    setIgnoredNames(r.ignored_names ?? null);
  }).catch(() => setCams([]));
  useEffect(() => { load(); }, []);

  useEffect(() => {
    const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
    if (!md?.enumerateDevices) return;
    let cancelled = false;
    md.enumerateDevices().then((devs) => {
      if (cancelled) return;
      setDevices(devs);
      setRows(inventoryRows(allVideoInputs(devs), loadIgnoreSet(storage)));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [scan, ignoreVersion]);

  const fail = (e: unknown) => setMsg(e instanceof Error ? e.message : "failed");
  const set = (u: string | null) => api.setScienceUid(u)
    .then((r) => { setUid(r.unique_id); setMsg(u ? "science camera bound" : "binding cleared"); })
    .catch(fail);
  const saveIgnored = (list: string[]) => api.setIgnoredCameras(list).then((r) => {
    setIgnored(r.unique_ids);
    setIgnoredNames(r.names ?? null);
    void applyIgnoredNames(storage, r.names); // hide/unhide in this browser's pickers now
  }).catch(fail);
  const ignore = (u: string) => { if (uid !== u) void saveIgnored([...ignored, u]); };
  const unignore = (u: string) => void saveIgnored(ignored.filter((x) => x !== u));
  const unignoreHere = (deviceId: string) => { unignoreDevice(storage, deviceId); notifyIgnoreChanged(); };

  const ignoredMissing = ignored.filter((u) => !cams.some((c) => c.unique_id === u)); // unplugged
  const serverStatus = (c: AvfCam) => {
    if (ignored.includes(c.unique_id)) {
      const byName = ignoredNames === null || ignoredNames.includes(c.name);
      return byName
        ? tag("ignored — hidden everywhere")
        : tag("ignored on the operator — same name as another camera, so also “ignore here” below", "warn");
    }
    if (uid === c.unique_id) return tag("science ✓", "ok");
    if (isBuiltinOrPhoneLabel(c.name)) return tag("built-in/phone — always hidden from pickers");
    return tag("shown");
  };
  const browserStatus = (r: InventoryRow) =>
    r.reason === "ignored"
      ? tag(r.ignoredHere ? "ignored in this browser" : "ignored (operator list)")
      : r.reason === "built-in"
        ? tag("built-in/phone — always hidden from pickers")
        : tag("shown", "ok");
  const labelled = rows.filter((r) => r.label);

  return (
    <div className="body">
      <div className="hint" style={{ marginTop: 0 }}>
        Every camera this computer sees, and which ones the console hides. An <b>ignored</b> camera
        never appears in any picker (live feed, camera roles, calibration) and can't hold a role;
        built-in and phone cameras are always kept out of the pickers. Ignoring persists across
        restarts.
      </div>

      <h4 style={{ margin: "14px 0 4px" }}>Operator cameras <span className="hint">· macOS, by stable id</span></h4>
      {cams.length === 0 && ignoredMissing.length === 0
        ? <div className="hint">no macOS cameras enumerated (non-macOS operator, or none detected)</div>
        : cams.map((c) => {
            const isIgnored = ignored.includes(c.unique_id);
            return (
              <div key={c.unique_id} className="row" style={{ ...rowStyle, opacity: isIgnored ? 0.65 : 1 }}>
                <span>[{c.index}] {c.name || "camera"}{serverStatus(c)} <small className="hint">{c.unique_id}</small></span>
                <span style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  {!isIgnored && uid !== c.unique_id && <button className="small" onClick={() => set(c.unique_id)}>set as science</button>}
                  {isIgnored
                    ? <button className="small" onClick={() => unignore(c.unique_id)}>un-ignore</button>
                    : <button className="small" title={uid === c.unique_id ? "clear the science binding first" : "Hide this camera everywhere"} disabled={uid === c.unique_id} onClick={() => ignore(c.unique_id)}>ignore</button>}
                </span>
              </div>
            );
          })}
      {ignoredMissing.map((u) => (
        <div key={u} className="row" style={{ ...rowStyle, opacity: 0.65 }}>
          <span><span className="hint">not connected</span>{tag("ignored")} <small className="hint">{u}</small></span>
          <button className="small" onClick={() => unignore(u)}>un-ignore</button>
        </div>
      ))}
      <div className="actions" style={{ marginTop: 8, gap: 8 }}>
        <button className="small" onClick={load}>refresh</button>
        {uid && <button className="small" onClick={() => set(null)}>clear science binding</button>}
        {msg && <span className="hint">{msg}</span>}
      </div>
      <div className="hint">
        “set as science” binds the science camera by unique id so the operator captures the right
        camera with no browser tab open. Confirm on the two-ELP rig before relying on it.
      </div>

      <h4 style={{ margin: "14px 0 4px" }}>Cameras in this browser <span className="hint">· by device id</span></h4>
      {labelled.length === 0
        ? <CameraAccessPrompt devices={devices} onGranted={() => setScan((n) => n + 1)} />
        : labelled.map((r) => (
            <div key={r.deviceId} className="row" style={{ ...rowStyle, opacity: r.reason ? 0.65 : 1 }}>
              <span>{r.display}{browserStatus(r)}</span>
              <span style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                {r.ignoredHere
                  ? <button className="small" onClick={() => unignoreHere(r.deviceId)}>un-ignore here</button>
                  : r.reason !== "ignored" && (
                      <button className="small" title="Hide this camera from every picker in this browser" onClick={() => ignoreCameraHere(storage, r.deviceId)}>ignore here</button>
                    )}
              </span>
            </div>
          ))}
      <div className="hint">
        Two identical cameras share a name, so the operator list can't tell them apart in the browser:
        use “ignore here” on the one you don't want (the numbers match the live tiles).
      </div>
    </div>
  );
}
