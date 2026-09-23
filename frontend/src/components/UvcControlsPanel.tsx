import { useEffect, useRef, useState } from "react";
import { api, type UvcControl, type UvcResetPayload } from "../lib/api.ts";
import { defaultUvcCamera, type UvcCamera } from "../lib/uvc_controls.ts";
import { formatExposure } from "../lib/camera_caps.ts";
import type { SettingsRole } from "../lib/overview_settings.ts";
import { Toggle } from "./Toggle.tsx";

const storage = typeof localStorage === "undefined" ? null : localStorage;
const pickKey = (role: SettingsRole) => `vpi.uvcCamera.${role}`;
const readPick = (role: SettingsRole): string | null => { try { return storage?.getItem(pickKey(role)) ?? null; } catch { return null; } };
const savePick = (role: SettingsRole, uid: string) => { try { storage?.setItem(pickKey(role), uid); } catch { /* storage blocked */ } };

/** Camera controls driven by the OPERATOR over UVC (macOS), for when the browser exposes none.
 *  Every range, default and value is read from the camera itself. `resetNonce` > 0 asks for a
 *  factory reset of the selected camera; the outcome goes to `onReset`. Renders nothing when the
 *  operator has no UVC backend (Windows/Linux: the browser controls cover those). */
export function UvcControlsPanel({ role, resetNonce, onReset, onAvailable }: {
  role: SettingsRole; resetNonce: number; onReset: (r: UvcResetPayload | { error: string } | null) => void;
  onAvailable: (shown: boolean) => void;
}) {
  const [cams, setCams] = useState<UvcCamera[] | null>(null);
  const [uid, setUid] = useState<string | null>(null);
  const [controls, setControls] = useState<UvcControl[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    api.uvcCameras().then((r) => {
      const list = r.available ? r.cameras : [];
      setCams(list);
      onAvailable(list.length > 0);
      setUid(defaultUvcCamera(role, list, readPick(role)));
    }).catch(() => { setCams([]); onAvailable(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  useEffect(() => {
    if (!uid) { setControls([]); return; }
    setError(null);
    api.uvcControls(uid).then((r) => setControls(r.controls)).catch((e: Error) => { setControls([]); setError(e.message); });
  }, [uid]);

  useEffect(() => {
    if (resetNonce === 0) return;
    if (!uid) { onReset(null); return; }
    api.uvcReset(uid).then((r) => { setControls(r.controls); onReset(r); })
      .catch((e: Error) => onReset({ error: e.message }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetNonce]);

  if (!cams || cams.length === 0) return null;

  const choose = (next: string) => { setUid(next); savePick(role, next); };
  const send = (key: string, value: number | boolean, delay = 0) => {
    setControls((cs) => cs.map((c) => (c.key === key ? { ...c, value } : c)));
    clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(() => {
      if (!uid) return;
      api.uvcSetControl(uid, key, value).then((r) => { setControls(r.controls); setError(null); })
        .catch((e: Error) => setError(e.message));
    }, delay);
  };
  const autoOn = (key: string | null) => key != null && controls.find((c) => c.key === key)?.value === true;
  const readout = (c: UvcControl, v: number) => (c.key === "exposure" ? formatExposure(v) : String(v));

  return (
    <div className="grid-gap" style={{ gap: 6 }}>
      <b style={{ fontSize: 13 }}>camera controls <span className="hint" style={{ fontWeight: 400 }}>· set on the camera by the operator (the browser can't reach them on macOS)</span></b>
      <label className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>USB camera</span>
        <select value={uid ?? ""} onChange={(e) => choose(e.target.value)}>
          {!uid && <option value="">choose…</option>}
          {cams.map((c) => <option key={c.unique_id} value={c.unique_id}>{c.name} · {c.unique_id}{c.science ? " · science" : ""}</option>)}
        </select>
        {!uid && <span className="hint" style={{ marginTop: 0 }}>two identical cameras — pick one; the preview above changes when you move a slider</span>}
      </label>
      {error && <div className="errline">{error}</div>}
      {controls.map((c) => {
        const locked = autoOn(c.auto_key);
        if (c.kind === "bool") {
          return (
            <label key={c.key} className="row" style={{ gap: 8, alignItems: "center" }}>
              <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>{c.label}</span>
              <Toggle checked={c.value === true} onChange={(v) => send(c.key, v)} />
              <span className="hint" style={{ marginTop: 0 }}>default {c.default ? "on" : "off"}</span>
            </label>
          );
        }
        if (c.kind === "menu") {
          return (
            <label key={c.key} className="row" style={{ gap: 8, alignItems: "center" }}>
              <span className="hint" style={{ minWidth: 96, marginTop: 0 }} data-tip={c.key === "power_line_frequency" ? "Anti-flicker for mains lighting. US mains is 60 Hz; the camera's factory setting is 50 Hz." : undefined}>{c.label}</span>
              <select value={Number(c.value)} onChange={(e) => send(c.key, Number(e.target.value))}>
                {(c.options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}{o.value === c.default ? " (default)" : ""}</option>)}
              </select>
            </label>
          );
        }
        const v = Number(c.value);
        return (
          <label key={c.key} className="row" style={{ gap: 8, alignItems: "center" }}>
            <span className="hint" style={{ minWidth: 96, marginTop: 0 }}>{c.label}</span>
            <input type="range" min={c.min} max={c.max} step={c.step} value={v} disabled={locked} aria-label={c.label}
              onChange={(e) => send(c.key, Number(e.target.value), 150)} style={{ flex: 1 }} />
            <span className="hint" style={{ minWidth: 130, textAlign: "right", marginTop: 0 }}>
              {locked ? "auto" : readout(c, v)}{v !== c.default && !locked ? ` · default ${readout(c, Number(c.default))}` : ""}
            </span>
          </label>
        );
      })}
    </div>
  );
}
