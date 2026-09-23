// Lightweight camera mode — for a machine whose cameras share a constrained USB path (the Windows lab
// PC: both ELPs behind a hub that also carries a USB-Ethernet adapter). Measured there 2026-09-23:
// either camera ALONE streams cleanly at every configuration; BOTH together truncate frames at 1080p
// and above, and are clean at 1280x720 @ 15 (0/11 truncated, full rate). The ELP streams isochronous,
// so each open stream RESERVES bus bandwidth. So in this mode live views are capped at LIGHT_LIVE, and
// science stills are taken with the camera ALONE at full resolution (camera_bus.ts). The Mac (one
// powered hub) keeps full-quality streaming with the mode off.

export const LIGHT_LIVE = { width: 1280, height: 720, frameRate: 15 };

const KEY = "vpi.lightweightCameras";

/** On by default on Windows (the machine with the constrained USB path), off elsewhere. */
export function lightweightDefault(ua: string): boolean {
  return /windows/i.test(ua);
}

export function loadLightweight(storage: Storage | null, ua: string): boolean {
  try {
    const v = storage?.getItem(KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch { /* storage blocked: fall through to the default */ }
  return lightweightDefault(ua);
}

export function saveLightweight(storage: Storage | null, on: boolean): void {
  try { storage?.setItem(KEY, on ? "1" : "0"); } catch { /* storage blocked */ }
}

/** Whether lightweight mode is on for this browser (localStorage, else the OS default). */
export function lightweightEnabled(): boolean {
  const storage = typeof localStorage === "undefined" ? null : localStorage;
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  return loadLightweight(storage, ua);
}

const idealOf = (v: unknown): number | null => {
  if (typeof v === "number") return v;
  if (v && typeof v === "object" && typeof (v as { ideal?: unknown }).ideal === "number") return (v as { ideal: number }).ideal;
  return null;
};

/** A live-view request, capped at LIGHT_LIVE in lightweight mode; unchanged otherwise. */
export function liveConstraints(c: MediaTrackConstraints, light: boolean): MediaTrackConstraints {
  if (!light) return c;
  const cap = (key: "width" | "height" | "frameRate", max: number) => {
    const want = idealOf(c[key]);
    return { ideal: want == null ? max : Math.min(want, max), max };
  };
  return {
    ...c,
    width: cap("width", LIGHT_LIVE.width),
    height: cap("height", LIGHT_LIVE.height),
    frameRate: cap("frameRate", LIGHT_LIVE.frameRate),
  };
}

/** The request for a full-resolution still with the camera alone on the bus: the saved resolution at
 *  a low rate, where the ELP offers its uncompressed mode (5120x3840 YUY2 is 7.5 fps). */
export function fullResConstraints(deviceId: string, resolution: string): MediaTrackConstraints {
  const [w, h] = resolution.split("x").map(Number);
  return { deviceId: { exact: deviceId }, width: { ideal: w || 1920 }, height: { ideal: h || 1080 }, frameRate: { ideal: 7.5 } };
}
