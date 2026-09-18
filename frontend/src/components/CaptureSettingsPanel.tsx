import { useEffect, useState } from "react";
import { api, type CameraSettings } from "../lib/api.ts";

type Role = "overview" | "science";

/** SERVER-SIDE capture settings for a camera role (GET/PUT /api/vision/settings). Unlike the live
 *  browser preview (getUserMedia can't pick a pixel format), these apply to the operator's own
 *  capture path (cv2 FOURCC/resolution/fps/exposure) — the only way to force YUY2 = uncompressed /
 *  lossless, which the science camera needs for CAD. Shows the camera model, and the format / max
 *  resolution / fps / exposure the old settings page exposed. Takes effect next time the camera opens
 *  (server-side capture = the unique-id-bound science path in "unattended science capture"). */
export function CaptureSettingsPanel({ role }: { role: Role }) {
  const [s, setS] = useState<CameraSettings | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const load = () => {
    api.visionGetSettings().then((all) => setS(all[role] ?? {})).catch(() => setS({}));
    api.visionDevices().then((d) => { const dev = d.devices.find((x) => x.role === role); setModel(dev?.name ?? null); }).catch(() => {});
  };
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const save = (patch: Partial<CameraSettings>) => {
    const next = { ...(s ?? {}), ...patch };
    setS(next);
    api.visionSetSettings({ [role]: next }).then(() => setMsg("saved — applies next time the camera opens"))
      .catch((e) => setMsg(String(e?.message ?? "save failed")));
  };

  if (!s) return <div className="hint">loading…</div>;
  const res = Array.isArray(s.resolution) ? s.resolution : [undefined, undefined];
  const w = res[0], h = res[1];

  return (
    <div className="grid-gap">
      <b style={{ fontSize: 13 }}>{role} capture settings <span className="hint" style={{ fontWeight: 400 }}>· server-side, recorded stills</span></b>
      <div className="hint" style={{ marginTop: 0 }}>
        camera: <b>{model ?? "— (assign it in the tiles above)"}</b>. These apply to the operator's own captures (the
        unique-id-bound science path), the only way to force <b>YUY2 = uncompressed/lossless</b>. Effective next time the camera opens.
      </div>
      <div className="fields" style={{ maxWidth: "none" }}>
        <span title="Pixel format. YUY2 = uncompressed (LOSSLESS — best for CAD, lower max fps/resolution over USB); MJPG = compressed (higher fps/resolution); auto = let the driver choose.">format</span>
        <select value={s.format ?? ""} onChange={(e) => save({ format: e.target.value || null })}>
          <option value="">auto (driver picks)</option>
          <option value="YUY2">YUY2 — uncompressed / lossless</option>
          <option value="MJPG">MJPG — compressed</option>
        </select>
        <span title="Capture resolution (width × height). Pair YUY2 with the camera's max resolution for lossless CAD stills.">resolution</span>
        <span className="row" style={{ gap: 6 }}>
          <input type="number" value={w ?? ""} placeholder="width" style={{ width: 90 }} onChange={(e) => save({ resolution: [Number(e.target.value) || 0, Number(h) || 0] })} /> ×
          <input type="number" value={h ?? ""} placeholder="height" style={{ width: 90 }} onChange={(e) => save({ resolution: [Number(w) || 0, Number(e.target.value) || 0] })} />
        </span>
        <span title="Capture frame rate. YUY2 at max resolution is bandwidth-heavy over USB — e.g. 7.5 fps for the science camera.">fps</span>
        <input type="number" step="0.5" value={s.fps ?? ""} placeholder="e.g. 7.5" style={{ width: 90 }} onChange={(e) => save({ fps: e.target.value === "" ? null : Number(e.target.value) })} />
        <span title="Manual exposure in the driver's units. Blank = auto-exposure.">exposure</span>
        <input type="number" value={s.exposure ?? ""} placeholder="auto" style={{ width: 90 }} onChange={(e) => save({ exposure: e.target.value === "" ? null : Number(e.target.value) })} />
      </div>
      {msg && <div className="hint">{msg}</div>}
    </div>
  );
}
